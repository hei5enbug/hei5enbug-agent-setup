"""Session approval state and the host decisions built on it, shared by the approval guard and the DataGrip guard.

State lives in `$XDG_STATE_HOME/hei5enbug-agent-setup/approvals/<host>-<session_id>.json` (default `~/.local/state`).
Each file holds `approved` keys for the rest of the session, `once` keys that one call may consume, and `pending`
codes. On Codex the user approves a pending code by typing `승인 <CODE>` (or `approve <CODE>`) in chat. A hook event
without a usable session id has no memory: writes ask on Claude and are denied on Codex, and no code is stored.
"""
import fcntl
import hashlib
import json
import os
import re
import secrets
import time
from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path

# Write/request keys are session approvals. Always/sensitive keys
# need a once approval and writes need session approval. exe names a psql read so the caller can enforce read-only mode.
Outcome = namedtuple("Outcome", "kind keys descriptions exe writes", defaults=(None, ()))

KEY_SEPARATOR = "\x1f"
CODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ23456789"
CODE_LENGTH = 6
RETENTION_SECONDS = 7 * 24 * 60 * 60
SESSION_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
APPROVAL_TEXT = re.compile(r"(?:승인|approve)\s+([A-Z2-9]{6})", re.IGNORECASE)
UNKNOWN_SESSION = "the session is unknown, so the approval cannot be recorded"
RETRY_INSTRUCTION = (
    "After the user replies with the code, retry this exact call immediately and continue the task without asking again."
)
PARENT_REASON = (
    "Approval is needed in the main session: run approval_guard.py request --key <key> --why <reason> "
    "there, then retry."
)
HOOKS_PATH = Path(__file__).resolve().parents[1] / "hooks" / "hooks.json"
HOOKS_WARNING = (
    "The approval guard has not yet been seen checking a tool call since its hooks changed. "
    "On Codex, trust the plugin hooks in /hooks; until then writes may run without approval."
)


def parent_session():
    value = os.environ.get("HEI5ENBUG_PARENT_SESSION", "")
    host, separator, session = value.partition(":")
    return (host, session) if separator and host in ("claude", "codex") and session_key(session) else None


def hooks_hash():
    try:
        return hashlib.sha256(HOOKS_PATH.read_bytes()).hexdigest()
    except OSError:
        return None


def heartbeat(host, session, event_name=None):
    if session_key(session) is None and event_name != "PreToolUse":
        return
    try:
        directory = state_dir().parent / "heartbeats"
        directory.mkdir(parents=True, exist_ok=True)
        if session_key(session) is not None:
            (directory / f"{host}-{session}").touch()
            if session_key(event_name) is not None:
                (directory / f"{host}-{session}.{event_name}").touch()
        if event_name == "PreToolUse":
            digest = hooks_hash()
            if digest is not None:
                confirmed = directory / f"confirmed-{host}"
                temp = confirmed.with_name(f".{confirmed.name}.{os.getpid()}.tmp")
                temp.write_text(digest + "\n", encoding="utf-8")
                os.replace(temp, confirmed)
    except OSError:
        pass


def hooks_warning(host, session):
    digest = hooks_hash()
    try:
        confirmed = (state_dir().parent / "heartbeats" / f"confirmed-{host}").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        confirmed = None
    if digest is not None and digest == confirmed:
        return None

    def change(data):
        if data["hooks_warning_shown"]:
            return False
        data["hooks_warning_shown"] = True
        return True
    return HOOKS_WARNING if _mutate(host, session, change) else None


def state_dir() -> Path:
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "hei5enbug-agent-setup" / "approvals"


def session_key(value):
    """Return the session id when it is a usable string, otherwise None (the hook has no memory then)."""
    if isinstance(value, str) and SESSION_ID.fullmatch(value):
        return value
    return None


def pre_output(decision: str, reason: str) -> dict:
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }}


def permission_allow() -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}


