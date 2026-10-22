"""Plan-gated reads on production databases, shared by the approval guard (tabularis) and the DataGrip guard.

A connection is production unless its name carries a development marker. A PostgreSQL production read runs only when
the same session planned the identical read in the last 30 minutes (`EXPLAIN (FORMAT JSON) <read>`) and the estimate is
within the limits; a SQL Server production read runs with lock and result safeguards instead of a plan. The approval
guard records the estimate after a plan statement succeeds.

Limits default to DEFAULT_LIMITS; `$XDG_CONFIG_HOME/hei5enbug-agent-setup/db-read-limits.json` (default `~/.config`) may
hold `{"default": {...}, "connections": {"<name or id>": {...}}}` and a matching connection entry overrides per key.
"""
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import approval_state  # noqa: E402
from approval_state import Outcome  # noqa: E402

DEFAULT_LIMITS = {
    "postgres_max_cost": 10000,
    "max_estimated_rows": 100000,
    "max_result_rows": 1000,
    "sqlserver_lock_timeout_ms": 5000,
}
INTEGER_LIMITS = frozenset({"max_estimated_rows", "max_result_rows", "sqlserver_lock_timeout_ms"})
DEFAULT_RESULT_LIMIT = 100
NONPRODUCTION_WORDS = frozenset("dev develop development test testing qa stg stage staging sandbox local demo".split())
NONPRODUCTION_MARKERS = ("개발", "테스트", "스테이징", "검증", "로컬")
PRODUCTION_WORDS = frozenset("prod production prd live".split())
PRODUCTION_MARKERS = ("운영",)
ENFORCE_POSTGRES = "db-read:postgres"
ENFORCE_SQLSERVER = "db-read:sqlserver"
BOUND_SETTING = re.compile(r"set\s+(?P<name>lock_timeout|deadlock_priority)\b(?P<value>.*)", re.I | re.S)
LIMITS_FILE = "db-read-limits.json"
TEXT_PLAN_COST = re.compile(r"\(cost=[\d.]+\.\.(?P<cost>[\d.]+)\s+rows=(?P<rows>\d+)")
BRACKETS = re.compile(r"[.\[\](){}]")


def is_production(name) -> bool:
    """A connection is non-production only when its name has a development word or marker and no production word or
    marker; unknown names are production."""
    if not isinstance(name, str) or not name.strip():
        return True
    from approval_guard import tool_words
    words = set(tool_words(BRACKETS.sub(" ", name)))
    if PRODUCTION_WORDS & words or any(marker in name for marker in PRODUCTION_MARKERS):
        return True
    return not (NONPRODUCTION_WORDS & words or any(marker in name for marker in NONPRODUCTION_MARKERS))


def limits_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "hei5enbug-agent-setup" / LIMITS_FILE


