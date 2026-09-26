from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Sequence

if __package__:
    from .session_lifecycle import (
        ACTIVE_TRANSACTION_STATES,
        TERMINAL_HANDLE_RE,
        data_root_from_env,
        now_utc,
        read_json_object,
        registry_lock,
        session_key,
        transaction_may_be_active,
        transaction_path,
        write_json_atomic,
    )
else:
    from session_lifecycle import (
        ACTIVE_TRANSACTION_STATES,
        TERMINAL_HANDLE_RE,
        data_root_from_env,
        now_utc,
        read_json_object,
        registry_lock,
        session_key,
        transaction_may_be_active,
        transaction_path,
        write_json_atomic,
    )


PLUGIN_NAME = "hei5enbug-agent-setup"
MARKETPLACE_NAME = "hei5enbug"
EXPECTED_REPO_URL = "https://github.com/hei5enbug/hei5enbug-agent-setup.git"
EXPECTED_CLAUDE_REPO = "hei5enbug/hei5enbug-agent-setup"
PLAN_SCHEMA_VERSION = 1
TRANSACTION_SCHEMA_VERSION = 1
PLAN_TTL = timedelta(minutes=30)
PLAN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
SUPPORTED_AGENTS = {"codex": {"codex"}, "claude": {"claude", "claude-code", "claude code"}}


class RefreshError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
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


@contextmanager
def file_lock(path: Path, *, blocking: bool = True, timeout: float = 3.0) -> Iterator[None]:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    stream = os.fdopen(descriptor, "a+")
    try:
        if blocking:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RefreshError("lock_busy", "Another plugin refresh operation is active.")
                    time.sleep(0.03)
        else:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RefreshError("worker_active", "The transaction worker is still running.") from error
        yield
    finally:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


def require_data_root(*, create: bool) -> Path:
    if sys.platform not in {"darwin", "linux"}:
        raise RefreshError("unsupported_platform", "This workflow supports macOS and Linux only.")
    app_root = data_root_from_env(create=create)
    if app_root is None:
        raise RefreshError("not_orca", "Run this workflow from an Orca-managed agent terminal.")
    if create:
        app_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            app_root.chmod(0o700)
        except OSError:
            pass
    return app_root


def orca_command() -> list[str]:
    configured = os.environ.get("ORCA_CLI_COMMAND")
    if configured:
        return [configured]
    if os.environ.get("ORCA_DEV_REPO_ROOT"):
        executable = shutil.which("orca-dev")
        if executable:
            return [executable]
        raise RefreshError("orca_cli_missing", "The configured Orca development CLI is unavailable.")
    if not os.environ.get("ORCA_WORKTREE_ID") and not os.environ.get("ORCA_WORKSPACE_ID"):
        raise RefreshError("not_orca", "Run this workflow from an Orca-managed agent terminal.")
    executable_name = "orca-ide" if sys.platform == "linux" and os.environ.get("TERM_PROGRAM") != "Orca" else "orca"
    executable = shutil.which(executable_name)
    if not executable:
        raise RefreshError("orca_cli_missing", f"The selected Orca CLI is unavailable: {executable_name}.")
    return [executable]