def _empty() -> dict:
    return {"approved": [], "once": [], "pending": {}, "inflight": [], "hooks_warning_shown": False}


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    approved = [key for key in data.get("approved", []) if isinstance(key, str)]
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
    return {
        "approved": sorted(set(approved)), "once": sorted(set(once)), "pending": pending, "inflight": inflight,
        "hooks_warning_shown": data.get("hooks_warning_shown") is True,
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


def _path(host: str, session: str) -> Path:
    return state_dir() / f"{host}-{session}.json"


def _load(host: str, session) -> dict:
    if session_key(session) is None:
        return _empty()
    return _read(_path(host, session))


def _mutate(host: str, session, change):
    if session_key(session) is None:
        return None
    directory = state_dir()
    path = _path(host, session)
    with _locked(directory):
        data = _read(path)
        result = change(data)
        _write(path, data)
        _cleanup(directory, path)
    return result


def _new_code(data: dict) -> str:
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        if code not in data["pending"]:
            return code


def is_approved(host: str, session: str, keys) -> bool:
    approved = approved_keys(host, session)
    return all(key in approved for key in keys)


def approved_keys(host, session):
    approved = set(_load(host, session)["approved"])
    parent = parent_session()
    if parent:
        approved.update(_load(*parent)["approved"])
    return approved


def record_approved(host: str, session: str, keys) -> None:
    def change(data):
        data["approved"] = sorted(set(data["approved"]) | set(keys))
    _mutate(host, session, change)


def request_code(host: str, session: str, once_keys, session_keys, descriptions=()) -> str:
    """Return the pending code for these keys, creating one when needed. Once keys and session keys are approved apart."""
    once = sorted(set(once_keys))
    approved = sorted(set(session_keys))
    key = KEY_SEPARATOR.join(sorted(set(once) | set(approved)))

    def change(data):
        for code, entry in data["pending"].items():
            if entry.get("once_keys") == once and entry.get("session_keys") == approved:
                return code
        code = _new_code(data)
        data["pending"][code] = {
            "key": key, "once_keys": once, "session_keys": approved, "descriptions": list(descriptions),
        }
        return code
    return _mutate(host, session, change)


def approve_text(host: str, session, text) -> list:
    """Move every pending code that the text approves into `once` or `approved`; return the approved keys."""
    session = session_key(session)
    if parent_session() or session is None or not isinstance(text, str):
        return []
    codes = [match.upper() for match in APPROVAL_TEXT.findall(text)]
    if not codes:
        return []

    def change(data):
        approved_keys = []
        for code in codes:
            entry = data["pending"].pop(code, None)
            if entry is None:
                continue
            once_keys = entry.get("once_keys")
            session_keys = entry.get("session_keys")
            if once_keys is None or session_keys is None:
                keys = entry["key"].split(KEY_SEPARATOR)
                once_keys, session_keys = (keys, []) if entry.get("once") else ([], keys)
            data["once"] = sorted(set(data["once"]) | set(once_keys))
            data["approved"] = sorted(set(data["approved"]) | set(session_keys))
            approved_keys.extend([*once_keys, *session_keys])
        return approved_keys
    return _mutate(host, session, change) or []


def describe(outcome: Outcome) -> str:
    return "; ".join(outcome.descriptions)


def split_outcome(outcome: Outcome):
    """Return (once keys, session keys) that a call needs before it may proceed."""
    if outcome.kind in ("always", "sensitive"):
        return list(outcome.keys), list(outcome.writes)
    if outcome.kind in ("write", "request"):
        return [], list(outcome.keys)
    return [], []


def _tool_id(tool_use_id):
    return tool_use_id if isinstance(tool_use_id, str) and tool_use_id else None


def take_once(host: str, session: str, once_keys, session_keys, tool_use_id=None) -> bool:
    """Check and consume a call's approvals in one locked step. Consumed once keys become in-flight for this call."""
    tool_id = _tool_id(tool_use_id)
    inherited = approved_keys(host, session)

    def change(data):
        if not all(key in data["once"] for key in once_keys):
            return False
        if not all(key in inherited or key in data["once"] for key in session_keys):
            return False
        extra = [key for key in session_keys if key not in data["approved"] and key in data["once"]]
        consumed = list(dict.fromkeys([*once_keys, *extra]))
        data["once"] = [key for key in data["once"] if key not in consumed]
        data["inflight"] = [*data["inflight"], *({"key": key, "id": tool_id} for key in consumed)]
        return True
    return bool(_mutate(host, session, change))


def _in_flight_keys(data: dict, tool_id) -> set:
    return {entry["key"] for entry in data["inflight"] if tool_id is None or entry.get("id") in (None, tool_id)}


def _clear_in_flight(host: str, session: str, keys, tool_use_id) -> None:
    tool_id = _tool_id(tool_use_id)

    def change(data):
        for key in keys:
            for index, entry in enumerate(data["inflight"]):
                if entry["key"] == key and (tool_id is None or entry.get("id") in (None, tool_id)):
                    del data["inflight"][index]
                    break
    _mutate(host, session, change)


def pre_decision(host: str, session_id, outcome: Outcome, tool_use_id=None):
    """PreToolUse decision for a write or always call. Codex proceeds only with every needed approval."""
    session = session_key(session_id)
    description = describe(outcome)
    once_keys, session_keys = split_outcome(outcome)
    if parent_session():
        if outcome.kind == "request" or once_keys or not is_approved(host, session, session_keys):
            return pre_output("deny", PARENT_REASON)
        return pre_output("allow", f"Approved in the main session: {description}") if host == "claude" else None
    if host == "claude":
        if once_keys:
            return pre_output("ask", f"{description}. This action asks every time.")
        if session is not None and is_approved(host, session, session_keys):
            return pre_output("allow", f"Approved earlier in this session: {description}")
        return pre_output(
            "ask",
            f"{description}. Approving lets the same command and target run without asking for the rest of this session.",
        )
    if session is None:
        return pre_output("deny", f"Approval required: {description}. {UNKNOWN_SESSION}; ask the user before retrying.")
    if take_once(host, session, once_keys, session_keys, tool_use_id):
        return None
    code = request_code(host, session, once_keys, session_keys, outcome.descriptions)
    return pre_output("deny", (
        f"Approval required: {description}. Ask the user to reply `승인 {code}`; do not retry until they do. "
        + RETRY_INSTRUCTION
    ))


def permission_allowed(host: str, session_id, outcome: Outcome, tool_use_id=None) -> bool:
    """Whether Codex's own PermissionRequest may allow a call whose approvals are already consumed or granted."""
    session = session_key(session_id)
    once_keys, session_keys = split_outcome(outcome)
    if session is None or not (once_keys or session_keys):
        return False
    data = _load(host, session)
    approved = approved_keys(host, session)
    flying = _in_flight_keys(data, _tool_id(tool_use_id))
    return all(key in flying for key in once_keys) and all(
        key in approved or key in flying for key in session_keys
    )


def after_call(host: str, session_id, outcome: Outcome, tool_use_id=None) -> None:
    """PostToolUse bookkeeping: Claude records approved writes; Codex clears the in-flight keys of this call."""
    session = session_key(session_id)
    if session is None or parent_session():
        return
    once_keys, session_keys = split_outcome(outcome)
    if host == "claude" and session_keys:
        record_approved(host, session, session_keys)
    elif host == "codex" and (once_keys or session_keys):
        _clear_in_flight(host, session, [*once_keys, *session_keys], tool_use_id)


def approve_prompt(host, session, prompt):
    if parent_session() or not isinstance(prompt, str):
        return None
    pending = _load(host, session)["pending"]
    descriptions = [
        description for code in APPROVAL_TEXT.findall(prompt)
        for description in pending.get(code.upper(), {}).get("descriptions", [])
    ]
    keys = approve_text(host, session, prompt)
    if not keys:
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": "Approved: " + "; ".join(dict.fromkeys(descriptions or keys)) + ". " + RETRY_INSTRUCTION,
    }}
