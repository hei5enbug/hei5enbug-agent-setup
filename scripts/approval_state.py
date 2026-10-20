"""Session approval state and the host decisions built on it, shared by the approval guard and the DataGrip guard.

State lives in `$XDG_STATE_HOME/hei5enbug-agent-setup/approvals/<host>-<session_id>.json` (default `~/.local/state`).
Each file holds `approved` keys that last for the rest of the session, `once` keys that one call may consume, and
`pending` codes. On Codex the user approves a pending code by typing `승인 <CODE>` (or `approve <CODE>`) in chat. A hook event
without a usable session id has no memory: writes ask on Claude and are denied on Codex, and no code is stored.
"""
import fcntl
import functools
import hashlib
import json
import os
import re
import secrets
import time
from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path

# Two keys last for the rest of the session: WRITE_KEY for writes and SENSITIVE_KEY for reads that may expose a protected
# value. Every other key of an always outcome asks every time. exe names a psql read so the caller can enforce
# read-only mode.
Outcome = namedtuple("Outcome", "kind keys descriptions exe writes every_time", defaults=(None, (), False))

WRITE_KEY = "write:session"
SENSITIVE_KEY = "sensitive:session"
SESSION_KEYS = frozenset({WRITE_KEY, SENSITIVE_KEY})
KEY_SEPARATOR = "\x1f"
CODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ23456789"
CODE_LENGTH = 6
RETENTION_SECONDS = 7 * 24 * 60 * 60
MAX_REQUESTS = 3
LINE_LIMIT = 100
PROMPTS = {
    "Korean": {
        "write": "쓰기 승인: {desc}. 한 번 승인하면 이 세션의 쓰기는 더 묻지 않습니다.",
        "every_time": "매번 승인: {desc}.",
        "sensitive": "민감 조회 승인: {desc} (값이 노출될 수 있음). 한 번 승인하면 이 세션의 민감 조회는 더 묻지 않습니다.",
        "write_scope": " 쓰기도 세션 동안 승인됩니다.",
        "sensitive_scope": " 민감 조회도 세션 동안 승인됩니다.",
        "codex": "승인 필요: {desc}. {grant}사용자에게 `승인 {code}` 입력을 요청하세요(대기 요청이 하나면 `승인`만).",
        "grant_writes": "승인하면 이 세션의 쓰기도 더 묻지 않습니다. ",
        "grant_sensitive": "승인하면 이 세션의 민감 조회도 더 묻지 않습니다. ",
        "grant_both": "승인하면 이 세션의 쓰기(와 민감 조회)도 더 묻지 않습니다. ",
        "stop": "사용자의 마지막 메시지 이후 승인 요청이 3번 완료되지 않았습니다(거절 포함). 다시 시도하지 말고 사용자에게 알리세요.",
    },
    "English": {
        "write": "Write: {desc}. Approve once; later writes in this session will not ask.",
        "every_time": "Asks every time: {desc}.",
        "sensitive": "Sensitive read: {desc} (may show a value). Later ones in this session won't ask.",
        "write_scope": " Also approves writes for this session.",
        "sensitive_scope": " Also approves sensitive reads for this session.",
        "codex": "Approval required: {desc}. {grant}Ask the user to reply `approve {code}` "
                 "(or just `approve` when only one is pending).",
        "grant_writes": "Approving also covers later writes in this session. ",
        "grant_sensitive": "Approving also covers later sensitive reads in this session. ",
        "grant_both": "Approving also covers later writes (and sensitive reads) in this session. ",
        "stop": "This approval was requested three times since the user's last message without the call completing (declines included); "
                "stop retrying and tell the user.",
    },
}
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASS|PWD|CRED|AUTH|COOKIE|PRIVATE|CERT|SAS|CONN|SIGNATURE|OTP", re.I)
_SECRET_WORD = r"[\w.-]*(?:" + SECRET_NAME.pattern + r")[\w.-]*"
_VALUE = r"""'[^']*'|"[^"]*"|[^\s'"]+"""
REDACT_LIMIT = 2000
REDACTIONS = (
    (re.compile(r"(?<![\w-])(-u|--user|--proxy-user|-b|--cookie|--oauth2-bearer)(=|\s+)(?:" + _VALUE + ")"), r"\1\2***"),
    (re.compile(r"(?<![\w-])(-u|-b)(?=[^\s=-])(?:" + _VALUE + ")"), r"\1***"),
    (re.compile(r"(?i)(?<=['\"])((?:proxy-)?authorization|cookie|x-api-key)(\s*:\s*)[^'\"\n]*"), r"\1\2***"),
    (re.compile(r"(?i)(?<![\w'\"-])((?:proxy-)?authorization|cookie|x-api-key)(\s*:\s*)[^\s'\"]+"), r"\1\2***"),
    (re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)[^/\s@'\"]*@"), r"\1***@"),
    (re.compile(r"(?<![\w.-])(" + _SECRET_WORD + r")=(?:" + _VALUE + "|)", re.I), r"\1=***"),
    (re.compile(r"(?<![\w-])(--[\w-]*(?:" + SECRET_NAME.pattern + r")[\w-]*)(\s+)(?!-)(?:" + _VALUE + ")", re.I), r"\1\2***"),
)


def redact(text: str) -> str:
    """Mask credentials in a description: -u and --user values, Authorization, Cookie, and X-Api-Key header values,
    URL userinfo, and key=value or --key value pairs whose key names a secret."""
    text = text[:REDACT_LIMIT]
    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)
    return text
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