def _limit_value(key, value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        return None
    if key in INTEGER_LIMITS:
        return int(value) if value >= 1 else None
    return value


def limits(*identifiers) -> dict:
    """The limits for a connection given its name and id; an unreadable or invalid file gives the defaults."""
    merged = dict(DEFAULT_LIMITS)
    try:
        data = json.loads(limits_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return merged
    if not isinstance(data, dict):
        return merged
    layers = [data.get("default")]
    connections = data.get("connections")
    if isinstance(connections, dict):
        layers.extend(connections.get(identifier) for identifier in identifiers if isinstance(identifier, str))
    for layer in layers:
        if isinstance(layer, dict):
            for key in DEFAULT_LIMITS:
                value = _limit_value(key, layer.get(key))
                if value is not None:
                    merged[key] = value
    return merged


def normalize(sql: str) -> str:
    """The exact statement text: only outer whitespace and trailing semicolons are dropped, every inner character stays."""
    text = sql.strip()
    while text.endswith(";"):
        text = text[:-1].rstrip()
    return text


def read_digest(sql: str) -> str:
    return hashlib.sha256(normalize(sql).encode("utf-8")).hexdigest()[:16]


def plan_form(read: str) -> str:
    return "EXPLAIN (FORMAT JSON) " + normalize(read)


def _plan_json(value):
    plan = value[0] if isinstance(value, list) and value else value
    plan = plan.get("Plan") if isinstance(plan, dict) else None
    cost, rows = (plan.get(key) for key in ("Total Cost", "Plan Rows")) if isinstance(plan, dict) else (None, None)
    if all(type(number) in (int, float) and math.isfinite(number) for number in (cost, rows)):
        return float(cost), float(rows)
    return None


def _plan_cell(cell):
    if isinstance(cell, (list, dict)):
        return _plan_json(cell)
    if not isinstance(cell, str):
        return None
    try:
        value = json.loads(cell)
    except ValueError:
        value = None
    if isinstance(value, (list, dict)):
        return _plan_json(value)
    line = next((line for line in cell.splitlines() if line.strip()), "")
    match = TEXT_PLAN_COST.search(line)
    return (float(match.group("cost")), float(match.group("rows"))) if match else None


def _first_cell(payload):
    """The first data cell of a tabularis result (`rows`) or a DataGrip result (CSV `text` with a header row)."""
    if isinstance(payload.get("rows"), list):
        rows = payload["rows"]
        return rows[0][0] if rows and isinstance(rows[0], list) and rows[0] else None
    if isinstance(payload.get("text"), str):
        rows = list(csv.reader(io.StringIO(payload["text"])))
        return rows[1][0] if len(rows) > 1 and rows[1] else None
    return None


def _payloads(response):
    if isinstance(response, str):
        try:
            value = json.loads(response)
        except ValueError:
            return
        if isinstance(value, dict):
            yield value
    elif isinstance(response, list):
        for item in response:
            yield from _payloads(item)
    elif isinstance(response, dict):
        if response.get("type") == "text" and isinstance(response.get("text"), str):
            yield from _payloads(response["text"])
        elif isinstance(response.get("content"), (list, str)):
            yield from _payloads(response["content"])
        else:
            yield response


def plan_estimate(response):
    """(estimated cost, estimated rows) from a successful PostgreSQL plan result, or None for an error, an empty result,
    or a plan without an estimate. The result may be a string, a list of content blocks, or an object with `content`."""
    for payload in _payloads(response):
        if any(payload.get(key) for key in ("errorMessage", "error")) or payload.get("isError") is True:
            return None
        try:
            estimate = _plan_cell(_first_cell(payload))
        except (csv.Error, IndexError, TypeError):
            estimate = None
        if estimate is not None:
            return estimate
    return None


def record_plan(host, session, tool, connection, read, response) -> bool:
    """Record the estimate of a successful plan result for the identical read; False when nothing was recorded."""
    estimate = plan_estimate(response)
    if estimate is None:
        return False
    approval_state.store_plan(host, session, tool, connection, read_digest(read), *estimate)
    return True


def _every_time(tool, connection, digest, description):
    return Outcome("always", [f"dbplan:{tool}:{connection}:{digest}"], [description], every_time=True)


def _loosened_setting(sql, lock_timeout_limit):
    """The name of the first SQL Server LOCK_TIMEOUT or DEADLOCK_PRIORITY statement in the read that is outside the
    safe bounds (a LOCK_TIMEOUT from 0 to the limit, a DEADLOCK_PRIORITY of LOW or -5 or lower), else None."""
    from datagrip_guard import fold, split_statements
    try:
        statements = split_statements(sql, False)
    except ValueError:
        return "LOCK_TIMEOUT"
    for statement in statements:
        match = BOUND_SETTING.fullmatch(fold(statement))
        if match is None:
            continue
        name, value = match.group("name").upper(), match.group("value").strip()
        if name == "LOCK_TIMEOUT":
            safe = re.fullmatch(r"\d+", value) is not None and int(value) <= lock_timeout_limit
        else:
            safe = value.upper() == "LOW" or (re.fullmatch(r"-\d+", value) is not None and int(value) <= -5)
        if not safe:
            return name
    return None


def read_outcome(host, session, tool, connection, name, postgres, sql, shape) -> Outcome:
    """Outcome of a read that the SQL classifier already accepted: read, forbidden (deny with guidance), or always.

    `shape` is the datagrip_guard.read_shape of a PostgreSQL read. A read outcome with `exe` set must run through
    `enforce`.
    """
    if not is_production(name):
        return Outcome("read", [], [])
    if not postgres:
        unsafe = _loosened_setting(sql, limits(connection, name)["sqlserver_lock_timeout_ms"])
        if unsafe is not None:
            return _every_time(tool, connection, read_digest(sql),
                               f"unsafe SET {unsafe} in {tool} production read on {name or connection}")
        return Outcome("read", [], [], ENFORCE_SQLSERVER)
    kind, read = shape
    if kind == "plan":
        return Outcome("read", [], [])
    label = f"{tool} production read on {name or connection}"
    if kind != "read":
        return _every_time(tool, connection, read_digest(sql), f"{label} cannot be planned as one statement")
    digest = read_digest(read)
    record = approval_state.recorded_plan(host, session, tool, connection, digest)
    bound = limits(connection, name)
    if record is None:
        return Outcome("forbidden", [], [
            f"Production database read: first run `{plan_form(read)}` (never ANALYZE) on the same connection, then run "
            f"the identical read text. The estimate must be at most cost {bound['postgres_max_cost']:g} and "
            f"{bound['max_estimated_rows']:g} rows."])
    cost, rows = record.get("cost"), record.get("rows")
    if not all(type(number) in (int, float) and math.isfinite(number) for number in (cost, rows)):
        return _every_time(tool, connection, digest, f"unparsed plan for {label}")
    if cost > bound["postgres_max_cost"] or rows > bound["max_estimated_rows"]:
        return _every_time(tool, connection, digest, f"estimated cost {cost:g}, rows {rows:g} over the limits ({label})")
    return Outcome("read", [], [], ENFORCE_POSTGRES)


def enforce(tool, tool_input, exe, identifiers, existing=()):
    """The tool input of a production read with its result limit and the SQL Server lock safeguards in front of it.

    `existing` is accepted for older callers and ignored: the guard's own settings always come first, and
    `read_outcome` has already checked every setting the read makes itself.
    """
    bound = limits(*identifiers)
    updated = dict(tool_input)
    if tool == "tabularis":
        requested = tool_input.get("limit")
        requested = requested if type(requested) is int and requested > 0 else DEFAULT_RESULT_LIMIT
        updated["limit"] = min(requested, bound["max_result_rows"])
    if exe == ENFORCE_SQLSERVER:
        field = "query" if tool == "tabularis" else "queryText"
        updated[field] = f"SET LOCK_TIMEOUT {bound['sqlserver_lock_timeout_ms']};\nSET DEADLOCK_PRIORITY LOW;\n" \
            + tool_input[field]
    return updated
