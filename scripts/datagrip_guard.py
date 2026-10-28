#!/usr/bin/env python3
"""Approval guard for the DataGrip `execute_sql_query` tool, shared by Claude Code and Codex.

The data source is resolved from `<projectPath>/.idea/dataSources.xml` by matching `connectionId` to the `uuid` of a
`data-source` element. The `driver-ref` selects the database: `postgresql`, or a value starting with `sqlserver` or
`azure`. Any other driver, an unreadable file, or an unknown uuid asks. With the `approval_guard` toggle on, a read on
a production data source (see db_read_policy) needs a recorded plan for PostgreSQL and gets lock and result safeguards
for SQL Server.

Only queries that are certainly reads run without approval. With the `approval_guard` toggle on, a PostgreSQL or SQL
Server write uses the shared mcp:session approval key, and Codex denies it with a one-time code. A statement whose
code (literals, comments, and quoted identifiers removed) names delete, drop, or truncate, and everything else that is
not a read, asks every time.
  - PostgreSQL with pglast: every statement must be SELECT, VALUES, TABLE, SHOW, or EXPLAIN of a SELECT without
    ANALYZE, and the parse tree must hold no INSERT, UPDATE, DELETE, MERGE, INTO, locking clause, or risky function
    call. Reads run in a read-only transaction through a prepended `SET LOCAL transaction_read_only = on;`.
  - PostgreSQL without pglast: a regex classifier over text with strings, quoted identifiers, and comments removed.
  - SQL Server: every statement starts with SELECT or WITH and holds no write, execute, or side-effect keyword.
    Session variable statements (DECLARE @v, SET @v =, INSERT [INTO] @v) and the listed session SET statements count
    as reads under the same condition.
  - Control characters, invisible format characters, JDBC escapes, unterminated literals, and parse errors ask.
Codex denies only unapproved writes and always-asking queries, through approval_state; the guard always exits 0.
While Codex's native approval window can ask (the approval guard's native_ready), it leaves a write to the
window instead and remembers the session approval it grants; an always-asking query keeps the one-time code.

Claude Code PreToolUse prints a permission decision; PermissionRequest prints nothing. Codex PreToolUse prints an
allow with the read-only prefix for PostgreSQL reads, and PermissionRequest prints an allow for any read. Anything
undecided prints nothing, which leaves the host's own approval flow in charge.

When pglast is not importable and `$XDG_STATE_HOME/hei5enbug-agent-setup/sql-parser/bin/python` exists (default
`~/.local/state`), the script re-executes itself once with that interpreter.
"""
import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.dont_write_bytecode = sys.pycache_prefix is None
sys.path.insert(0, str(Path(__file__).resolve().parent))
from plugin_toggles import enabled  # noqa: E402
import approval_state  # noqa: E402
import db_read_policy  # noqa: E402
from approval_state import Outcome  # noqa: E402
import datagrip_sql  # noqa: E402
from datagrip_sql import (  # noqa: E402
    KEYWORD_START, MSSQL_RISKY, PG_SAFE_FUNCTIONS, READ_ONLY_PRELUDE, RISKY, asks_every_time, fold,
    has_plain_backslash_string, is_destructive, is_mssql_read, is_read, postgres_read_state,
    postgres_read_state_regex, query_facts, read_shape, sanitize, session_settings, split_statements,
)

TOOL_NAME = "mcp__datagrip__execute_sql_query"
REEXEC_GUARD = "HEI5ENBUG_SQL_PARSER_REEXEC"
UNKNOWN_REASON = "The DataGrip data source could not be identified from the project settings. Review the SQL and approve it."
UNSUPPORTED_REASON = "Only PostgreSQL and SQL Server data sources are checked automatically. Review the SQL and approve it."
ASK_REASON = "This query writes or cannot be classified as a read. Review the SQL and approve it."
PG_ALLOW_REASON = "Classified as a PostgreSQL read; it runs in a read-only transaction."
MSSQL_ALLOW_REASON = "Classified as a SQL Server read; it runs without approval."


def result(decision: str, reason: str, updated_input: dict = None) -> dict:
    output = {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }
    if updated_input is not None:
        output["updatedInput"] = updated_input
    return {"hookSpecificOutput": output}