def permission_deny(message: str) -> dict:
    return {"hookSpecificOutput": {
        "hookEventName": "PermissionRequest", "decision": {"behavior": "deny", "message": message}}}


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
        _grant(data, keys)
    _mutate(host, session, change)


def _grant(data, keys):
    for key in keys:
        if key not in data["approved"]:
            data["approved_at"][key] = time.time()
    data["approved"] = sorted(set(data["approved"]) | set(keys))


def _recoverable(data, keys):
    return {entry["key"]: entry for entry in data["inflight"]
            if entry["key"] in keys and not entry.get("retried", False)}


def _count_request(data, keys):
    keys = set(keys)
    counts = data["request_counts"]
    if any(counts.get(key, 0) >= MAX_REQUESTS for key in keys):
        return False
    for key in keys:
        counts[key] = counts.get(key, 0) + 1
    return True


def reset_request_counts(host, session):
    if parent_session() or session_key(session) is None:
        return

    def change(data):
        data["request_counts"].clear()
    _mutate(host, session, change)


def request_ask(host, session, once_keys, session_keys, tool_use_id=None, grant_keys=None):
    if session_key(session) is None:
        return True
    grant_keys = list(session_keys) if grant_keys is None else list(grant_keys)

    def change(data):
        needed = [key for key in session_keys if key not in data["approved"]]
        if not _count_request(data, [*once_keys, *needed]):
            return False
        if grant_keys:
            entry = {"id": _tool_id(tool_use_id), "keys": grant_keys}
            if entry not in data["asked"]:
                data["asked"].append(entry)
        return True
    return bool(_mutate(host, session, change))


def request_code(host: str, session: str, once_keys, session_keys, descriptions=()) -> str | None:
    """Issue a counted request for missing approvals, or None when no new request can be issued."""
    once = sorted(set(once_keys))
    approved = sorted(set(session_keys))

    def change(data):
        recoverable = _recoverable(data, once)
        needed_once = [key for key in once if key not in data["once"] and key not in recoverable]
        needed_session = [key for key in approved if key not in data["approved"] and key not in data["once"]]
        needed = [*needed_once, *needed_session]
        if not needed or not _count_request(data, needed):
            return None
        for code, entry in data["pending"].items():
            if entry.get("once_keys") == needed_once and entry.get("session_keys") == needed_session:
                return code
        code = _new_code(data)
        data["pending"][code] = {
            "key": KEY_SEPARATOR.join(sorted(set(needed))), "once_keys": needed_once,
            "session_keys": needed_session, "descriptions": [redact(item) for item in descriptions],
        }
        return code
    return _mutate(host, session, change)


def approve_text(host: str, session, text) -> list:
    """Move every pending code that the text approves into `once` or `approved`; return the approved keys."""
    session = session_key(session)
    if parent_session() or session is None or not isinstance(text, str):
        return []
    codes = [match.upper() for match in APPROVAL_TEXT.findall(text)]
    plain = text.strip().rstrip(".!。").strip().lower() in ("승인", "approve")
    if not codes and not plain:
        return []

    def change(data):
        approved_keys = []
        selected = list(data["pending"]) if plain and len(data["pending"]) == 1 else codes
        for code in selected:
            entry = data["pending"].pop(code, None)
            if entry is None:
                continue
            once_keys = entry.get("once_keys")
            session_keys = entry.get("session_keys")
            if once_keys is None or session_keys is None:
                keys = entry["key"].split(KEY_SEPARATOR)
                once_keys, session_keys = (keys, []) if entry.get("once") else ([], keys)
            data["once"] = sorted(set(data["once"]) | set(once_keys))
            _grant(data, session_keys)
            approved_keys.extend([*once_keys, *session_keys])
        return approved_keys
    return _mutate(host, session, change) or []


