"""Approval state primitives: the outcome tuple, session ids, and locked JSON files."""
import fcntl
import json
import os
import re
import time
from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path


# Two keys last for the rest of the session: WRITE_KEY for writes and SENSITIVE_KEY for reads that may expose a protected
# value. Every other key of an always outcome asks every time. exe names a psql read so the caller can enforce
# read-only mode. critical marks discarding local work, production database deletion, and production infrastructure
# deletion: with the `session` approval scope only those keep asking every time.
Outcome = namedtuple("Outcome", "kind keys descriptions exe writes every_time critical",
                     defaults=(None, (), False, False))
RETENTION_SECONDS = 7 * 24 * 60 * 60
SESSION_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")


def state_dir() -> Path:
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "hei5enbug-agent-setup" / "approvals"


def session_key(value):
    """Return the session id when it is a usable string, otherwise None (the hook has no memory then)."""
    if isinstance(value, str) and SESSION_ID.fullmatch(value):
        return value
    return None


def _empty() -> dict:
    return {"approved": [], "approved_at": {}, "once": [], "pending": {}, "inflight": [], "hooks_warning_shown": False,
            "request_counts": {}, "asked": []}


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    approved = [key for key in data.get("approved", []) if isinstance(key, str)]
    times = data.get("approved_at", {})
    times = times if isinstance(times, dict) else {}
    once = [key for key in data.get("once", []) if isinstance(key, str)]
    pending = data.get("pending", {})
    pending = {
        code: entry for code, entry in pending.items()
        if isinstance(entry, dict) and isinstance(entry.get("key"), str)
    } if isinstance(pending, dict) else {}
    inflight = [
        entry for entry in data.get("inflight", [])
        if isinstance(entry, dict) and isinstance(entry.get("key"), str)
    ]
    counts = data.get("request_counts", {})
    counts = {
        key: value for key, value in counts.items()
        if isinstance(key, str) and type(value) is int and value >= 0
    } if isinstance(counts, dict) else {}
    asked = [entry for entry in data.get("asked", [])
             if isinstance(entry, dict) and isinstance(entry.get("keys"), list)
             and all(isinstance(key, str) for key in entry["keys"])]
    return {
        "approved": sorted(set(approved)), "once": sorted(set(once)), "pending": pending, "inflight": inflight,
        "approved_at": {key: times[key] for key in approved if type(times.get(key)) in (int, float)},
        "hooks_warning_shown": data.get("hooks_warning_shown") is True,
        "request_counts": counts,
        "asked": asked,
    }


def _write(path: Path, data: dict) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)


def _cleanup(directory: Path, keep: Path) -> None:
    cutoff = time.time() - RETENTION_SECONDS
    for path in directory.glob("*.json"):
        if path != keep and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)


@contextmanager
def _locked(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / ".lock", "a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
