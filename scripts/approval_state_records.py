"""Worker, plan estimate, and risk records kept beside the approval state."""
import json
import time
from pathlib import Path
from approval_state_store import Outcome, _cleanup, _locked, _write, session_key, state_dir


def worker_record_path(host: str, session: str) -> Path:
    return state_dir().parent / "worker-settings" / f"{host}-{session}.json"


def record_worker_pair(host: str, session, model: str, effort: str) -> None:
    """Fix the worker model and effort announced at session start; older records are pruned like approval state."""
    if session_key(session) is None:
        return
    path = worker_record_path(host, session)
    with _locked(path.parent):
        _write(path, {"model": model, "effort": effort})
        _cleanup(path.parent, path)


def recorded_worker_pair(host: str, session) -> tuple[str, str] | None:
    if session_key(session) is None:
        return None
    try:
        data = json.loads(worker_record_path(host, session).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    model, effort = (data.get(key) for key in ("model", "effort")) if isinstance(data, dict) else (None, None)
    return (model, effort) if isinstance(model, str) and isinstance(effort, str) else None


PLAN_TTL_SECONDS = 30 * 60


def plan_path(host: str, session: str) -> Path:
    return state_dir() / "db-plans" / f"{host}-{session}.json"


def _plan_entries(path: Path) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = data.get("plans") if isinstance(data, dict) else None
    now = time.time()
    return [
        entry for entry in entries or []
        if isinstance(entry, dict) and all(isinstance(entry.get(key), str) for key in ("tool", "connection", "digest"))
        and type(entry.get("at")) in (int, float) and 0 <= now - entry["at"] <= PLAN_TTL_SECONDS
    ]


def store_plan(host: str, session, tool: str, connection: str, digest: str, cost, rows) -> None:
    """Record a database read plan estimate for one session; entries older than the plan lifetime are dropped."""
    if session_key(session) is None:
        return
    path = plan_path(host, session)
    with _locked(path.parent):
        kept = [entry for entry in _plan_entries(path)
                if (entry["tool"], entry["connection"], entry["digest"]) != (tool, connection, digest)]
        kept.append({"tool": tool, "connection": connection, "digest": digest, "cost": cost, "rows": rows,
                     "at": time.time()})
        _write(path, {"plans": kept})
        _cleanup(path.parent, path)


def recorded_plan(host: str, session, tool: str, connection: str, digest: str):
    """The newest unexpired plan record for the session, tool, connection, and read digest, or None."""
    if session_key(session) is None:
        return None
    matches = [entry for entry in _plan_entries(plan_path(host, session))
               if (entry["tool"], entry["connection"], entry["digest"]) == (tool, connection, digest)]
    return max(matches, key=lambda entry: entry["at"], default=None)


RISK_LIMIT = 200
RISK_KINDS = frozenset({"write", "request", "always"})


def risk_path(host: str, session: str) -> Path:
    return state_dir() / "risk" / f"{host}-{session}.json"


def record_risk(host: str, session, tool_use_id, outcome: Outcome) -> None:
    """Record a write, request, every-time, or critical call's kind by tool_use_id for the Claude Code mod's transcript
    marker, keeping the newest entries. The record never reaches the model, and any failure only drops the marker:
    unreadable or malformed data counts as empty, and no error reaches the caller."""
    try:
        if session_key(session) is None or not isinstance(tool_use_id, str) or not tool_use_id:
            return
        if outcome.kind not in RISK_KINDS and not outcome.critical:
            return
        path = risk_path(host, session)
        with _locked(path.parent):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            calls = data.get("calls") if isinstance(data, dict) else None
            kept = [call for call in calls if isinstance(call, dict) and call.get("id") != tool_use_id] \
                if isinstance(calls, list) else []
            kept.append({"id": tool_use_id, "kind": outcome.kind, "critical": bool(outcome.critical)})
            _write(path, {"calls": kept[-RISK_LIMIT:]})
            _cleanup(path.parent, path)
    except Exception:
        return