@functools.lru_cache(maxsize=None)
def prompt_language(host: str = "claude") -> str:
    """Return "Korean" or "English" for approval prompts, using the same `language` setting as language_guard."""
    from language_guard import claude_language, codex_language, language_name
    value = os.environ.get("HEI5ENBUG_LANGUAGE") or codex_language() if host == "codex" else (claude_language({}) or "")
    return "Korean" if value.strip() and language_name(value) == "Korean" else "English"


def stop_reason(host: str) -> str:
    return PROMPTS[prompt_language(host)]["stop"]


def describe(outcome: Outcome) -> str:
    if outcome.kind == "request":
        return redact(outcome.descriptions[-1])
    return "; ".join(redact(item) for item in outcome.descriptions)


def _clean(description: str) -> str:
    return description.strip().rstrip(".")


def _fit(description: str, room: int) -> str:
    if len(description) <= max(room, 20):
        return description
    return description[:max(room - 1, 19)] + "…"


def _cut(description: str, limit: int = 40) -> str:
    return description if len(description) <= limit else description[:limit] + "…"


def _prompt_line(template: str, description: str, scope: str = "", compound: bool = False) -> str:
    """Fill a Claude ask line. A single description fits LINE_LIMIT, keeping at least 20 characters of it; a compound
    call keeps every description, each cut to 40 characters, and the line is not limited."""
    if compound:
        return template.format(desc="; ".join(_cut(_clean(item)) for item in description)) + scope
    room = LINE_LIMIT - len(template.format(desc="") + scope)
    return template.format(desc=_fit(_clean(description), room)) + scope


def _grant_text(prompts: dict, session_keys) -> str:
    writes, sensitive = WRITE_KEY in session_keys, SENSITIVE_KEY in session_keys
    if writes and sensitive:
        return prompts["grant_both"]
    if writes:
        return prompts["grant_writes"]
    if sensitive:
        return prompts["grant_sensitive"]
    return ""