def find_data_source(tool_input: dict):
    project = tool_input.get("projectPath")
    connection_id = tool_input.get("connectionId")
    if not isinstance(project, str) or not project or not isinstance(connection_id, str) or not connection_id:
        return None
    try:
        root = ET.parse(Path(project) / ".idea" / "dataSources.xml").getroot()
    except (OSError, ET.ParseError, ValueError):
        return None
    for element in root.iter("data-source"):
        if element.get("uuid") == connection_id:
            return element
    return None


def connection_kind(tool_input: dict) -> str:
    """Return unknown, unsupported, postgres, or mssql for the data source named by the tool input."""
    source = find_data_source(tool_input)
    if source is None:
        return "unknown"
    driver = (source.findtext("driver-ref") or "").strip().lower()
    if driver == "postgresql":
        return "postgres"
    if driver.startswith("sqlserver") or driver.startswith("azure"):
        return "mssql"
    return "unsupported"


def database_target(tool_input):
    """(connection id, name, postgres, sql) for a call on a PostgreSQL or SQL Server data source, else None."""
    kind = connection_kind(tool_input) if isinstance(tool_input, dict) else "unknown"
    sql = tool_input.get("queryText") if isinstance(tool_input, dict) else None
    if kind not in ("postgres", "mssql") or not isinstance(sql, str):
        return None
    return tool_input["connectionId"], find_data_source(tool_input).get("name"), kind == "postgres", sql


def approval_on() -> bool:
    return enabled("approval_guard")


def always_outcome(tool_input, sql) -> Outcome:
    text = sql if isinstance(sql, str) else json.dumps(tool_input, sort_keys=True, default=str)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    source = find_data_source(tool_input) if isinstance(tool_input, dict) else None
    name = (source.get("name") if source is not None else None) or "an unidentified data source"
    connection = tool_input.get("connectionId") if isinstance(tool_input, dict) else None
    connection = connection if isinstance(connection, str) and connection else "unknown"
    return Outcome("always", [f"sql:always:{connection}:{digest}"], [f"DataGrip query on {name}"], every_time=True,
                   critical=db_read_policy.is_production(source.get("name") if source is not None else None))


def classify_query(tool_input) -> Outcome:
    """Classify a DataGrip query as read, write (asks once per session), or always (asks every time)."""
    sql = tool_input.get("queryText") if isinstance(tool_input, dict) else None
    kind = connection_kind(tool_input) if isinstance(tool_input, dict) else "unknown"
    source = find_data_source(tool_input) if isinstance(tool_input, dict) else None
    name = source.get("name") if source is not None else None
    if isinstance(sql, str) and asks_every_time(sql, {"postgres": True, "mssql": False}.get(kind), name):
        return always_outcome(tool_input, sql)
    if kind in ("unknown", "unsupported") or not isinstance(sql, str):
        if approval_state.session_scope():
            return always_outcome(tool_input, sql)._replace(critical=True)
        return Outcome("write", ["mcp:session"], ["DataGrip query requiring approval"])
    postgres = kind == "postgres"
    if is_read(sql, postgres):
        return Outcome("read", [], [])
    keywords, destructive = query_facts(sql, postgres, name)
    if destructive:
        return always_outcome(tool_input, sql)
    listed = ", ".join(sorted(keywords)) if keywords else "unclassified"
    if not keywords and approval_state.session_scope():
        return always_outcome(tool_input, sql)._replace(critical=True)
    return Outcome(
        "write",
        ["mcp:session"],
        [f"DataGrip write ({listed}) on {name or 'an unnamed data source'}"],
    )


def unapproved_write(tool_input, session_id, tool_use_id=None) -> dict:
    """Claude decision for a query that is not a read: an approved write runs without the prelude, anything else asks."""
    if not approval_on():
        return result("ask", ASK_REASON)
    outcome = classify_query(tool_input)
    if outcome.kind == "write" or approval_state.parent_session():
        return approval_state.pre_decision("claude", session_id, outcome, tool_use_id)
    return result("ask", ASK_REASON)


def read_policy(host: str, tool_input: dict, sql: str, postgres: bool, session_id) -> Outcome:
    """Outcome of an accepted read under the production database policy; a plain read when the approval guard is off."""
    if not approval_on():
        return Outcome("read", [], [])
    source = find_data_source(tool_input)
    return db_read_policy.read_outcome(
        host, session_id, "datagrip", tool_input.get("connectionId"), source.get("name") if source is not None else None,
        postgres, sql, read_shape(sql) if postgres else None,
    )


