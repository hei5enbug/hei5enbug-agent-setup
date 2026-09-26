from __future__ import annotations

import fcntl
from copy import deepcopy
import json
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator


PLUGIN_NAME = "hei5enbug-agent-setup"
SCHEMA_VERSION = 1
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
TERMINAL_HANDLE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
LOCK_WAIT_SECONDS = 0.8
ACTIVE_TRANSACTION_STATES = {"queued", "running", "recovering"}
TERMINAL_TRANSACTION_STATES = {"complete", "failed", "already_current", "stale_plan", "needs_manual_command", "recovered"}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def data_root_from_env(create: bool = False) -> Path | None:
    value = os.environ.get("ORCA_USER_DATA_PATH")
    if not value:
        return None
    root = Path(value).expanduser()
    if not root.is_absolute():
        return None
    app_root = root.resolve() / "plugin-session-refresh"
    if create:
        app_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            app_root.chmod(0o700)
        except OSError:
            pass
    return app_root


def registry_path(app_root: Path) -> Path:
    return app_root / "registry-v1.json"


def transaction_path(app_root: Path, transaction_id: str) -> Path:
    return app_root / "transactions" / transaction_id / "receipt.json"


def session_key(host: str, session_id: str) -> str:
    return f"{host}:{session_id}"


def fresh_registry() -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, "sessions": {}}


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    _write_json_atomic(path, payload)


@contextmanager
def registry_lock(app_root: Path, timeout: float = LOCK_WAIT_SECONDS) -> Iterator[dict[str, object]]:
    app_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = app_root / ".registry.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    lock_file = os.fdopen(descriptor, "a+")
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("registry lock is busy")
                time.sleep(0.02)
        path = registry_path(app_root)
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(payload, dict)
                or payload.get("schema_version") != SCHEMA_VERSION
                or not isinstance(payload.get("sessions"), dict)
            ):
                raise ValueError("registry schema is invalid")
        else:
            payload = fresh_registry()
        original = deepcopy(payload)
        yield payload
        _prune_ended(payload)
        if payload != original or not path.exists():
            _write_json_atomic(path, payload)
    finally:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()


def read_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON root must be an object")
    return payload


def read_transaction_state(app_root: Path, transaction_id: str) -> str | None:
    if not SESSION_ID_RE.fullmatch(transaction_id):
        return None
    try:
        receipt = read_json_object(transaction_path(app_root, transaction_id))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    state = receipt.get("state")
    return state if isinstance(state, str) else None


def transaction_may_be_active(app_root: Path, transaction_id: str) -> bool:
    return read_transaction_state(app_root, transaction_id) not in TERMINAL_TRANSACTION_STATES


def _prune_ended(registry: dict[str, object]) -> None:
    sessions = registry.get("sessions")
    if not isinstance(sessions, dict):
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    for key, record in list(sessions.items()):
        if not isinstance(record, dict) or record.get("state") != "ended":
            continue
        stamp = record.get("updated_at")
        if not isinstance(stamp, str):
            continue
        try:
            parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            continue
        if parsed < cutoff:
            del sessions[key]


def _host_and_root() -> tuple[str, Path] | None:
    codex_root = os.environ.get("PLUGIN_ROOT")
    if codex_root:
        candidate = Path(codex_root).expanduser().resolve()
        if candidate == Path(__file__).resolve().parents[1]:
            return "codex", candidate
    claude_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if claude_root:
        candidate = Path(claude_root).expanduser().resolve()
        if candidate == Path(__file__).resolve().parents[1]:
            return "claude", candidate
    return None


def _plugin_version(host: str, root: Path) -> str | None:
    manifest = root / (".codex-plugin/plugin.json" if host == "codex" else ".claude-plugin/plugin.json")
    try:
        payload = read_json_object(manifest)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    version = payload.get("version")
    return version if isinstance(version, str) and version else None


def _event_record(event: object, host: str, root: Path) -> tuple[str, str, dict[str, object]] | None:
    if not isinstance(event, dict) or event.get("agent_id"):
        return None
    event_name = event.get("hook_event_name")
    allowed = {"SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"}
    if event_name not in allowed:
        return None
    session_id = event.get("session_id")
    codex_session_id = os.environ.get("CODEX_SESSION_ID") if host == "codex" else None
    if isinstance(session_id, str) and isinstance(codex_session_id, str) and session_id != codex_session_id:
        sys.stderr.write("Plugin refresh session ID differs from the Codex environment; using the hook payload.\n")
    if not isinstance(session_id, str):
        session_id = codex_session_id
    if not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id):
        return None
    handle = os.environ.get("ORCA_TERMINAL_HANDLE")
    worktree_id = os.environ.get("ORCA_WORKTREE_ID") or os.environ.get("ORCA_WORKSPACE_ID")
    cwd = event.get("cwd")
    if (
        not isinstance(handle, str)
        or not TERMINAL_HANDLE_RE.fullmatch(handle)
        or not isinstance(worktree_id, str)
        or not worktree_id
        or not isinstance(cwd, str)
        or not Path(cwd).is_absolute()
    ):
        return None
    record: dict[str, object] = {
        "host": host,
        "session_id": session_id,
        "terminal_handle": handle,
        "worktree_id": worktree_id,
        "tab_id": os.environ.get("ORCA_TAB_ID"),
        "leaf_id": _leaf_id_from_env(),
        "cwd": str(Path(cwd).resolve()),
        "plugin_version": _plugin_version(host, root),
        "updated_at": now_utc(),
        "last_event": event_name,
    }
    return event_name, session_id, record