def permission_digest(tool_name, tool_input) -> str:
    """The digest that names a PermissionRequest and its PostToolUse for the same call."""
    text = json.dumps([tool_name, tool_input], sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def split_outcome(outcome: Outcome):
    """Return (every-time keys, session keys) that a call needs before it may proceed."""
    if outcome.kind in ("always", "sensitive"):
        once = [key for key in outcome.keys if key not in SESSION_KEYS]
        session = [WRITE_KEY] if outcome.writes else []
        if outcome.kind == "sensitive":
            session = [SENSITIVE_KEY, *session]
        return once, session
    if outcome.kind == "request":
        session = [SENSITIVE_KEY] if SENSITIVE_KEY in outcome.keys else []
        if any(key != SENSITIVE_KEY for key in outcome.keys):
            session.append(WRITE_KEY)
        return [], session
    if outcome.kind == "write":
        return [], [WRITE_KEY]
    return [], []


def _tool_id(tool_use_id):
    return tool_use_id if isinstance(tool_use_id, str) and tool_use_id else None


def take_once(host: str, session: str, once_keys, session_keys, tool_use_id=None) -> bool:
    """Check and consume a call's approvals in one locked step. Consumed once keys become in-flight for this call."""
    tool_id = _tool_id(tool_use_id)
    inherited = approved_keys(host, session)

    def change(data):
        recoverable = _recoverable(data, once_keys)
        if not all(key in data["once"] or key in recoverable for key in once_keys):
            return False
        if not all(key in inherited or key in data["once"] for key in session_keys):
            return False
        extra = [key for key in session_keys if key not in data["approved"] and key in data["once"]]
        consumed = list(dict.fromkeys([*once_keys, *extra]))
        entries = [{"key": key, "id": tool_id, "retried": key not in data["once"]} for key in consumed]
        data["once"] = [key for key in data["once"] if key not in consumed]
        data["inflight"] = [entry for entry in data["inflight"] if entry["key"] not in consumed] + entries
        return True
    return bool(_mutate(host, session, change))


def _in_flight_keys(data: dict, tool_id) -> set:
    return {entry["key"] for entry in data["inflight"] if tool_id is None or entry.get("id") in (None, tool_id)}


def pre_decision(host: str, session_id, outcome: Outcome, tool_use_id=None):
    """PreToolUse decision for a write or always call. Codex proceeds only with every needed approval."""
    session = session_key(session_id)
    description = describe(outcome)
    once_keys, session_keys = split_outcome(outcome)
    if parent_session():
        if outcome.kind == "request" or once_keys or not is_approved(host, session, session_keys):
            return pre_output("deny", PARENT_REASON)
        return pre_output("allow", f"Approved in the main session: {description}") if host == "claude" else None
    prompts = PROMPTS[prompt_language(host)]
    if host == "claude":
        if not once_keys and session is not None and is_approved(host, session, session_keys):
            return pre_output("allow", f"Approved earlier in this session: {description}")
        if not request_ask(host, session, once_keys, session_keys, tool_use_id, session_keys):
            return pre_output("deny", stop_reason(host))
        compound = outcome.kind != "request" and len(outcome.descriptions) > 1
        text = [redact(item) for item in outcome.descriptions] if compound else description
        if once_keys:
            scope = (prompts["write_scope"] if WRITE_KEY in session_keys else "") + (
                prompts["sensitive_scope"] if SENSITIVE_KEY in session_keys else "")
            return pre_output("ask", _prompt_line(prompts["every_time"], text, scope, compound))
        if SENSITIVE_KEY in session_keys:
            scope = prompts["write_scope"] if WRITE_KEY in session_keys else ""
            return pre_output("ask", _prompt_line(prompts["sensitive"], text, scope, compound))
        return pre_output("ask", _prompt_line(prompts["write"], text, "", compound))
    if session is None:
        return pre_output("deny", f"Approval required: {description}. {UNKNOWN_SESSION}; ask the user before retrying.")
    if take_once(host, session, once_keys, session_keys, tool_use_id):
        return None
    code = request_code(host, session, once_keys, session_keys, outcome.descriptions)
    if code is None:
        if take_once(host, session, once_keys, session_keys, tool_use_id):
            return None
        return pre_output("deny", stop_reason(host))
    line = prompts["codex"].format(desc=_clean(description), grant=_grant_text(prompts, session_keys), code=code)
    return pre_output("deny", line + "\n" + RETRY_INSTRUCTION)


def permission_allowed(host: str, session_id, outcome: Outcome, tool_use_id=None) -> bool:
    """Whether Codex's own PermissionRequest may allow a call whose approvals are already consumed or granted."""
    session = session_key(session_id)
    once_keys, session_keys = split_outcome(outcome)
    if session is None or not (once_keys or session_keys):
        return False
    data = _load(host, session)
    approved = approved_keys(host, session)
    flying = _in_flight_keys(data, _tool_id(tool_use_id))
    return all(key in flying for key in once_keys) and all(key in approved or key in flying for key in session_keys)


def _asked_entry(data, tool_id, request_id):
    """The asked entry of a completed call: the same tool_use_id first, else the same PermissionRequest digest."""
    by_id = next((entry for entry in data["asked"] if entry.get("id") == tool_id), None)
    if by_id is not None or request_id is None:
        return by_id
    return next((entry for entry in data["asked"] if entry.get("id") == request_id), None)


def after_call(host: str, session_id, outcome: Outcome, tool_use_id=None, tool_name=None, tool_input=None) -> None:
    """PostToolUse bookkeeping: a completed call grants the keys stored when it was asked; Codex also clears its keys.

    The stored keys are found by tool_use_id or by the digest of the call's tool name and input. Codex also clears
    the in-flight keys of the call; a native Codex approval completes only after the user chose to proceed.
    """
    session = session_key(session_id)
    if session is None or parent_session():
        return
    once_keys, session_keys = split_outcome(outcome)
    keys = [*once_keys, *session_keys]
    tool_id = _tool_id(tool_use_id)
    request_id = "pr:" + permission_digest(tool_name, tool_input) if tool_name is not None else None
    if not keys and _asked_entry(_load(host, session), tool_id, request_id) is None:
        return

    def change(data):
        for key in keys:
            data["request_counts"].pop(key, None)
        asked = _asked_entry(data, tool_id, request_id)
        if asked is not None:
            for key in asked["keys"]:
                data["request_counts"].pop(key, None)
            _grant(data, asked["keys"])
            data["asked"].remove(asked)
        if host == "codex":
            for key in keys:
                for index, entry in enumerate(data["inflight"]):
                    if entry["key"] == key and (tool_id is None or entry.get("id") in (None, tool_id)):
                        del data["inflight"][index]
                        break
    _mutate(host, session, change)


def approve_prompt(host, session, prompt):
    if parent_session() or not isinstance(prompt, str):
        return None
    pending = _load(host, session)["pending"]
    descriptions = [
        description for code in APPROVAL_TEXT.findall(prompt)
        for description in pending.get(code.upper(), {}).get("descriptions", [])
    ]
    if prompt.strip().rstrip(".!。").strip().lower() in ("승인", "approve") and len(pending) == 1:
        descriptions = next(iter(pending.values())).get("descriptions", [])
    keys = approve_text(host, session, prompt)
    if not keys:
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": "Approved: " + "; ".join(dict.fromkeys(descriptions or keys)) + ". " + RETRY_INSTRUCTION,
    }}