def policy_response(host: str, outcome: Outcome, session_id, tool_use_id):
    """The hook output for a read that the production policy denies or asks about, otherwise None."""
    if outcome.kind == "forbidden":
        return result("deny", outcome.descriptions[0])
    if outcome.kind == "always":
        return approval_state.pre_decision(host, session_id, outcome, tool_use_id)
    return None


def enforced_input(tool_input: dict, sql: str, outcome: Outcome) -> dict:
    source = find_data_source(tool_input)
    names = (tool_input.get("connectionId"), source.get("name") if source is not None else None)
    return db_read_policy.enforce("datagrip", tool_input, outcome.exe, names, session_settings(sql))


def decide_postgres(tool_input: dict, sql: str, session_id=None, tool_use_id=None) -> dict:
    if not is_read(sql, True):
        return unapproved_write(tool_input, session_id, tool_use_id)
    outcome = read_policy("claude", tool_input, sql, True, session_id)
    blocked = policy_response("claude", outcome, session_id, tool_use_id)
    if blocked is not None:
        return blocked
    read_only = postgres_read_state(sql)
    if read_only:
        return result("allow", PG_ALLOW_REASON)
    updated = dict(tool_input)
    updated["queryText"] = READ_ONLY_PRELUDE + sql
    return result("allow", PG_ALLOW_REASON, updated)


def decide_mssql(sql: str, tool_input=None, session_id=None, tool_use_id=None) -> dict:
    if is_read(sql, False):
        outcome = read_policy("claude", tool_input, sql, False, session_id) if tool_input is not None else None
        blocked = policy_response("claude", outcome, session_id, tool_use_id) if outcome is not None else None
        if blocked is not None:
            return blocked
        if outcome is not None and outcome.exe:
            return result("allow", MSSQL_ALLOW_REASON, enforced_input(tool_input, sql, outcome))
        return result("allow", MSSQL_ALLOW_REASON)
    return unapproved_write(tool_input, session_id, tool_use_id) if tool_input is not None else result("ask", ASK_REASON)


def decide(tool_input, session_id=None, tool_use_id=None) -> dict:
    if not isinstance(tool_input, dict):
        return result("ask", ASK_REASON)
    if approval_on():
        outcome = classify_query(tool_input)
        if outcome.kind != "read":
            return approval_state.pre_decision("claude", session_id, outcome, tool_use_id)
    kind = connection_kind(tool_input)
    if kind == "unknown":
        return result("ask", UNKNOWN_REASON)
    if kind == "unsupported":
        return result("ask", UNSUPPORTED_REASON)
    sql = tool_input.get("queryText")
    if not isinstance(sql, str):
        return result("ask", ASK_REASON)
    if kind == "postgres":
        return decide_postgres(tool_input, sql, session_id, tool_use_id)
    return decide_mssql(sql, tool_input, session_id, tool_use_id)


def classify_read(tool_input):
    if not isinstance(tool_input, dict):
        return None
    sql = tool_input.get("queryText")
    if not isinstance(sql, str):
        return None
    kind = connection_kind(tool_input)
    if kind == "postgres":
        if not is_read(sql, True):
            return None
        return (sql, True, postgres_read_state(sql))
    if kind == "mssql":
        return (sql, False, True) if is_read(sql, False) else None
    return None


def _native_ready(event):
    """Whether Codex's native approval window asks for this call (the approval guard decides, see native_ready)."""
    if event is None:
        return False
    import guard_permissions
    return guard_permissions.native_ready(event)


def codex_unapproved(tool_input, session_id, tool_use_id=None, event=None):
    """Codex decision for a query that is not a read: an approved write proceeds, an always query needs a one-time code.

    When the native window can ask, a write is left to it and no code is issued; an always query keeps the code flow.
    """
    if not approval_on():
        return None
    outcome = classify_query(tool_input)
    if outcome.kind in ("write", "always"):
        if (outcome.kind == "write" and approval_state.session_key(session_id) is not None
                and _native_ready(event)):
            return None
        return approval_state.pre_decision("codex", session_id, outcome, tool_use_id)
    return None