def executable(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RefreshError("command_missing", f"Required command is unavailable: {name}.")
    return path


def run_command(
    argv: Sequence[str],
    *,
    timeout: float = 30.0,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RefreshError("command_timeout", f"{Path(argv[0]).name} did not finish before its timeout.") from error
    except OSError as error:
        raise RefreshError("command_failed", f"{Path(argv[0]).name} could not be started.") from error
    if check and result.returncode != 0:
        raise RefreshError("command_failed", f"{Path(argv[0]).name} failed with exit code {result.returncode}.")
    return result


def parse_json_output(result: subprocess.CompletedProcess[str], command_name: str) -> object:
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise RefreshError("invalid_cli_json", f"{command_name} returned unreadable JSON.") from error
    if isinstance(payload, dict) and payload.get("ok") is False:
        raise RefreshError("orca_rejected", f"{command_name} was rejected by Orca.")
    return payload


def run_json(argv: Sequence[str], *, timeout: float = 30.0) -> object:
    result = run_command(argv, timeout=timeout)
    return parse_json_output(result, Path(argv[0]).name)


def unwrap_orca(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise RefreshError("invalid_orca_response", "Orca returned an unsupported response shape.")
    result = payload.get("result", payload)
    if not isinstance(result, dict):
        raise RefreshError("invalid_orca_response", "Orca returned an unsupported result shape.")
    return result


def orca_send_receipt(payload: object) -> dict[str, object]:
    send = unwrap_orca(payload).get("send")
    if not isinstance(send, dict) or send.get("accepted") is not True:
        raise RefreshError("input_not_accepted", "Orca did not confirm terminal input acceptance.")
    return send


def base_version(version: object) -> str:
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise RefreshError("invalid_version", "A plugin manifest contains an unsupported version string.")
    return version.split("+", 1)[0]


def version_core(version: str) -> tuple[int, int, int]:
    stable = version.split("-", 1)[0]
    try:
        major, minor, patch = stable.split(".")
        return int(major), int(minor), int(patch)
    except (ValueError, TypeError) as error:
        raise RefreshError("invalid_version", "A plugin version is not a supported semantic version.") from error


def read_manifest_version(root: Path, host: str) -> str:
    manifest = root / (".codex-plugin/plugin.json" if host == "codex" else ".claude-plugin/plugin.json")
    try:
        payload = read_json_object(manifest)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise RefreshError("manifest_unavailable", f"The {host} marketplace plugin manifest is unavailable.") from error
    if payload.get("name") != PLUGIN_NAME:
        raise RefreshError("wrong_plugin", f"The {host} marketplace points to a different plugin.")
    return base_version(payload.get("version"))


def installed_plugins(host: str) -> tuple[dict[str, object], dict[str, object]]:
    if host == "codex":
        payload = run_json([executable("codex"), "plugin", "list", "--json"])
        if not isinstance(payload, dict):
            raise RefreshError("invalid_plugin_list", "Codex returned an unsupported plugin list.")
        installed = payload.get("installed")
        matches = [
            item for item in installed if isinstance(item, dict) and item.get("pluginId") == f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"
        ] if isinstance(installed, list) else []
        if len(matches) != 1:
            raise RefreshError("codex_plugin_missing", "The Codex plugin is not installed exactly once.")
        item = matches[0]
        if item.get("enabled") is not True:
            raise RefreshError("codex_plugin_disabled", "The Codex plugin must be enabled before it can be refreshed.")
        source = item.get("marketplaceSource")
        if not isinstance(source, dict) or source.get("sourceType") != "git" or source.get("source") != EXPECTED_REPO_URL:
            raise RefreshError("codex_marketplace_mismatch", "Codex is not using the expected GitHub marketplace source.")
        marketplaces = run_json([executable("codex"), "plugin", "marketplace", "list", "--json"])
        if not isinstance(marketplaces, dict) or not isinstance(marketplaces.get("marketplaces"), list):
            raise RefreshError("invalid_marketplace_list", "Codex returned an unsupported marketplace list.")
        entries = [
            value for value in marketplaces["marketplaces"]
            if isinstance(value, dict) and value.get("name") == MARKETPLACE_NAME
        ]
        if len(entries) != 1 or not isinstance(entries[0].get("root"), str):
            raise RefreshError("codex_marketplace_missing", "The configured Codex marketplace root is unavailable.")
        root = Path(entries[0]["root"]).expanduser().resolve()
        if not root.is_dir():
            raise RefreshError("codex_marketplace_missing", "The configured Codex marketplace directory is unavailable.")
        marketplace_source = entries[0].get("marketplaceSource")
        if (
            not isinstance(marketplace_source, dict)
            or marketplace_source.get("sourceType") != "git"
            or marketplace_source.get("source") != EXPECTED_REPO_URL
        ):
            raise RefreshError("codex_marketplace_mismatch", "The configured Codex marketplace source does not match this repository.")
        item_version = base_version(item.get("version"))
        return item, {"root": str(root), "catalog_version": read_manifest_version(root, "codex"), "installed_version": item_version}

    payload = run_json([executable("claude"), "plugin", "list", "--json"])
    if not isinstance(payload, list):
        raise RefreshError("invalid_plugin_list", "Claude Code returned an unsupported plugin list.")
    matches = [
        item for item in payload if isinstance(item, dict) and item.get("id") == f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"
    ]
    if len(matches) != 1:
        raise RefreshError("claude_plugin_missing", "The Claude Code plugin is not installed exactly once.")
    item = matches[0]
    if item.get("enabled") is not True or item.get("scope") != "user":
        raise RefreshError("claude_plugin_scope", "The Claude Code plugin must be enabled at user scope.")
    marketplaces = run_json([executable("claude"), "plugin", "marketplace", "list", "--json"])
    if not isinstance(marketplaces, list):
        raise RefreshError("invalid_marketplace_list", "Claude Code returned an unsupported marketplace list.")
    entries = [
        value for value in marketplaces if isinstance(value, dict) and value.get("name") == MARKETPLACE_NAME
    ]
    if len(entries) != 1 or entries[0].get("repo") != EXPECTED_CLAUDE_REPO:
        raise RefreshError("claude_marketplace_mismatch", "Claude Code is not using the expected GitHub marketplace source.")
    location = entries[0].get("installLocation")
    if not isinstance(location, str):
        raise RefreshError("claude_marketplace_missing", "The configured Claude Code marketplace root is unavailable.")
    root = Path(location).expanduser().resolve()
    if not root.is_dir():
        raise RefreshError("claude_marketplace_missing", "The configured Claude Code marketplace directory is unavailable.")
    return item, {"root": str(root), "catalog_version": read_manifest_version(root, "claude"), "installed_version": base_version(item.get("version"))}


def git_revision(root: Path) -> str | None:
    result = run_command([executable("git"), "-C", str(root), "rev-parse", "HEAD"], timeout=5, check=False)
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", value):
        return None
    status = run_command([executable("git"), "-C", str(root), "status", "--porcelain", "--untracked-files=all"], timeout=5, check=False)
    return value if status.returncode == 0 and not status.stdout.strip() else None


def supported_host(identity: object) -> str | None:
    if not isinstance(identity, str):
        return None
    normalized = identity.strip().lower()
    for host, aliases in SUPPORTED_AGENTS.items():
        if normalized in aliases:
            return host
    return None


def terminal_inventory() -> list[dict[str, object]]:
    payload = run_json([*orca_command(), "terminal", "list", "--json"], timeout=15)
    result = unwrap_orca(payload)
    terminals = result.get("terminals")
    total_count = result.get("totalCount")
    if not isinstance(terminals, list) or not isinstance(total_count, int):
        raise RefreshError("invalid_terminal_list", "Orca returned an unsupported terminal list.")
    if result.get("truncated") is True or total_count > len(terminals):
        raise RefreshError("terminal_list_truncated", "Orca truncated the terminal list; no sessions were changed.")
    selected: list[dict[str, object]] = []
    for value in terminals:
        if not isinstance(value, dict):
            continue
        host = supported_host(value.get("agentIdentity"))
        if host is None:
            continue
        handle = value.get("handle")
        incarnation_id = value.get("incarnationId")
        worktree_id = value.get("worktreeId")
        worktree_path = value.get("worktreePath")
        if not isinstance(handle, str) or not TERMINAL_HANDLE_RE.fullmatch(handle):
            raise RefreshError("terminal_handle_missing", "An Orca agent terminal has no usable handle.")
        if not isinstance(incarnation_id, str) or not incarnation_id:
            raise RefreshError("terminal_incarnation_missing", "An Orca agent terminal has no process incarnation ID.")
        worktree = Path(worktree_path).expanduser() if isinstance(worktree_path, str) and worktree_path else None
        if not isinstance(worktree_id, str) or not worktree_id or worktree is None or not worktree.is_absolute():
            raise RefreshError(
                "terminal_worktree_missing",
                "An Orca agent terminal has no absolute worktree path; floating agent terminals cannot be refreshed.",
            )
        selected.append(
            {
                "host": host,
                "terminal_handle": handle,
                "incarnation_id": incarnation_id,
                "worktree_id": worktree_id,
                "worktree_path": str(worktree.resolve()),
                "tab_id": value.get("tabId"),
                "leaf_id": value.get("leafId"),
                "title": value.get("title"),
                "connected": value.get("connected") is True,
                "writable": value.get("writable") is True,
                "orphaned": value.get("orphaned") is True,
            }
        )
    return selected


def wait_terminal(handle: str, condition: str, timeout_ms: int) -> bool:
    payload = run_json(
        [*orca_command(), "terminal", "wait", "--terminal", handle, "--for", condition, "--timeout-ms", str(timeout_ms), "--json"],
        timeout=(timeout_ms / 1000) + 10,
    )
    result = unwrap_orca(payload)
    wait = result.get("wait")
    if isinstance(wait, dict):
        return wait.get("satisfied") is True
    return result.get("satisfied") is True


def registry_sessions(app_root: Path) -> dict[str, dict[str, object]]:
    with registry_lock(app_root) as registry:
        sessions = registry.get("sessions")
        if not isinstance(sessions, dict):
            raise RefreshError("registry_invalid", "The Orca session registry has an invalid shape.")
        return {key: dict(value) for key, value in sessions.items() if isinstance(value, dict)}


def plan_directory(app_root: Path) -> Path:
    path = app_root / "plans"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def prune_old_local_state(app_root: Path) -> None:
    cutoff = utc_now() - timedelta(days=30)
    plans = plan_directory(app_root)
    for path in plans.glob("*.json"):
        if path.is_symlink() or not PLAN_ID_RE.fullmatch(path.stem):
            continue
        try:
            payload = read_json_object(path)
            expiry = parse_time(payload.get("expires_at"))
            if expiry is not None and expiry < cutoff:
                path.unlink()
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    transactions = app_root / "transactions"
    if not transactions.is_dir():
        return
    for directory in transactions.iterdir():
        if directory.is_symlink() or not directory.is_dir() or not PLAN_ID_RE.fullmatch(directory.name):
            continue
        receipt_path = directory / "receipt.json"
        try:
            receipt = read_json_object(receipt_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if receipt.get("state") in ACTIVE_TRANSACTION_STATES:
            continue
        updated = parse_time(receipt.get("updated_at"))
        if updated is not None and updated < cutoff:
            try:
                receipt_path.unlink()
                (directory / ".worker.lock").unlink(missing_ok=True)
                directory.rmdir()
            except OSError:
                pass


def transaction_directory(app_root: Path, transaction_id: str) -> Path:
    if not PLAN_ID_RE.fullmatch(transaction_id):
        raise RefreshError("invalid_transaction_id", "The transaction identifier is invalid.")
    path = app_root / "transactions" / transaction_id
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def safe_session_summary(session: dict[str, object]) -> dict[str, object]:
    handle = session.get("terminal_handle")
    return {
        "host": session.get("host"),
        "terminal": f"…{handle[-6:]}" if isinstance(handle, str) else None,
        "worktree": session.get("worktree_path"),
        "state": session.get("state"),
        "plugin_version": session.get("plugin_version"),
    }


def session_record_for_terminal(
    terminal: dict[str, object], records: dict[str, dict[str, object]]
) -> tuple[str | None, dict[str, object] | None, str | None]:
    host = terminal.get("host")
    handle = terminal.get("terminal_handle")
    worktree_id = terminal.get("worktree_id")
    if not isinstance(host, str) or not isinstance(handle, str) or not isinstance(worktree_id, str):
        return None, None, "terminal identity is incomplete"

    exact = [
        (key, value)
        for key, value in records.items()
        if value.get("host") == host
        and value.get("state") != "ended"
        and value.get("terminal_handle") == handle
        and value.get("worktree_id") == worktree_id
    ]
    if len(exact) == 1:
        recorded_incarnation = exact[0][1].get("incarnation_id")
        if isinstance(recorded_incarnation, str) and recorded_incarnation != terminal.get("incarnation_id"):
            return None, None, "terminal process incarnation changed without a lifecycle registration"
        return exact[0][0], exact[0][1], None
    if len(exact) > 1:
        return None, None, "multiple registry records match the terminal handle"
    return None, None, "terminal has no current lifecycle registry handle"


def _manifest_snapshots() -> dict[str, dict[str, object]]:
    snapshots: dict[str, dict[str, object]] = {}
    for host in ("codex", "claude"):
        _, snapshot = installed_plugins(host)
        root = Path(str(snapshot["root"]))
        snapshots[host] = {
            **snapshot,
            "catalog_revision": git_revision(root),
        }
    return snapshots


def _plan_hash(plan: dict[str, object]) -> str:
    stable = {key: value for key, value in plan.items() if key != "plan_hash"}
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_plan(app_root: Path) -> dict[str, object]:
    prune_old_local_state(app_root)
    terminals = terminal_inventory()
    records = registry_sessions(app_root)
    initiator_handle = str(_current_initiator(terminals)["terminal_handle"])
    versions = _manifest_snapshots()
    blockers: list[dict[str, str]] = []

    catalog_versions = {host: value["catalog_version"] for host, value in versions.items()}
    if catalog_versions["codex"] != catalog_versions["claude"]:
        blockers.append({"code": "catalog_version_mismatch", "message": "The configured marketplaces show different plugin versions."})
    for host, value in versions.items():
        installed = str(value["installed_version"])
        catalog = str(value["catalog_version"])
        if value.get("catalog_revision") is None:
            blockers.append({"code": "catalog_revision_missing", "message": f"The {host} marketplace revision cannot be verified."})
        if version_core(catalog) < version_core(installed):
            blockers.append({"code": "downgrade_refused", "message": f"The {host} marketplace version is older than its installed plugin."})

    snapshots: list[dict[str, object]] = []
    seen_sessions: set[str] = set()
    initiator_found = False
    for terminal in sorted(terminals, key=lambda value: (str(value["worktree_id"]), str(value["host"]), str(value["terminal_handle"]))):
        key, record, problem = session_record_for_terminal(terminal, records)
        if problem or record is None or key is None:
            blockers.append(
                {
                    "code": "session_unregistered",
                    "message": f"A {terminal['host']} terminal in {terminal['worktree_path']} is not safely registered ({problem}).",
                }
            )
            snapshots.append({**terminal, "session_id": None, "registry_state": None, "registered": False})
            continue
        session_id = record.get("session_id")
        if not isinstance(session_id, str):
            blockers.append({"code": "session_id_missing", "message": f"A {terminal['host']} terminal has no native session ID."})
            continue
        identity = session_key(str(terminal["host"]), session_id)
        if identity in seen_sessions:
            blockers.append({"code": "duplicate_session", "message": "One native session is attached to more than one live terminal."})
            continue
        seen_sessions.add(identity)
        initiator = terminal["terminal_handle"] == initiator_handle
        initiator_found = initiator_found or initiator
        state = record.get("state")
        if state not in {"idle", "busy"}:
            blockers.append({"code": "session_not_resumable", "message": f"A {terminal['host']} session is not in a resumable state."})
        if not isinstance(record.get("event_sequence"), int):
            blockers.append({"code": "session_event_sequence_missing", "message": f"A {terminal['host']} session needs a new lifecycle event before refresh."})
        cwd = record.get("cwd")
        worktree_path = Path(str(terminal["worktree_path"])).resolve()
        if not isinstance(cwd, str) or not Path(cwd).is_absolute() or not Path(cwd).resolve().is_relative_to(worktree_path):
            blockers.append({"code": "cwd_outside_worktree", "message": f"A {terminal['host']} session is outside its recorded worktree."})
        existing_lease = record.get("refresh_transaction_id")
        if isinstance(existing_lease, str) and transaction_may_be_active(app_root, existing_lease):
            blockers.append({"code": "transaction_active", "message": "Another plugin refresh already owns a target session."})
        if terminal.get("orphaned") or not terminal.get("connected") or not terminal.get("writable"):
            blockers.append({"code": "terminal_unavailable", "message": f"A {terminal['host']} terminal is not writable and connected."})
        tui_idle = False
        try:
            tui_idle = wait_terminal(str(terminal["terminal_handle"]), "tui-idle", 300)
        except RefreshError:
            tui_idle = False
        if not initiator and (state != "idle" or not tui_idle):
            blockers.append({"code": "session_busy", "message": f"A non-initiator {terminal['host']} session is busy."})
        plugin_version = record.get("plugin_version")
        if not isinstance(plugin_version, str):
            blockers.append({"code": "session_version_missing", "message": f"A {terminal['host']} session has no recorded plugin version."})
            plugin_version = None
        snapshot = {
            **terminal,
            "session_id": session_id,
            "registry_key": key,
            "registry_state": state,
            "registry_updated_at": record.get("updated_at"),
            "registry_event_sequence": record.get("event_sequence"),
            "plugin_version": plugin_version,
            "tui_idle_at_plan": tui_idle,
            "initiator": initiator,
            "registered": True,
            "tab_id": record.get("tab_id") or terminal.get("tab_id"),
            "leaf_id": record.get("leaf_id") or terminal.get("leaf_id"),
            "cwd": record.get("cwd"),
        }
        snapshots.append(snapshot)
    if not initiator_found:
        blockers.append({"code": "initiator_not_targeted", "message": "The current Orca terminal is not a registered Claude Code or Codex session."})

    installed_versions = {host: value["installed_version"] for host, value in versions.items()}
    target_versions = {host: value["catalog_version"] for host, value in versions.items()}
    needs_plugin_update = any(installed_versions[host] != target_versions[host] for host in versions)
    needs_session_restart = any(
        not isinstance(session.get("plugin_version"), str)
        or base_version(session.get("plugin_version")) != target_versions[str(session["host"])]
        for session in snapshots
        if session.get("registered") is True
    )

    plan_id = uuid.uuid4().hex
    created_at = now_utc()
    plan: dict[str, object] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "plan_id": plan_id,
        "created_at": created_at,
        "expires_at": (utc_now() + PLAN_TTL).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "initiator_handle": initiator_handle,
        "versions": versions,
        "installed_versions": installed_versions,
        "target_versions": target_versions,
        "needs_plugin_update": needs_plugin_update,
        "needs_session_restart": needs_session_restart,
        "sessions": snapshots,
        "blockers": blockers,
        "eligible": not blockers,
        "consumed_by": None,
    }
    plan["plan_hash"] = _plan_hash(plan)
    write_json(plan_directory(app_root) / f"{plan_id}.json", plan)
    return plan


def plan_output(plan: dict[str, object]) -> dict[str, object]:
    sessions = plan.get("sessions") if isinstance(plan.get("sessions"), list) else []
    return {
        "ok": plan.get("eligible") is True,
        "plan_id": plan.get("plan_id"),
        "expires_at": plan.get("expires_at"),
        "target_versions": plan.get("target_versions"),
        "installed_versions": plan.get("installed_versions"),
        "needs_plugin_update": plan.get("needs_plugin_update"),
        "needs_session_restart": plan.get("needs_session_restart"),
        "sessions": [safe_session_summary(value) for value in sessions if isinstance(value, dict)],
        "blockers": plan.get("blockers"),
        "approval": "Apply only after the user explicitly approves this plan ID.",
    }


def load_plan(app_root: Path, plan_id: str) -> dict[str, object]:
    if not PLAN_ID_RE.fullmatch(plan_id):
        raise RefreshError("invalid_plan_id", "The plan identifier is invalid.")
    path = plan_directory(app_root) / f"{plan_id}.json"
    try:
        plan = read_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise RefreshError("plan_missing", "The requested plan is unavailable; create a new plan.") from error
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION or plan.get("plan_id") != plan_id:
        raise RefreshError("plan_invalid", "The saved plan has an unsupported schema.")
    if plan.get("plan_hash") != _plan_hash(plan):
        raise RefreshError("plan_changed", "The saved plan was modified; create a new plan.")
    expiry = parse_time(plan.get("expires_at"))
    if expiry is None or utc_now() > expiry:
        raise RefreshError("plan_expired", "The plan expired; create and review a new plan.")
    if plan.get("eligible") is not True:
        raise RefreshError("plan_blocked", "The plan has unresolved preflight blockers.")
    return plan


def plan_path(app_root: Path, plan_id: str) -> Path:
    if not PLAN_ID_RE.fullmatch(plan_id):
        raise RefreshError("invalid_plan_id", "The plan identifier is invalid.")
    return plan_directory(app_root) / f"{plan_id}.json"


def _session_identity(session: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(session.get("host")),
        str(session.get("session_id")),
        str(session.get("worktree_id")),
    )


def _records_by_identity(records: dict[str, dict[str, object]]) -> dict[tuple[str, str, str], dict[str, object]]:
    result: dict[tuple[str, str, str], dict[str, object]] = {}
    for record in records.values():
        if all(isinstance(record.get(field), str) for field in ("host", "session_id", "worktree_id")):
            identity = _session_identity(record)
            if identity in result:
                raise RefreshError("duplicate_session", "A native session is registered more than once.")
            result[identity] = record
    return result


def _current_initiator(terminals: list[dict[str, object]]) -> dict[str, object]:
    handle = os.environ.get("ORCA_TERMINAL_HANDLE")
    exact = [item for item in terminals if isinstance(handle, str) and item.get("terminal_handle") == handle]
    if len(exact) == 1:
        return exact[0]
    tab_id = os.environ.get("ORCA_TAB_ID")
    pane_key = os.environ.get("ORCA_PANE_KEY")
    pane_tab_id, leaf_id = pane_key.rsplit(":", 1) if isinstance(pane_key, str) and ":" in pane_key else (None, None)
    if pane_tab_id != tab_id:
        leaf_id = None
    matches = [
        item for item in terminals
        if isinstance(tab_id, str)
        and item.get("tab_id") == tab_id
        and isinstance(leaf_id, str)
        and item.get("leaf_id") == leaf_id
    ]
    if len(matches) == 1:
        return matches[0]
    raise RefreshError("initiator_not_found", "The current Orca terminal cannot be matched to one agent session.")


def _current_versions_match_plan(plan: dict[str, object], *, compare_revision: bool) -> dict[str, dict[str, object]]:
    current = _manifest_snapshots()
    planned = plan.get("versions")
    if not isinstance(planned, dict):
        raise RefreshError("plan_invalid", "The saved plan has no marketplace version snapshot.")
    for host in ("codex", "claude"):
        old = planned.get(host)
        new = current.get(host)
        if not isinstance(old, dict) or not isinstance(new, dict):
            raise RefreshError("plan_invalid", "The saved plan has an incomplete marketplace snapshot.")
        if old.get("catalog_version") != new.get("catalog_version"):
            raise RefreshError("stale_plan", "A marketplace plugin version changed after the plan. Review a new plan.")
        if old.get("installed_version") != new.get("installed_version"):
            raise RefreshError("stale_plan", "An installed plugin version changed after the plan. Review a new plan.")
        if old.get("root") != new.get("root"):
            raise RefreshError("stale_plan", "A marketplace source changed after the plan. Review a new plan.")
        if compare_revision and old.get("catalog_revision") != new.get("catalog_revision"):
            raise RefreshError("stale_plan", "A marketplace source revision changed after the plan. Review a new plan.")
    return current


def _current_sessions_match_plan(
    app_root: Path,
    plan: dict[str, object],
    *,
    initiator_may_be_busy: bool,
    transaction_id: str | None = None,
) -> list[dict[str, object]]:
    terminals = terminal_inventory()
    records = registry_sessions(app_root)
    records_by_id = _records_by_identity(records)
    initiator = _current_initiator(terminals)
    initiator_handle = initiator.get("terminal_handle")
    planned_sessions = plan.get("sessions")
    if not isinstance(planned_sessions, list):
        raise RefreshError("plan_invalid", "The saved plan has no session snapshot.")
    planned_by_id = {
        _session_identity(value): value
        for value in planned_sessions
        if isinstance(value, dict) and value.get("registered") is True
    }
    current: list[dict[str, object]] = []
    found: set[tuple[str, str, str]] = set()
    for terminal in terminals:
        key, record, problem = session_record_for_terminal(terminal, records)
        if problem or record is None or key is None:
            raise RefreshError("session_unregistered", "A live Claude Code or Codex terminal has no matching session record.")
        identity = _session_identity(record)
        if identity not in planned_by_id:
            raise RefreshError("stale_plan", "The set of live agent sessions changed after the plan. Review a new plan.")
        planned = planned_by_id[identity]
        found.add(identity)
        is_initiator = terminal.get("terminal_handle") == initiator_handle
        if is_initiator != (planned.get("initiator") is True):
            raise RefreshError("stale_plan", "The initiating terminal changed after the plan.")
        if terminal.get("worktree_id") != planned.get("worktree_id"):
            raise RefreshError("stale_plan", "A session worktree changed after the plan.")
        if terminal.get("incarnation_id") != planned.get("incarnation_id"):
            raise RefreshError("stale_plan", "A terminal process changed after the plan. Review a new plan.")
        cwd = record.get("cwd")
        worktree_path = Path(str(terminal["worktree_path"])).resolve()
        if not isinstance(cwd, str) or not Path(cwd).is_absolute() or not Path(cwd).resolve().is_relative_to(worktree_path):
            raise RefreshError("cwd_outside_worktree", "A target session is outside its recorded worktree.")
        if terminal.get("orphaned") or not terminal.get("connected") or not terminal.get("writable"):
            raise RefreshError("terminal_unavailable", "A target Orca terminal is not writable and connected.")
        existing_lease = record.get("refresh_transaction_id")
        if isinstance(existing_lease, str) and existing_lease != transaction_id:
            if transaction_may_be_active(app_root, existing_lease):
                raise RefreshError("transaction_active", "Another plugin refresh already owns a target session.")
        state = record.get("state")
        if is_initiator and initiator_may_be_busy:
            if state not in {"busy", "idle"}:
                raise RefreshError("initiator_not_ready", "The initiating session has an invalid lifecycle state.")
            if state == "busy" and record.get("last_event") != "UserPromptSubmit":
                raise RefreshError("hook_not_active", "The initiating prompt hook did not record this apply request.")
        else:
            if state != "idle":
                raise RefreshError("session_busy", "A target session is not idle. No session was stopped.")
            if not is_initiator and record.get("event_sequence") != planned.get("registry_event_sequence"):
                raise RefreshError("stale_plan", "A target session changed after the plan. Review a new plan.")
        if not is_initiator and not wait_terminal(str(terminal["terminal_handle"]), "tui-idle", 1000):
            raise RefreshError("session_busy", "A target terminal is not idle. No session was stopped.")
        if is_initiator and not initiator_may_be_busy and state != "idle":
            raise RefreshError("session_busy", "The initiating terminal is not idle.")
        record_copy = dict(record)
        record_copy.update(terminal)
        record_copy["registry_key"] = key
        record_copy["initiator"] = is_initiator
        record_copy["session_id"] = record.get("session_id")
        record_copy["cwd"] = record.get("cwd")
        record_copy["tab_id"] = record.get("tab_id") or terminal.get("tab_id")
        record_copy["leaf_id"] = record.get("leaf_id") or terminal.get("leaf_id")
        current.append(record_copy)
    if found != set(planned_by_id):
        raise RefreshError("stale_plan", "A planned session is no longer live. Review a new plan.")
    if not any(item.get("initiator") for item in current):
        raise RefreshError("initiator_not_targeted", "The initiating session is not part of this plan.")
    return current


def _make_receipt(plan: dict[str, object], transaction_id: str) -> dict[str, object]:
    sessions = plan.get("sessions") if isinstance(plan.get("sessions"), list) else []
    return {
        "schema_version": TRANSACTION_SCHEMA_VERSION,
        "transaction_id": transaction_id,
        "plan_id": plan.get("plan_id"),
        "state": "queued",
        "stage": "queued",
        "created_at": now_utc(),
        "updated_at": now_utc(),
        "initiator_handle": plan.get("initiator_handle"),
        "target_versions": plan.get("target_versions"),
        "sessions": [
            {
                key: value.get(key)
                for key in (
                    "host", "session_id", "terminal_handle", "worktree_id", "worktree_path", "cwd",
                    "tab_id", "leaf_id", "incarnation_id", "plugin_version", "initiator",
                )
            }
            for value in sessions if isinstance(value, dict) and value.get("registered") is True
        ],
        "events": [],
        "errors": [],
    }


def _append_event(receipt: dict[str, object], name: str, *, detail: str | None = None) -> None:
    events = receipt.get("events")
    if not isinstance(events, list):
        events = []
        receipt["events"] = events
    entry: dict[str, object] = {"at": now_utc(), "event": name}
    if detail:
        entry["detail"] = detail
    events.append(entry)
    receipt["updated_at"] = now_utc()


def _save_receipt(app_root: Path, receipt: dict[str, object]) -> None:
    transaction_id = receipt.get("transaction_id")
    if not isinstance(transaction_id, str) or not PLAN_ID_RE.fullmatch(transaction_id):
        raise RefreshError("receipt_invalid", "The transaction receipt identifier is invalid.")
    write_json(transaction_path(app_root, transaction_id), receipt)


def _set_leases(app_root: Path, sessions: list[dict[str, object]], transaction_id: str) -> None:
    with registry_lock(app_root) as registry:
        records = registry.get("sessions")
        if not isinstance(records, dict):
            raise RefreshError("registry_invalid", "The Orca session registry is invalid.")
        for session in sessions:
            key = session.get("registry_key")
            if not isinstance(key, str) or not isinstance(records.get(key), dict):
                raise RefreshError("session_unregistered", "A target session disappeared before the transaction started.")
            record = records[key]
            existing_lease = record.get("refresh_transaction_id")
            if isinstance(existing_lease, str) and existing_lease != transaction_id:
                if transaction_may_be_active(app_root, existing_lease):
                    raise RefreshError("transaction_active", "Another plugin refresh already owns a target session.")
                record.pop("refresh_transaction_id", None)
            record["refresh_transaction_id"] = transaction_id
            record["lease_updated_at"] = now_utc()
            record["incarnation_id"] = session.get("incarnation_id")


def _clear_leases(app_root: Path, transaction_id: str, *, recovered: bool = False) -> None:
    try:
        with registry_lock(app_root) as registry:
            records = registry.get("sessions")
            if not isinstance(records, dict):
                return
            for record in records.values():
                if isinstance(record, dict) and record.get("refresh_transaction_id") == transaction_id:
                    record.pop("refresh_transaction_id", None)
                    record.pop("lease_updated_at", None)
                    if recovered and record.get("state") == "ended":
                        record["state"] = "ended"
    except (OSError, ValueError, TimeoutError, json.JSONDecodeError):
        return


def _pending_command_receipt(app_root: Path, command_hash: str) -> dict[str, object]:
    matches: list[dict[str, object]] = []
    root = app_root / "transactions"
    if root.is_dir():
        for directory in root.iterdir():
            if directory.is_symlink() or not directory.is_dir() or not PLAN_ID_RE.fullmatch(directory.name):
                continue
            try:
                receipt = read_json_object(directory / "receipt.json")
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            action = receipt.get("manual_action")
            if (
                receipt.get("state") == "needs_manual_command"
                and isinstance(action, dict)
                and action.get("plugin") == PLUGIN_NAME
                and action.get("marketplace") == MARKETPLACE_NAME
                and action.get("command_sha256") == command_hash
            ):
                matches.append(receipt)
    if len(matches) != 1:
        raise RefreshError("command_approval_missing", "No unique pending Claude Code command matches this hash.")
    return matches[0]


def apply_plan(app_root: Path, plan_id: str, *, accept_command: str | None = None) -> dict[str, object]:
    dispatch_lock = app_root / ".dispatch.lock"
    with file_lock(dispatch_lock, timeout=0.1):
        plan = load_plan(app_root, plan_id)
        parent_transaction_id = plan.get("consumed_by")
        if parent_transaction_id:
            if not isinstance(parent_transaction_id, str):
                raise RefreshError("plan_consumed", "This plan already started a transaction. Create a fresh plan.")
            parent_receipt = _load_receipt(app_root, parent_transaction_id)
            manual = parent_receipt.get("manual_action")
            if (
                parent_receipt.get("state") != "needs_manual_command"
                or not isinstance(manual, dict)
                or not isinstance(accept_command, str)
                or manual.get("command_sha256") != accept_command
                or manual.get("plugin") != PLUGIN_NAME
                or manual.get("marketplace") != MARKETPLACE_NAME
                or parent_receipt.get("target_versions") != plan.get("target_versions")
            ):
                raise RefreshError("plan_consumed", "This plan can continue only with the exact command hash shown in its receipt.")
        elif accept_command is not None:
            parent_receipt = _pending_command_receipt(app_root, accept_command)
            parent_transaction_id = parent_receipt.get("transaction_id")
            if parent_receipt.get("target_versions") != plan.get("target_versions"):
                raise RefreshError("command_approval_stale", "The pending command belongs to a different plugin version. Review a new plan.")
        if accept_command is not None and not re.fullmatch(r"[0-9a-f]{64}", accept_command):
            raise RefreshError("command_hash_invalid", "The marketplace command hash is invalid.")
        _current_versions_match_plan(plan, compare_revision=True)
        sessions = _current_sessions_match_plan(app_root, plan, initiator_may_be_busy=True)
        if not plan.get("needs_plugin_update") and not plan.get("needs_session_restart"):
            return {"ok": True, "state": "already_current", "plan_id": plan_id, "message": "Both plugins and all sessions already match the marketplace version."}
        transaction_id = uuid.uuid4().hex
        transaction_dir = transaction_directory(app_root, transaction_id)
        receipt = _make_receipt(plan, transaction_id)
        receipt["state"] = "queued"
        receipt["stage"] = "queued"
        if accept_command is not None:
            receipt["claude_command_hash"] = accept_command
            receipt["parent_transaction_id"] = parent_transaction_id
        _append_event(receipt, "apply-approved")
        _save_receipt(app_root, receipt)
        _set_leases(app_root, sessions, transaction_id)
        plan["consumed_by"] = transaction_id
        plan["plan_hash"] = _plan_hash(plan)
        write_json(plan_path(app_root, plan_id), plan)
        argv = [sys.executable, str(Path(__file__).resolve()), "worker", "--transaction-id", transaction_id]
        try:
            subprocess.Popen(
                argv,
                cwd=app_root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
        except OSError as error:
            receipt["state"] = "failed"
            receipt["stage"] = "worker-start"
            receipt["errors"] = [{"code": "worker_start_failed", "message": "The detached update worker could not start."}]
            _append_event(receipt, "worker-start-failed")
            _save_receipt(app_root, receipt)
            _clear_leases(app_root, transaction_id)
            raise RefreshError("worker_start_failed", "The detached update worker could not start.") from error
        return {
            "ok": True,
            "state": "queued",
            "transaction_id": transaction_id,
            "receipt": str(transaction_path(app_root, transaction_id)),
            "sessions": [safe_session_summary(item) for item in sessions],
        }


def _load_receipt(app_root: Path, transaction_id: str) -> dict[str, object]:
    try:
        receipt = read_json_object(transaction_path(app_root, transaction_id))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise RefreshError("receipt_missing", "The transaction receipt is unavailable.") from error
    if receipt.get("schema_version") != TRANSACTION_SCHEMA_VERSION or receipt.get("transaction_id") != transaction_id:
        raise RefreshError("receipt_invalid", "The transaction receipt has an unsupported schema.")
    return receipt


def _set_stage(app_root: Path, receipt: dict[str, object], stage: str, *, state: str = "running") -> None:
    receipt["stage"] = stage
    receipt["state"] = state
    _append_event(receipt, stage)
    _save_receipt(app_root, receipt)


def _add_error(receipt: dict[str, object], code: str, message: str) -> None:
    errors = receipt.get("errors")
    if not isinstance(errors, list):
        errors = []
        receipt["errors"] = errors
    errors.append({"code": code, "message": message})


def _read_current_records(app_root: Path) -> dict[str, dict[str, object]]:
    return registry_sessions(app_root)


def _current_record_for(session: dict[str, object], records: dict[str, dict[str, object]]) -> tuple[str, dict[str, object]]:
    identity = _session_identity(session)
    matches = [(key, value) for key, value in _records_by_identity(records).items() if key == identity]
    if len(matches) != 1:
        raise RefreshError("session_disappeared", "A target session disappeared from the registry.")
    return matches[0]


def _refresh_sources(app_root: Path, receipt: dict[str, object]) -> None:
    _set_stage(app_root, receipt, "refreshing-marketplaces")
    run_command([executable("codex"), "plugin", "marketplace", "upgrade", MARKETPLACE_NAME], timeout=180)
    _append_event(receipt, "codex-marketplace-updated")
    _save_receipt(app_root, receipt)
    run_command([executable("claude"), "plugin", "marketplace", "update", MARKETPLACE_NAME], timeout=180)
    _append_event(receipt, "claude-marketplace-updated")
    _save_receipt(app_root, receipt)


def _check_catalog_after_refresh(plan: dict[str, object]) -> dict[str, dict[str, object]]:
    current = _manifest_snapshots()
    previous = plan.get("versions")
    if not isinstance(previous, dict):
        raise RefreshError("plan_invalid", "The plan marketplace snapshot is invalid.")
    for host in ("codex", "claude"):
        before = previous.get(host)
        after = current.get(host)
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise RefreshError("plan_invalid", "The plan marketplace snapshot is incomplete.")
        if before.get("root") != after.get("root"):
            raise RefreshError("stale_plan", "A marketplace root changed while refreshing sources.")
        if before.get("catalog_version") != after.get("catalog_version"):
            raise RefreshError("stale_plan", "A marketplace published a different plugin version after the plan. Create and review a new plan.")
        if before.get("catalog_revision") is None or before.get("catalog_revision") != after.get("catalog_revision"):
            raise RefreshError("stale_plan", "A marketplace revision changed after the plan. Create and review a new plan.")
    return current


def _verify_installed_versions(target_versions: dict[str, object]) -> dict[str, str]:
    actual: dict[str, str] = {}
    for host in ("codex", "claude"):
        item, _ = installed_plugins(host)
        raw = item.get("version")
        actual[host] = base_version(raw)
        if actual[host] != target_versions.get(host):
            raise RefreshError("installed_version_mismatch", f"The {host} plugin did not reach its planned version.")
    return actual


def _installed_versions() -> dict[str, str]:
    values: dict[str, str] = {}
    for host in ("codex", "claude"):
        item, _ = installed_plugins(host)
        values[host] = base_version(item.get("version"))
    return values


def _claude_update(app_root: Path, receipt: dict[str, object], target: str) -> None:
    command = [executable("claude"), "plugin", "update"]
    accepted_hash = receipt.get("claude_command_hash")
    if isinstance(accepted_hash, str):
        if not re.fullmatch(r"[0-9a-f]{64}", accepted_hash):
            raise RefreshError("command_hash_invalid", "The marketplace command hash is invalid.")
        command.extend(["--accept-command", accepted_hash])
    command.extend([f"{PLUGIN_NAME}@{MARKETPLACE_NAME}", "--json"])
    result = run_command(
        command,
        timeout=180,
        check=False,
    )
    if result.returncode == 0:
        return
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        payload = None
    shown = payload.get("shownCommand") if isinstance(payload, dict) else None
    digest = shown.get("sha256") if isinstance(shown, dict) else None
    if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
        receipt["manual_action"] = {
            "kind": "claude_marketplace_command_approval",
            "marketplace": MARKETPLACE_NAME,
            "plugin": PLUGIN_NAME,
            "command_sha256": digest,
            "target_version": target,
        }
        receipt["state"] = "needs_manual_command"
        receipt["stage"] = "claude-command-approval"
        _append_event(receipt, "manual-command-approval-required")
        _save_receipt(app_root, receipt)
        _clear_leases(app_root, str(receipt["transaction_id"]))
        return
    raise RefreshError("claude_update_failed", f"Claude Code plugin update failed with exit code {result.returncode}.")


def _update_plugins(app_root: Path, receipt: dict[str, object], target_versions: dict[str, object]) -> bool:
    _set_stage(app_root, receipt, "updating-claude-plugin")
    current = _installed_versions()
    if current["claude"] != target_versions["claude"]:
        _claude_update(app_root, receipt, str(target_versions["claude"]))
        if receipt.get("state") == "needs_manual_command":
            return False

    receipt["installed_versions"] = _installed_versions()
    _save_receipt(app_root, receipt)
    _set_stage(app_root, receipt, "updating-codex-plugin")
    current = _installed_versions()
    if current["codex"] != target_versions["codex"]:
        run_command(
            [executable("codex"), "plugin", "add", f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"],
            timeout=180,
        )
    receipt["installed_versions"] = _installed_versions()
    _save_receipt(app_root, receipt)
    actual = _verify_installed_versions(target_versions)
    receipt["installed_versions"] = actual
    _set_stage(app_root, receipt, "plugins-updated")
    return True


def _reconcile_terminal(session: dict[str, object], terminals: list[dict[str, object]]) -> dict[str, object]:
    host = session.get("host")
    worktree_id = session.get("worktree_id")
    current_handle = session.get("terminal_handle")
    exact = [
        terminal for terminal in terminals
        if terminal.get("host") == host
        and terminal.get("worktree_id") == worktree_id
        and terminal.get("terminal_handle") == current_handle
    ]
    if len(exact) == 1:
        if exact[0].get("incarnation_id") != session.get("incarnation_id"):
            raise RefreshError("terminal_changed", "The target terminal process changed after the plan.")
        return exact[0]
    raise RefreshError("terminal_missing", "The planned Orca terminal is no longer live; create and approve a new plan.")


def _wait_session_idle(
    app_root: Path,
    session: dict[str, object],
    *,
    timeout_seconds: int,
    receipt: dict[str, object],
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        terminals = terminal_inventory()
        terminal = _reconcile_terminal(session, terminals)
        if terminal.get("orphaned") or not terminal.get("connected") or not terminal.get("writable"):
            raise RefreshError("terminal_unavailable", "A target Orca terminal became unavailable.")
        records = _read_current_records(app_root)
        _, record = _current_record_for(session, records)
        if record.get("refresh_transaction_id") != receipt.get("transaction_id"):
            raise RefreshError("lease_lost", "The update transaction lost its session lease.")
        if record.get("terminal_handle") != terminal.get("terminal_handle") or record.get("incarnation_id") != terminal.get("incarnation_id"):
            raise RefreshError("terminal_identity_unverified", "The replacement terminal has not registered the planned native session ID.")
        if record.get("state") == "ended":
            raise RefreshError("session_ended", "The planned native session ended before refresh.")
        expected_sequence = session.get("expected_event_sequence")
        if expected_sequence is None and not session.get("initiator"):
            expected_sequence = session.get("registry_event_sequence")
        if expected_sequence is not None and record.get("event_sequence") != expected_sequence:
            raise RefreshError("stale_plan", "A planned native session changed after the preview.")
        is_idle = record.get("state") == "idle"
        wait_ms = min(1000, max(1, int((deadline - time.monotonic()) * 1000)))
        tui_idle = wait_terminal(str(terminal["terminal_handle"]), "tui-idle", wait_ms)
        if is_idle and tui_idle:
            session["terminal_handle"] = terminal["terminal_handle"]
            session["tab_id"] = terminal.get("tab_id")
            session["leaf_id"] = terminal.get("leaf_id")
            session["incarnation_id"] = terminal.get("incarnation_id")
            return terminal
        if time.monotonic() >= deadline:
            raise RefreshError("session_not_idle", "A target agent did not reach a safe idle point before the timeout.")


def _send_exit(handle: str) -> None:
    payload = run_json(
        [*orca_command(), "terminal", "send", "--terminal", handle, "--text", "/exit", "--enter", "--json"],
        timeout=20,
    )
    orca_send_receipt(payload)
    if not wait_terminal(handle, "exit", 60_000):
        if not wait_terminal(handle, "exit", 120_000):
            raise RefreshError("exit_unconfirmed", "The agent process did not exit; the terminal was left open.")


def _close_exited_terminal(handle: str) -> None:
    result = run_command([*orca_command(), "terminal", "close", "--terminal", handle, "--json"], timeout=20, check=False)
    if result.returncode == 0:
        try:
            parse_json_output(result, "orca")
            return
        except RefreshError:
            pass
    terminals = terminal_inventory()
    if any(item.get("terminal_handle") == handle for item in terminals):
        raise RefreshError("terminal_close_failed", "The exited Orca terminal tab could not be closed safely.")


def _created_handle(payload: object) -> str | None:
    result = unwrap_orca(payload)
    for key in ("startupTerminal", "terminal", "createdTerminal"):
        value = result.get(key)
        if isinstance(value, dict) and isinstance(value.get("handle"), str):
            return value["handle"]
    if isinstance(result.get("handle"), str):
        return str(result["handle"])
    return None


def _resume_command(session: dict[str, object]) -> list[str]:
    cwd = session.get("cwd")
    session_id = session.get("session_id")
    host = session.get("host")
    if not isinstance(cwd, str) or not Path(cwd).is_absolute() or not isinstance(session_id, str):
        raise RefreshError("resume_context_missing", "A target session is missing its original cwd or session ID.")
    if host == "codex":
        return [executable("codex"), "-C", cwd, "resume", session_id]
    if host == "claude":
        return [executable("claude"), "--resume", session_id]
    raise RefreshError("host_unsupported", "A target session uses an unsupported agent host.")


def _manual_resume_shell_command(session: dict[str, object]) -> str:
    cwd = str(session["cwd"])
    return "cd -- " + shlex.quote(cwd) + " && exec " + shlex.join(_resume_command(session))


def _update_receipt_session(receipt: dict[str, object], session: dict[str, object]) -> None:
    entries = receipt.get("sessions")
    if not isinstance(entries, list):
        return
    for item in entries:
        if not isinstance(item, dict):
            continue
        if item.get("host") == session.get("host") and item.get("session_id") == session.get("session_id"):
            for field in (
                "previous_terminal_handle",
                "previous_terminal_closed",
                "resume_launch_attempted",
                "new_terminal_handle",
                "new_incarnation_id",
                "new_plugin_version",
                "resume_verified",
                "manual_resume_command",
                "manual_resume_requires_terminal_check",
                "last_error",
            ):
                if field in session:
                    item[field] = session[field]
            return


def _create_resumed_terminal(session: dict[str, object], transaction_id: str) -> dict[str, object]:
    cwd = str(session["cwd"])
    host = str(session["host"])
    session_id = str(session["session_id"])
    worktree_id = str(session["worktree_id"])
    title = f"refresh-{transaction_id[:8]}-{host}-{session_id[-6:]}"
    shell_command = "cd -- " + shlex.quote(cwd) + " && exec " + shlex.join(_resume_command(session))
    payload = run_json(
        [
            *orca_command(),
            "terminal",
            "create",
            "--worktree",
            f"id:{worktree_id}",
            "--title",
            title,
            "--command",
            shell_command,
            "--json",
        ],
        timeout=30,
    )
    handle = _created_handle(payload)
    terminals = terminal_inventory()
    if handle:
        matches = [terminal for terminal in terminals if terminal.get("terminal_handle") == handle]
    else:
        matches = [
            terminal for terminal in terminals
            if terminal.get("host") == host
            and terminal.get("worktree_id") == worktree_id
            and terminal.get("title") == title
        ]
    if len(matches) != 1:
        raise RefreshError("new_terminal_ambiguous", "The new Orca terminal could not be identified uniquely.")
    terminal = matches[0]
    if terminal.get("host") != host or terminal.get("worktree_id") != worktree_id:
        raise RefreshError("new_terminal_mismatch", "The new Orca terminal opened in a different host or worktree.")
    return terminal


def _wait_registry_resume(
    app_root: Path,
    session: dict[str, object],
    terminal: dict[str, object],
    target_version: str,
    transaction_id: str,
    timeout_seconds: int = 30,
) -> None:
    handle = str(terminal["terminal_handle"])
    if not wait_terminal(handle, "tui-idle", 60_000) and not wait_terminal(handle, "tui-idle", 120_000):
        raise RefreshError("resume_not_idle", "The resumed agent did not reach an idle state.")
    deadline = time.monotonic() + timeout_seconds
    identity = session_key(str(session["host"]), str(session["session_id"]))
    while time.monotonic() < deadline:
        records = _read_current_records(app_root)
        record = records.get(identity)
        if isinstance(record, dict):
            if (
                record.get("terminal_handle") == handle
                and record.get("worktree_id") == session.get("worktree_id")
                and record.get("refresh_transaction_id") == transaction_id
                and record.get("state") == "idle"
            ):
                recorded_version = record.get("plugin_version")
                if isinstance(recorded_version, str) and base_version(recorded_version) == target_version:
                    with registry_lock(app_root) as registry:
                        registered_sessions = registry.get("sessions")
                        registered = registered_sessions.get(identity) if isinstance(registered_sessions, dict) else None
                        if (
                            not isinstance(registered, dict)
                            or registered.get("terminal_handle") != handle
                            or registered.get("refresh_transaction_id") != transaction_id
                        ):
                            raise RefreshError("resume_identity_changed", "The resumed session changed before its process identity was recorded.")
                        registered["incarnation_id"] = terminal.get("incarnation_id")
                    session["new_terminal_handle"] = handle
                    session["new_incarnation_id"] = terminal.get("incarnation_id")
                    session["new_plugin_version"] = recorded_version
                    return
                raise RefreshError("resume_version_mismatch", "The resumed session did not load the planned plugin version.")
        time.sleep(0.1)
    raise RefreshError("resume_hook_missing", "The resumed session did not register its plugin hook. Review and trust the plugin hooks, then recover the transaction.")


def _confirm_exit_target(
    app_root: Path, session: dict[str, object], receipt: dict[str, object], terminal: dict[str, object]
) -> None:
    current = _reconcile_terminal(session, terminal_inventory())
    handle = terminal.get("terminal_handle")
    if current.get("terminal_handle") != handle:
        raise RefreshError("terminal_changed", "The target terminal changed immediately before exit.")
    _, record = _current_record_for(session, _read_current_records(app_root))
    if (
        record.get("terminal_handle") != handle
        or record.get("incarnation_id") != terminal.get("incarnation_id")
        or record.get("state") != "idle"
        or record.get("refresh_transaction_id") != receipt.get("transaction_id")
    ):
        raise RefreshError("session_became_busy", "The planned native session is not safely idle immediately before exit.")
    expected_sequence = session.get("expected_event_sequence")
    if expected_sequence is None:
        expected_sequence = session.get("registry_event_sequence")
    if expected_sequence is not None and record.get("event_sequence") != expected_sequence:
        raise RefreshError("stale_plan", "The planned native session changed immediately before exit.")
    if not wait_terminal(str(handle), "tui-idle", 1000):
        raise RefreshError("session_became_busy", "The target terminal became busy immediately before exit.")


def _record_resume_recovery(session: dict[str, object], error_code: str) -> None:
    session["last_error"] = error_code
    if not session.get("previous_terminal_closed") or session.get("resume_verified"):
        return
    try:
        session["manual_resume_command"] = _manual_resume_shell_command(session)
        session["manual_resume_requires_terminal_check"] = bool(session.get("resume_launch_attempted") or session.get("new_terminal_handle"))
    except RefreshError:
        pass


def _notify_initiator(handle: str, transaction_id: str) -> str | None:
    message = f"Plugin refresh transaction {transaction_id} completed. Read its local receipt and report the result to the user."
    try:
        send = orca_send_receipt(run_json(
            [*orca_command(), "terminal", "send", "--terminal", handle, "--text", message, "--enter", "--wait-submit", "10", "--json"],
            timeout=25,
        ))
    except RefreshError:
        return "complete_but_not_delivered"
    prompt = send.get("prompt")
    stages = prompt.get("stages") if isinstance(prompt, dict) else None
    return None if isinstance(stages, list) and "turn_started" in stages else "complete_but_not_confirmed"


def _release_transaction(app_root: Path, receipt: dict[str, object], final_state: str) -> None:
    receipt["state"] = final_state
    receipt["stage"] = final_state
    _append_event(receipt, final_state)
    _save_receipt(app_root, receipt)
    _clear_leases(app_root, str(receipt["transaction_id"]))


def _run_worker(app_root: Path, transaction_id: str) -> int:
    directory = transaction_directory(app_root, transaction_id)
    with file_lock(directory / ".worker.lock", blocking=False):
        receipt = _load_receipt(app_root, transaction_id)
        if receipt.get("state") != "queued":
            return 0
        active_session: dict[str, object] | None = None
        try:
            plan_id = receipt.get("plan_id")
            if not isinstance(plan_id, str):
                raise RefreshError("receipt_invalid", "The queued transaction has no plan ID.")
            plan = read_json_object(plan_path(app_root, plan_id))
            receipt["worker_pid"] = os.getpid()
            _set_stage(app_root, receipt, "preflight")
            _current_versions_match_plan(plan, compare_revision=True)
            current_sessions = _current_sessions_match_plan(
                app_root,
                plan,
                initiator_may_be_busy=True,
                transaction_id=transaction_id,
            )
            _set_leases(app_root, current_sessions, transaction_id)
            initiating_session = next((item for item in current_sessions if item.get("initiator")), None)
            if initiating_session is None:
                raise RefreshError("initiator_not_targeted", "The initiating native session is missing from the transaction.")
            _set_stage(app_root, receipt, "waiting-initiator-idle")
            _wait_session_idle(app_root, initiating_session, timeout_seconds=600, receipt=receipt)
            _current_sessions_match_plan(
                app_root,
                plan,
                initiator_may_be_busy=False,
                transaction_id=transaction_id,
            )
            _, initiating_record = _current_record_for(initiating_session, _read_current_records(app_root))
            initiating_event_sequence = initiating_record.get("event_sequence")
            _set_stage(app_root, receipt, "refreshing-marketplaces")
            _refresh_sources(app_root, receipt)
            fresh_versions = _check_catalog_after_refresh(plan)
            target = plan.get("target_versions")
            if not isinstance(target, dict):
                raise RefreshError("plan_invalid", "The saved plan target versions are invalid.")
            _set_stage(app_root, receipt, "validating-marketplaces")
            _update_plugins(app_root, receipt, target)
            if receipt.get("state") == "needs_manual_command":
                return 0

            if receipt.get("state") != "running":
                receipt["state"] = "running"
            receipt["catalog_versions"] = {host: value["catalog_version"] for host, value in fresh_versions.items()}
            _set_stage(app_root, receipt, "plugins-updated")

            if not plan.get("needs_session_restart"):
                _release_transaction(app_root, receipt, "already_current")
                return 0

            planned_sessions = [value for value in plan.get("sessions", []) if isinstance(value, dict)]
            planned_sessions.sort(key=lambda value: (bool(value.get("initiator")), str(value.get("host")), str(value.get("worktree_id"))))
            for session in planned_sessions:
                active_session = session
                if session.get("initiator"):
                    session["expected_event_sequence"] = initiating_event_sequence
                _set_stage(app_root, receipt, f"waiting-idle-{session['host']}")
                terminal = _wait_session_idle(
                    app_root,
                    session,
                    timeout_seconds=600 if session.get("initiator") else 10,
                    receipt=receipt,
                )
                _set_stage(app_root, receipt, f"stopping-{session['host']}")
                _confirm_exit_target(app_root, session, receipt, terminal)
                _send_exit(str(terminal["terminal_handle"]))
                session["previous_terminal_handle"] = terminal["terminal_handle"]
                _close_exited_terminal(str(terminal["terminal_handle"]))
                session["previous_terminal_closed"] = True
                _update_receipt_session(receipt, session)
                _save_receipt(app_root, receipt)
                _set_stage(app_root, receipt, f"resuming-{session['host']}")
                session["resume_launch_attempted"] = True
                _update_receipt_session(receipt, session)
                _save_receipt(app_root, receipt)
                new_terminal = _create_resumed_terminal(session, transaction_id)
                session["new_terminal_handle"] = new_terminal["terminal_handle"]
                _update_receipt_session(receipt, session)
                _save_receipt(app_root, receipt)
                _wait_registry_resume(
                    app_root,
                    session,
                    new_terminal,
                    str(target[str(session["host"])]),
                    transaction_id,
                )
                session["resume_verified"] = True
                _update_receipt_session(receipt, session)
                _append_event(receipt, f"resumed-{session['host']}")
                _save_receipt(app_root, receipt)

            _release_transaction(app_root, receipt, "complete")
            initiator = next((item for item in planned_sessions if item.get("initiator")), None)
            if initiator and isinstance(initiator.get("new_terminal_handle"), str):
                receipt["notification"] = _notify_initiator(str(initiator["new_terminal_handle"]), transaction_id)
                if receipt["notification"] is not None:
                    _save_receipt(app_root, receipt)
            return 0
        except RefreshError as error:
            if active_session is not None:
                _record_resume_recovery(active_session, error.code)
                _update_receipt_session(receipt, active_session)
            _add_error(receipt, error.code, error.message)
            _release_transaction(app_root, receipt, "failed")
            return 1
        except Exception:
            if active_session is not None:
                _record_resume_recovery(active_session, "unexpected_failure")
                _update_receipt_session(receipt, active_session)
            _add_error(receipt, "unexpected_failure", "The worker stopped after an unexpected internal error.")
            _release_transaction(app_root, receipt, "failed")
            return 1


def _public_receipt(receipt: dict[str, object]) -> dict[str, object]:
    sessions = receipt.get("sessions")
    result_sessions: list[dict[str, object]] = []
    if isinstance(sessions, list):
        for session in sessions:
            if not isinstance(session, dict):
                continue
            result_sessions.append(
                {
                    "host": session.get("host"),
                    "terminal": f"…{str(session.get('terminal_handle'))[-6:]}" if session.get("terminal_handle") else None,
                    "new_terminal": f"…{str(session.get('new_terminal_handle'))[-6:]}" if session.get("new_terminal_handle") else None,
                    "worktree": session.get("worktree_path"),
                    "initiator": session.get("initiator"),
                    "new_plugin_version": session.get("new_plugin_version"),
                    "manual_resume_available": isinstance(session.get("manual_resume_command"), str),
                    "manual_resume_requires_terminal_check": session.get("manual_resume_requires_terminal_check") is True,
                    "last_error": session.get("last_error"),
                }
            )
    return {
        "ok": receipt.get("state") in {"complete", "already_current"},
        "transaction_id": receipt.get("transaction_id"),
        "receipt_path": str(transaction_path(require_data_root(create=False), str(receipt.get("transaction_id")))),
        "state": receipt.get("state"),
        "stage": receipt.get("stage"),
        "created_at": receipt.get("created_at"),
        "updated_at": receipt.get("updated_at"),
        "target_versions": receipt.get("target_versions"),
        "installed_versions": receipt.get("installed_versions"),
        "sessions": result_sessions,
        "errors": receipt.get("errors", []),
        "manual_action": receipt.get("manual_action"),
        "notification": receipt.get("notification"),
    }


def status_transaction(app_root: Path, transaction_id: str | None) -> dict[str, object]:
    transactions_root = app_root / "transactions"
    if transaction_id is None:
        candidates = [
            child / "receipt.json"
            for child in transactions_root.iterdir()
            if child.is_dir() and PLAN_ID_RE.fullmatch(child.name) and (child / "receipt.json").is_file()
        ] if transactions_root.is_dir() else []
        if not candidates:
            raise RefreshError("transaction_missing", "No plugin refresh transaction is recorded.")
        latest = max(candidates, key=lambda path: path.stat().st_mtime)
        transaction_id = latest.parent.name
    if not PLAN_ID_RE.fullmatch(transaction_id):
        raise RefreshError("invalid_transaction_id", "The transaction identifier is invalid.")
    return _public_receipt(_load_receipt(app_root, transaction_id))


def recover_transaction(app_root: Path, transaction_id: str, *, confirmed: bool) -> dict[str, object]:
    if not confirmed:
        raise RefreshError("confirmation_required", "Recover only after confirming the transaction worker has stopped.")
    receipt = _load_receipt(app_root, transaction_id)
    if receipt.get("state") not in ACTIVE_TRANSACTION_STATES:
        raise RefreshError("transaction_not_active", "Only a queued or interrupted transaction can be recovered.")
    updated_at = parse_time(receipt.get("updated_at"))
    if updated_at is None or utc_now() - updated_at < timedelta(seconds=60):
        raise RefreshError("worker_may_start", "Wait at least one minute after the last receipt update before recovery.")
    with file_lock(transaction_directory(app_root, transaction_id) / ".worker.lock", blocking=False):
        current_terminals = terminal_inventory()
        terminal_by_handle = {str(value["terminal_handle"]): value for value in current_terminals}
        with registry_lock(app_root) as registry:
            records = registry.get("sessions")
            if not isinstance(records, dict):
                raise RefreshError("registry_invalid", "The Orca session registry is invalid.")
            recovered: list[dict[str, object]] = []
            for key, record in records.items():
                if not isinstance(record, dict) or record.get("refresh_transaction_id") != transaction_id:
                    continue
                handle = record.get("terminal_handle")
                terminal = terminal_by_handle.get(handle) if isinstance(handle, str) else None
                identity_matches = (
                    terminal is not None
                    and terminal.get("host") == record.get("host")
                    and terminal.get("worktree_id") == record.get("worktree_id")
                    and terminal.get("tab_id") == record.get("tab_id")
                    and terminal.get("leaf_id") == record.get("leaf_id")
                    and isinstance(record.get("incarnation_id"), str)
                    and terminal.get("incarnation_id") == record.get("incarnation_id")
                )
                verification = "exact_terminal"
                if identity_matches and terminal.get("connected") and terminal.get("writable"):
                    record["state"] = "idle" if wait_terminal(str(handle), "tui-idle", 1000) else "busy"
                else:
                    possible_replacements = [
                        item for item in current_terminals
                        if item.get("host") == record.get("host") and item.get("worktree_id") == record.get("worktree_id")
                    ]
                    if possible_replacements:
                        record["state"] = "busy"
                        verification = "terminal_identity_unverified"
                    else:
                        record["state"] = "ended"
                        verification = "no_live_terminal_in_worktree"
                record.pop("refresh_transaction_id", None)
                record.pop("lease_updated_at", None)
                record["updated_at"] = now_utc()
                sequence = record.get("event_sequence")
                record["event_sequence"] = (sequence if isinstance(sequence, int) and sequence >= 0 else 0) + 1
                recovered.append({"host": record.get("host"), "state": record.get("state"), "verification": verification})
        receipt["state"] = "recovered"
        receipt["stage"] = "manual-recovery"
        receipt["recovered_sessions"] = recovered
        _append_event(receipt, "leases-recovered-without-restarting-sessions")
        _save_receipt(app_root, receipt)
    return _public_receipt(receipt)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan and run a safe Orca plugin update and session resume.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="Create a read-only update and resume preview.")
    plan_parser.add_argument("--json", action="store_true")
    apply_parser = subparsers.add_parser("apply", help="Start the approved update transaction.")
    apply_parser.add_argument("--plan-id", required=True)
    apply_parser.add_argument("--accept-command", help="Approve the exact Claude Code marketplace command hash shown in a prior receipt.")
    apply_parser.add_argument("--json", action="store_true")
    status_parser = subparsers.add_parser("status", help="Read a transaction receipt.")
    status_parser.add_argument("--transaction-id")
    status_parser.add_argument("--json", action="store_true")
    recover_parser = subparsers.add_parser("recover", help="Clear a stopped worker lease without restarting sessions.")
    recover_parser.add_argument("--transaction-id", required=True)
    recover_parser.add_argument("--confirm-worker-stopped", action="store_true")
    recover_parser.add_argument("--json", action="store_true")
    worker_parser = subparsers.add_parser("worker", help=argparse.SUPPRESS)
    worker_parser.add_argument("--transaction-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        app_root = require_data_root(create=args.command in {"plan", "apply", "recover"})
        if args.command == "plan":
            plan = create_plan(app_root)
            output = plan_output(plan)
            print_json(output)
            return 0 if output["ok"] else 2
        if args.command == "apply":
            result = apply_plan(app_root, args.plan_id, accept_command=args.accept_command)
            print_json(result)
            return 0
        if args.command == "status":
            print_json(status_transaction(app_root, args.transaction_id))
            return 0
        if args.command == "recover":
            print_json(recover_transaction(app_root, args.transaction_id, confirmed=args.confirm_worker_stopped))
            return 0
        if args.command == "worker":
            return _run_worker(app_root, args.transaction_id)
        raise RefreshError("command_unknown", "The requested refresh operation is unsupported.")
    except RefreshError as error:
        print_json({"ok": False, "error": {"code": error.code, "message": error.message}})
        return 2
    except (OSError, ValueError, TimeoutError, json.JSONDecodeError):
        print_json({"ok": False, "error": {"code": "state_unavailable", "message": "Local Orca refresh state is unavailable or invalid."}})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