def _leaf_id_from_env() -> str | None:
    pane_key = os.environ.get("ORCA_PANE_KEY")
    tab_id = os.environ.get("ORCA_TAB_ID")
    if not isinstance(pane_key, str) or not isinstance(tab_id, str) or ":" not in pane_key:
        return None
    pane_tab_id, leaf_id = pane_key.rsplit(":", 1)
    if pane_tab_id != tab_id or not TERMINAL_HANDLE_RE.fullmatch(leaf_id):
        return None
    return leaf_id


def _set_state(record: dict[str, object], state: str) -> None:
    sequence = record.get("event_sequence")
    record["event_sequence"] = (sequence if isinstance(sequence, int) and sequence >= 0 else 0) + 1
    record["state"] = state
    record["updated_at"] = now_utc()


def _active_lease(record: dict[str, object], app_root: Path) -> str | None:
    transaction_id = record.get("refresh_transaction_id")
    if not isinstance(transaction_id, str) or not SESSION_ID_RE.fullmatch(transaction_id):
        return None
    if transaction_may_be_active(app_root, transaction_id):
        return transaction_id
    return None


def _emit_payload(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")


def handle_event(event: object) -> int:
    host_info = _host_and_root()
    if host_info is None:
        return 0
    host, root = host_info
    event_name = event.get("hook_event_name") if isinstance(event, dict) else None
    app_root = data_root_from_env(create=False)
    if app_root is None:
        if host == "codex" and event_name == "Stop":
            _emit_payload({})
        return 0
    parsed = _event_record(event, host, root)
    if parsed is None:
        if event_name == "UserPromptSubmit":
            _emit_payload({"decision": "block", "reason": "The Orca session identity could not be verified. Retry after checking the plugin hooks."})
        if host == "codex" and event_name == "Stop":
            _emit_payload({})
        return 0
    event_name, session_id, incoming = parsed
    sessions = fresh_registry()["sessions"]
    key = session_key(host, session_id)
    if not isinstance(sessions, dict):
        if host == "codex" and event_name == "Stop":
            _emit_payload({})
        return 0

    try:
        with registry_lock(app_root) as registry:
            stored = registry.get("sessions")
            if not isinstance(stored, dict):
                return 0
            prior = stored.get(key)
            if (
                isinstance(prior, dict)
                and prior.get("terminal_handle") != incoming["terminal_handle"]
                and event_name in {"Stop", "SessionEnd"}
            ):
                if host == "codex" and event_name == "Stop":
                    _emit_payload({})
                return 0
            record = dict(prior) if isinstance(prior, dict) else {}
            record.update(incoming)
            if isinstance(prior, dict) and prior.get("terminal_handle") != incoming["terminal_handle"]:
                record.pop("incarnation_id", None)
            lease = record.get("refresh_transaction_id")
            lease_active = _active_lease(record, app_root) if isinstance(lease, str) else None

            if event_name == "UserPromptSubmit" and lease_active:
                prompt = event.get("prompt") if isinstance(event, dict) else None
                if not (isinstance(prompt, str) and prompt.strip() in {"/exit", "/quit"}):
                    _emit_payload(
                        {
                            "decision": "block",
                            "reason": "An approved plugin refresh is restarting this session. Wait for its completion notice, then retry.",
                        }
                    )
                    return 0
            if isinstance(lease, str) and not lease_active:
                record.pop("refresh_transaction_id", None)

            if event_name != "SessionEnd":
                for other_key, other in stored.items():
                    if other_key == key or not isinstance(other, dict) or other.get("state") == "ended":
                        continue
                    same_terminal = other.get("terminal_handle") == incoming["terminal_handle"]
                    same_pane = (
                        isinstance(incoming.get("tab_id"), str)
                        and isinstance(incoming.get("leaf_id"), str)
                        and other.get("tab_id") == incoming["tab_id"]
                        and other.get("leaf_id") == incoming["leaf_id"]
                    )
                    if other.get("host") == host and other.get("worktree_id") == incoming["worktree_id"] and (same_terminal or same_pane):
                        _set_state(other, "ended")
                        other["last_event"] = "Superseded"

            if event_name == "SessionStart":
                source = event.get("source") if isinstance(event, dict) else None
                _set_state(record, "busy" if source == "compact" and isinstance(prior, dict) and prior.get("state") == "busy" else "idle")
            elif event_name == "Stop":
                background_tasks = event.get("background_tasks") if isinstance(event, dict) else None
                session_crons = event.get("session_crons") if isinstance(event, dict) else None
                clear_background = host != "claude" or (background_tasks == [] and session_crons == [])
                _set_state(record, "idle" if clear_background else "busy")
            elif event_name == "UserPromptSubmit":
                _set_state(record, "busy")
            else:
                _set_state(record, "ended")
            stored[key] = record
    except (OSError, ValueError, TimeoutError, json.JSONDecodeError):
        sys.stderr.write("Plugin refresh session state was not recorded.\n")
        if event_name == "UserPromptSubmit":
            _emit_payload({"decision": "block", "reason": "The Orca session registry is unavailable. Retry after checking the plugin refresh state."})
        if event_name == "Stop" and host == "codex":
            _emit_payload({})
        return 0

    if event_name == "Stop" and host == "codex":
        _emit_payload({})
    return 0


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        host_info = _host_and_root()
        if host_info is not None and host_info[0] == "codex":
            _emit_payload({})
        return 0
    return handle_event(event)


if __name__ == "__main__":
    raise SystemExit(main())