def codex_pre_tool_use(tool_input, session_id=None, tool_use_id=None, event=None):
    classified = classify_read(tool_input)
    if classified is None:
        return codex_unapproved(tool_input, session_id, tool_use_id, event)
    sql, postgres, read_only = classified
    outcome = read_policy("codex", tool_input, sql, postgres, session_id)
    blocked = policy_response("codex", outcome, session_id, tool_use_id)
    if blocked is not None:
        return blocked
    if not postgres:
        if not outcome.exe:
            return None
        updated = enforced_input(tool_input, sql, outcome)
    elif read_only:
        return None
    else:
        updated = dict(tool_input)
        updated["queryText"] = READ_ONLY_PRELUDE + sql
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "updatedInput": updated,
    }}


def codex_permission_request(tool_input, session_id=None, tool_use_id=None, event=None):
    """Allow reads and approved queries; otherwise leave the native window to ask and remember what it grants."""
    if classify_read(tool_input) is None:
        if not approval_on():
            return None
        outcome = classify_query(tool_input)
        if event is not None and outcome.kind == "write" and _native_ready(event):
            import guard_permissions
            return guard_permissions.codex_permission(session_id, outcome, tool_use_id, tool_input, TOOL_NAME, event)
        if not approval_state.permission_allowed("codex", session_id, outcome, tool_use_id):
            return None
    return approval_state.permission_allow()


def detect_host() -> str:
    root = Path(__file__).resolve().parents[1]
    codex_root = os.environ.get("PLUGIN_ROOT")
    return "codex" if codex_root and Path(codex_root).resolve() == root else "claude"


def handle(event):
    if isinstance(event, dict):
        approval_state.heartbeat(detect_host(), event.get("session_id"), event.get("hook_event_name"))
    if not isinstance(event, dict) or event.get("tool_name") != TOOL_NAME:
        return None
    name = event.get("hook_event_name")
    tool_input = event.get("tool_input")
    session_id = event.get("session_id")
    tool_use_id = event.get("tool_use_id")
    if detect_host() == "claude":
        if name != "PreToolUse":
            return None
        try:
            return decide(tool_input, session_id, tool_use_id)
        except Exception:
            return approval_state.pre_decision("claude", session_id, Outcome(
                "always", ["sql:always:guard-failure"], ["The approval guard failed to check this call"], every_time=True,
                critical=True,
            ), tool_use_id)
    try:
        if name == "PreToolUse":
            return codex_pre_tool_use(tool_input, session_id, tool_use_id, event)
        if name == "PermissionRequest":
            return codex_permission_request(tool_input, session_id, tool_use_id, event)
    except Exception:
        if name == "PreToolUse":
            return approval_state.pre_decision("codex", session_id, Outcome(
                "always", ["sql:always:guard-failure"], ["The approval guard failed to check this call"], every_time=True,
                critical=True,
            ), tool_use_id)
    return None


def parser_python() -> Path:
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "hei5enbug-agent-setup" / "sql-parser" / "bin" / "python"


def output_possible(event) -> bool:
    if not isinstance(event, dict) or event.get("tool_name") != TOOL_NAME:
        return False
    return detect_host() != "claude" or event.get("hook_event_name") == "PreToolUse"


def run_with_parser(raw: bytes):
    """Run this script under the parser interpreter with the already-read input; None when it cannot run."""
    interpreter = parser_python()
    if datagrip_sql.pglast_parser is not None or not interpreter.exists() or os.environ.get(REEXEC_GUARD):
        return None
    try:
        return subprocess.run(
            [str(interpreter), str(Path(__file__).absolute()), *sys.argv[1:]],
            input=raw,
            stdout=subprocess.PIPE,
            env={**os.environ, REEXEC_GUARD: "1"},
        )
    except OSError:
        return None


def main() -> int:
    raw = sys.stdin.buffer.read()
    try:
        event = json.loads(raw)
    except ValueError:
        return 0
    if isinstance(event, dict):
        approval_state.heartbeat(detect_host(), event.get("session_id"), event.get("hook_event_name"))
    if not enabled("datagrip_guard"):
        return 0
    if not output_possible(event):
        return 0
    child = run_with_parser(raw)
    if child is not None:
        sys.stdout.buffer.write(child.stdout)
        sys.stdout.buffer.flush()
        return child.returncode if child.returncode >= 0 else 1
    try:
        output = handle(event)
    except Exception:
        output = None
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
