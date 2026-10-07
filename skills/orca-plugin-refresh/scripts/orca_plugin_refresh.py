#!/usr/bin/env python3
"""Safely update hei5enbug-agent-setup offline and apply installed versions to idle Orca agent sessions."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Sequence

PLUGIN = "hei5enbug-agent-setup"
MARKETPLACE = "hei5enbug"
PLUGIN_ID = f"{PLUGIN}@{MARKETPLACE}"
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
HOSTS = ("claude", "codex")
RUN_ID = re.compile(r"^[0-9a-f]{32}$")
HANDLE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
RUNTIME_PATHS = ("skills", "instructions", "scripts", "hooks", "config", "agents", "standalone-agents", ".claude-plugin", ".codex-plugin")
REQUIRED_HOOK_TARGETS = (
    "scripts/session_context.py",
    "scripts/agent_guard.py",
    "scripts/datagrip_guard.py",
    "scripts/language_guard.py",
)
RELOAD_DONE = re.compile(r"Reloaded: \d+ plugins?")
RELOAD_REFUSED = re.compile(r"reload changes MCP tools|/reload-plugins --force", re.IGNORECASE)
CLAUDE_COMPACTED = re.compile(r"Compacted|Conversation compacted")
CODEX_COMPACTED = re.compile(r"Context compacted")
CLAUDE_NOTHING_TO_COMPACT = re.compile(r"Not enough messages to compact")
CLAUDE_COMPACT_ERROR = re.compile(r"Error during compaction|Compaction canceled")
COMMANDS = {"reload": "/reload-plugins", "compact": "/compact", "clear": "/clear"}
COMMAND_RECORD_PREFIXES = ("<command-name>", "<local-command-caveat>", "<local-command-stdout>", "<local-command-stderr>")
CLEAR_TIMEOUT = 60.0
CLAUDE_PLACEHOLDER = re.compile(r'^Try ".*"$')
CODEX_PLACEHOLDERS = {"Ask Codex to do anything", "Ask a follow-up question"}
CODEX_STARTING = "Waiting for startup"
PROBE_KEY = "x"
DRAFT_STABLE_SECONDS = 5.0
TRANSCRIPT_TAIL_BYTES = 512 * 1024
BACKSPACE = "\x7f"
SEPARATOR = re.compile(r"^\s*─{8,}\s*$")
CODEX_FOOTER = re.compile(r"^\s{2}\S.* · ")
POLL_SECONDS = 2.0
RELOAD_TIMEOUT = 45.0
COMPACT_TIMEOUT = 300.0
SELF_WAIT_SECONDS = 30 * 60
NOTIFY_SECONDS = 120
DEFAULT_APPLY_SECONDS = 240


class RefreshError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def parse_time(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def load_session_context():
    path = PLUGIN_ROOT / "scripts" / "session_context.py"
    spec = importlib.util.spec_from_file_location("hei5enbug_session_context", path)
    if spec is None or spec.loader is None or not path.is_file():
        raise RefreshError("plugin_incomplete", "The plugin's session_context.py is missing.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SESSION_CONTEXT = load_session_context()


def executable(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RefreshError("command_missing", f"Required command is unavailable: {name}.")
    return path


def run(argv: Sequence[str], *, timeout: float = 60.0, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(list(argv), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        raise RefreshError("command_timeout", f"{Path(argv[0]).name} did not finish in {int(timeout)} seconds.") from error
    except OSError as error:
        raise RefreshError("command_failed", f"{Path(argv[0]).name} could not start.") from error
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or [""]
        raise RefreshError("command_failed", f"{Path(argv[0]).name} {' '.join(argv[1:3])} failed: {detail[0][:200]}")
    return result


def run_json(argv: Sequence[str], *, timeout: float = 60.0) -> object:
    result = run(argv, timeout=timeout)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RefreshError("invalid_json", f"{Path(argv[0]).name} returned unreadable JSON.") from error


def state_root() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    root = base / PLUGIN / "orca-plugin-refresh"
    (root / "runs").mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def run_path(run_id: str) -> Path:
    if not RUN_ID.fullmatch(run_id):
        raise RefreshError("invalid_run_id", "The run ID is invalid.")
    return state_root() / "runs" / f"{run_id}.json"


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=1)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_run(run_id: str) -> dict:
    try:
        return json.loads(run_path(run_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RefreshError("run_missing", "No saved update run matches that ID.") from error


@contextmanager
def exclusive(name: str, wait_seconds: float = 0.0) -> Iterator[None]:
    """Hold one machine-wide lock so only one process sends commands to Orca sessions at a time."""
    path = state_root() / f"{name}.lock"
    deadline = time.time() + wait_seconds
    with path.open("a+") as handle:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as error:
                if time.time() >= deadline:
                    raise RefreshError("already_running", "Another refresh run is still sending commands to sessions.") from error
                time.sleep(1.0)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def installed(host: str) -> dict:
    if host == "claude":
        payload = run_json([executable("claude"), "plugin", "list", "--json"])
        matches = [item for item in payload if isinstance(item, dict) and item.get("id") == PLUGIN_ID] if isinstance(payload, list) else []
        if len(matches) != 1 or matches[0].get("enabled") is not True:
            raise RefreshError("claude_plugin_missing", "The Claude Code plugin is not installed and enabled exactly once.")
        root = Path(str(matches[0].get("installPath") or ""))
    else:
        payload = run_json([executable("codex"), "plugin", "list", "--json"])
        items = payload.get("installed") if isinstance(payload, dict) else None
        matches = [item for item in items if isinstance(item, dict) and item.get("pluginId") == PLUGIN_ID] if isinstance(items, list) else []
        if len(matches) != 1 or matches[0].get("enabled") is not True:
            raise RefreshError("codex_plugin_missing", "The Codex plugin is not installed and enabled exactly once.")
        home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        root = home / "plugins" / "cache" / MARKETPLACE / PLUGIN / str(matches[0].get("version"))
    version = matches[0].get("version")
    if not isinstance(version, str) or not root.is_absolute() or not root.is_dir():
        raise RefreshError(f"{host}_root_missing", f"The installed {host} plugin directory is unavailable.")
    return {"version": version, "root": root.resolve().as_posix()}


def inside(root: Path, path: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def validate_claude_mod(root: Path, manifest: dict) -> None:
    missing = RefreshError("plugin_hook_target_missing", "An installed claude plugin mod file is missing.")
    hooks = manifest.get("hooks")
    if not isinstance(hooks, str) or not hooks:
        raise missing
    config_path = root / hooks
    if not inside(root, config_path) or not config_path.is_file():
        raise missing
    try:
        modules = json.loads(config_path.read_text(encoding="utf-8")).get("modules")
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError) as error:
        raise missing from error
    if not isinstance(modules, list) or not modules:
        raise missing
    for module in modules:
        module_path = config_path.parent / module if isinstance(module, str) and module else None
        if module_path is None or not inside(root, module_path) or not module_path.is_file():
            raise missing


def validate_install(host: str, install: dict) -> dict:
    root = Path(install["root"])
    version = install["version"]
    manifest_path = root / (".claude-plugin/plugin.json" if host == "claude" else ".codex-plugin/plugin.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RefreshError("plugin_manifest_missing", f"The installed {host} plugin manifest is unavailable or unreadable.") from error
    if not isinstance(manifest, dict) or manifest.get("name") != PLUGIN or manifest.get("version") != version:
        raise RefreshError("plugin_manifest_mismatch", f"The installed {host} plugin manifest does not match version {version}.")

    hooks_path = root / "hooks" / "hooks.json"
    try:
        hooks_bytes = hooks_path.read_bytes()
        payload = json.loads(hooks_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RefreshError("plugin_hooks_missing", f"The installed {host} plugin hooks are unavailable or unreadable.") from error
    events = payload.get("hooks") if isinstance(payload, dict) else None
    if not isinstance(events, dict) or not events:
        raise RefreshError("plugin_hooks_invalid", f"The installed {host} plugin hooks are unsupported.")
    seen_targets: set[str] = set()
    for groups in events.values():
        if not isinstance(groups, list):
            raise RefreshError("plugin_hooks_invalid", f"The installed {host} plugin hooks are unsupported.")
        for group in groups:
            entries = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(entries, list):
                raise RefreshError("plugin_hooks_invalid", f"The installed {host} plugin hooks are unsupported.")
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("type") != "command" or not isinstance(entry.get("command"), str):
                    raise RefreshError("plugin_hooks_invalid", f"The installed {host} plugin hooks are unsupported.")
                try:
                    argv = shlex.split(entry["command"])
                except ValueError as error:
                    raise RefreshError("plugin_hooks_invalid", f"The installed {host} plugin hooks are unsupported.") from error
                target = next((item for item in argv[1:] if item.startswith("${CLAUDE_PLUGIN_ROOT}/")), None)
                if target is None:
                    raise RefreshError("plugin_hooks_invalid", f"The installed {host} plugin hook target is unsupported.")
                relative_target = target.removeprefix("${CLAUDE_PLUGIN_ROOT}/")
                seen_targets.add(relative_target)
                target_path = root / relative_target
                if not target_path.is_file():
                    raise RefreshError("plugin_hook_target_missing", f"An installed {host} plugin hook target is missing.")
    if not set(REQUIRED_HOOK_TARGETS) <= seen_targets:
        raise RefreshError("plugin_hook_target_missing", f"The installed {host} plugin hooks omit a required target.")
    if host == "claude":
        validate_claude_mod(root, manifest)
    try:
        digest = SESSION_CONTEXT.instructions_digest(root)
    except OSError as error:
        raise RefreshError("plugin_digest_missing", f"The installed {host} plugin instruction digest could not be read.") from error
    if not isinstance(digest, str) or not digest:
        raise RefreshError("plugin_digest_missing", f"The installed {host} plugin instruction digest is missing.")
    return {"digest": digest, "hooks": hashlib.sha256(hooks_bytes).hexdigest()}


ACTIVE_SESSION_ENV = (
    "ORCA_TERMINAL_HANDLE",
    "CLAUDE_PLUGIN_ROOT",
    "PLUGIN_ROOT",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDECODE",
    "CODEX_THREAD_ID",
    "CODEX_SESSION_ID",
)


def active_orca_terminals(orca: "Orca") -> bool:
    active = False
    for terminal in orca.terminals():
        handle = terminal.get("handle")
        identity = terminal.get("agentIdentity")
        connected = terminal.get("connected")
        if not isinstance(handle, str) or not HANDLE.fullmatch(handle) or not isinstance(connected, bool):
            raise RefreshError("update_deferred_unknown_session_state", "Orca returned unsupported terminal data.")
        if "agentIdentity" not in terminal or (identity is not None and (not isinstance(identity, str) or not identity.strip())):
            raise RefreshError("update_deferred_unknown_session_state", "Orca returned unsupported terminal data.")
        if not connected:
            continue
        if isinstance(identity, str) and identity.strip():
            active = True
            continue
        directory = SESSION_CONTEXT.marker_directory()
        marker_path = directory / f"{handle}.json" if directory is not None else None
        if marker_path is None or not marker_path.exists():
            continue
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise RefreshError("update_deferred_unknown_session_state", "An Orca session marker could not be read.") from error
        if not isinstance(marker, dict) or marker.get("schema") != SESSION_CONTEXT.MARKER_SCHEMA or marker.get("host") not in HOSTS:
            raise RefreshError("update_deferred_unknown_session_state", "An Orca session marker has an unsupported format.")
        active = True
    return active


def assert_update_safe(offline: bool) -> None:
    signals = [name for name in ACTIVE_SESSION_ENV if name in os.environ]
    if signals:
        raise RefreshError("update_deferred_active_session", "A coding-agent or Orca session environment is active.")
    try:
        active = active_orca_terminals(Orca())
    except RefreshError as error:
        if offline and error.code == "command_missing":
            return
        if error.code == "update_deferred_unknown_session_state":
            raise
        raise RefreshError("update_deferred_unknown_session_state", "Orca session inventory is unavailable.") from error
    if active:
        raise RefreshError("update_deferred_active_session", "A connected coding-agent session is present in Orca.")
    if not offline:
        raise RefreshError("update_deferred_unknown_session_state", "Use --offline only after affected coding-agent sessions have ended.")


def recovery_command(root: str | None) -> str:
    current = Path(__file__).resolve()
    try:
        relative = current.relative_to(PLUGIN_ROOT)
    except ValueError:
        relative = current.name
    candidate = Path(root) / relative if root else current
    script = candidate if candidate.is_file() else current
    return f"python3 {shlex.quote(str(script))} update --offline --json"


def claude_unreleased_changes() -> tuple[list[str], str | None]:
    """Runtime files the Claude marketplace has but a same-version install cannot pick up, or why that is unknown."""
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    try:
        record = json.loads((config / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
        installed_sha = record["plugins"][PLUGIN_ID][0]["gitCommitSha"]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return [], "installed commit is not recorded"
    try:
        marketplaces = run_json([executable("claude"), "plugin", "marketplace", "list", "--json"])
    except RefreshError as error:
        return [], error.message
    entries = [item for item in marketplaces if isinstance(item, dict) and item.get("name") == MARKETPLACE] if isinstance(marketplaces, list) else []
    if len(entries) != 1 or not isinstance(entries[0].get("installLocation"), str):
        return [], "the marketplace clone is not listed"
    clone = entries[0]["installLocation"]
    head = run([executable("git"), "-C", clone, "rev-parse", "HEAD"], check=False)
    if head.returncode != 0 or not head.stdout.strip():
        return [], "the marketplace revision is unreadable"
    if head.stdout.strip() == installed_sha:
        return [], None
    diff = run([executable("git"), "-C", clone, "diff", "--name-only", installed_sha, head.stdout.strip(), "--", *RUNTIME_PATHS], check=False)
    if diff.returncode != 0:
        return [], "the installed commit is not in the marketplace clone"
    return [line for line in diff.stdout.splitlines() if line.strip()], None


def update_host(host: str, offline: bool = False) -> dict:
    before = installed(host)
    before_snapshot = validate_install(host, before)
    try:
        assert_update_safe(offline)
    except RefreshError as error:
        if error.code in {"update_deferred_active_session", "update_deferred_unknown_session_state"}:
            error.details.update(root=before["root"], recovery_command=recovery_command(before["root"]))
        raise
    if host == "claude":
        run([executable("claude"), "plugin", "marketplace", "update", MARKETPLACE], timeout=180)
        run([executable("claude"), "plugin", "update", PLUGIN_ID], timeout=180)
    else:
        run([executable("codex"), "plugin", "marketplace", "upgrade", MARKETPLACE], timeout=180)
        run([executable("codex"), "plugin", "add", PLUGIN_ID], timeout=180)
    after = installed(host)
    after_snapshot = validate_install(host, after)
    result = {
        "before_version": before["version"],
        "after_version": after["version"],
        "root": after["root"],
        "previous_root": before["root"],
        "digest": after_snapshot["digest"],
        "instructions_changed": before_snapshot["digest"] != after_snapshot["digest"],
        "warnings": [],
    }
    if host == "claude":
        pending, unknown = claude_unreleased_changes()
        if unknown:
            result["warnings"].append(
                {"code": "unreleased_check_unavailable", "message": f"Could not check whether Claude Code missed same-version files: {unknown}."}
            )
        elif pending and before["version"] == after["version"]:
            result["warnings"].append(
                {"code": "unreleased_same_version", "message": "Claude Code keeps the installed copy because the version did not change; bump the version to release these files.", "files": pending[:20]}
            )
    if host == "codex" and before_snapshot["hooks"] != after_snapshot["hooks"]:
        result["warnings"].append(
            {"code": "codex_hooks_need_trust", "message": "hooks.json changed; review and trust the plugin hooks in Codex /hooks, or they are skipped."}
        )
    return result


def command_update(offline: bool = False) -> dict:
    run_id = uuid.uuid4().hex
    hosts: dict[str, dict] = {}
    for host in HOSTS:
        try:
            hosts[host] = update_host(host, offline=offline)
        except RefreshError as error:
            entry = {"error": {"code": error.code, "message": error.message}}
            for key in ("root", "recovery_command"):
                if key in error.details:
                    entry[key] = error.details[key]
            hosts[host] = entry
    state = {"run_id": run_id, "created_at": now(), "hosts": hosts, "sessions": {}}
    save_json(run_path(run_id), state)
    script = continuation_script(hosts)
    return {"ok": all("error" not in value for value in hosts.values()), "run_id": run_id, "script": script, "hosts": hosts}


def command_apply_installed() -> dict:
    run_id = uuid.uuid4().hex
    hosts: dict[str, dict] = {}
    for host in HOSTS:
        try:
            current = installed(host)
            current_snapshot = validate_install(host, current)
            hosts[host] = {
                "before_version": current["version"],
                "after_version": current["version"],
                "root": current["root"],
                "previous_root": PLUGIN_ROOT.as_posix(),
                "digest": current_snapshot["digest"],
                "instructions_changed": False,
                "warnings": [],
            }
        except RefreshError as error:
            hosts[host] = {"error": {"code": error.code, "message": error.message}}
    state = {"run_id": run_id, "created_at": now(), "hosts": hosts, "sessions": {}}
    save_json(run_path(run_id), state)
    script = continuation_script(hosts)
    return {"ok": all("error" not in value for value in hosts.values()), "run_id": run_id, "script": script, "hosts": hosts}


def continuation_script(hosts: dict[str, dict]) -> str:
    """The copy of this script that later commands must use; a Codex update deletes the invoking installation."""
    here = Path(__file__).resolve()
    for result in hosts.values():
        previous, root = result.get("previous_root"), result.get("root")
        if isinstance(previous, str) and isinstance(root, str) and here.is_relative_to(Path(previous)):
            candidate = Path(root) / here.relative_to(Path(previous))
            if candidate.is_file():
                return str(candidate)
    return str(here)


class Orca:
    """Thin wrapper over the Orca CLI so the refresh logic can be tested without Orca."""

    def __init__(self) -> None:
        configured = os.environ.get("ORCA_CLI_COMMAND")
        if configured:
            self.command = [configured]
        elif os.environ.get("ORCA_DEV_REPO_ROOT"):
            self.command = [executable("orca-dev")]
        else:
            self.command = [executable("orca")]

    def call(self, *args: str, timeout: float = 30.0) -> dict:
        payload = run_json([*self.command, *args, "--json"], timeout=timeout)
        if not isinstance(payload, dict) or payload.get("ok") is False:
            raise RefreshError("orca_rejected", f"Orca rejected `{' '.join(args[:2])}`.")
        result = payload.get("result", payload)
        if not isinstance(result, dict):
            raise RefreshError("orca_invalid", "Orca returned an unsupported result.")
        return result

    def terminals(self) -> list[dict]:
        result = self.call("terminal", "list")
        terminals = result.get("terminals")
        if not isinstance(terminals, list):
            raise RefreshError("orca_invalid", "Orca returned an unsupported terminal list.")
        truncated = result.get("truncated")
        total_count = result.get("totalCount")
        if truncated is not None and not isinstance(truncated, bool):
            raise RefreshError("orca_invalid", "Orca returned unsupported terminal-list metadata.")
        if total_count is not None and (not isinstance(total_count, int) or isinstance(total_count, bool) or total_count < len(terminals)):
            raise RefreshError("orca_invalid", "Orca returned unsupported terminal-list metadata.")
        if truncated is True or (total_count is not None and total_count > len(terminals)):
            raise RefreshError("terminal_list_truncated", "Orca truncated the terminal list, so some sessions could be missed.")
        if any(not isinstance(item, dict) for item in terminals):
            raise RefreshError("orca_invalid", "Orca returned unsupported terminal data.")
        return terminals

    def idle(self, handle: str) -> bool:
        result = run([*self.command, "terminal", "wait", "--terminal", handle, "--for", "tui-idle", "--timeout-ms", "500", "--json"], timeout=15, check=False)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RefreshError("invalid_json", "Orca returned unreadable JSON for a wait.") from error
        if isinstance(payload, dict) and payload.get("ok") is False:
            error = payload.get("error")
            if isinstance(error, dict) and error.get("code") == "timeout":
                return False
            raise RefreshError("orca_rejected", "Orca could not report whether the terminal is idle.")
        wait = payload.get("result", {}).get("wait") if isinstance(payload, dict) else None
        return isinstance(wait, dict) and wait.get("satisfied") is True

    def screen(self, handle: str) -> tuple[list[str], object]:
        terminal = self.call("terminal", "read", "--terminal", handle, "--screen").get("terminal")
        if not isinstance(terminal, dict):
            raise RefreshError("orca_invalid", "Orca returned an unsupported screen.")
        tail = terminal.get("tail")
        lines = [line for line in tail if isinstance(line, str)] if isinstance(tail, list) else []
        return lines, terminal.get("draft")

    def draft(self, handle: str) -> object:
        terminal = self.call("terminal", "read", "--terminal", handle, "--limit", "1").get("terminal")
        return terminal.get("draft") if isinstance(terminal, dict) else None

    def keys(self, handle: str, text: str) -> None:
        send = self.call("terminal", "send", "--terminal", handle, "--text", text).get("send")
        if not isinstance(send, dict) or send.get("accepted") is not True:
            raise RefreshError("input_not_accepted", "Orca did not accept the keystroke.")

    def send(self, handle: str, text: str) -> None:
        send = self.call("terminal", "send", "--terminal", handle, "--text", text, "--enter").get("send")
        if not isinstance(send, dict) or send.get("accepted") is not True:
            raise RefreshError("input_not_accepted", "Orca did not accept the command.")


def agent_host(terminal: dict) -> str | None:
    identity = str(terminal.get("agentIdentity") or "").strip().lower()
    if identity in {"claude", "claude-code", "claude code"}:
        return "claude"
    return "codex" if identity == "codex" else None


def input_state(host: str, lines: Sequence[str]) -> str:
    """Return `empty`, `text`, or `unknown` for the composer line of an agent TUI screen."""
    if host == "claude":
        for index in range(len(lines) - 1, 0, -1):
            if not SEPARATOR.match(lines[index]):
                continue
            opening = next((row for row in range(index - 1, -1, -1) if SEPARATOR.match(lines[row])), None)
            if opening is None or index - opening < 2:
                continue
            body = [line.strip() for line in lines[opening + 1:index]]
            if not body[0].startswith("❯"):
                continue
            content = "\n".join([body[0][1:].strip(), *body[1:]]).strip()
            return "empty" if not content or CLAUDE_PLACEHOLDER.match(content) else "text"
        return "unknown"
    if any(CODEX_STARTING in line for line in lines[-8:]):
        return "unknown"
    for index in range(len(lines) - 1, -1, -1):
        stripped = lines[index].strip()
        if not stripped.startswith("›"):
            continue
        following = next((line for line in lines[index + 1:] if line.strip()), "")
        if not CODEX_FOOTER.match(following):
            return "unknown"
        content = stripped[1:].strip()
        return "empty" if not content or content in CODEX_PLACEHOLDERS else "text"
    return "unknown"


def codex_fresh(lines: Sequence[str]) -> bool:
    """A Codex session that never ran a turn has not loaded any instructions yet; its first turn loads the new ones."""
    banner = any("OpenAI Codex (v" in line for line in lines)
    conversation = any(line.strip().startswith("•") for line in lines)
    prompts = [line for line in lines if line.strip().startswith("›")]
    return banner and not conversation and len(prompts) <= 1 and input_state("codex", lines) != "text"


def read_marker(handle: str) -> dict | None:
    directory = SESSION_CONTEXT.marker_directory()
    if directory is None or not HANDLE.fullmatch(handle):
        return None
    try:
        payload = json.loads((directory / f"{handle}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def compact_reason(host: str, marker: dict | None, target: dict, mode: str) -> str | None:
    if mode == "never":
        return None
    if mode == "always":
        return "requested"
    if marker is None:
        return "session_started_before_markers"
    if marker.get("schema") != SESSION_CONTEXT.MARKER_SCHEMA or marker.get("host") != host:
        return "marker_unrecognized"
    if marker.get("digest") != target.get("digest"):
        return "instructions_changed"
    loaded_root = marker.get("root")
    if host == "codex" and loaded_root != target.get("root"):
        return "codex_root_replaced"
    if host == "claude" and not (isinstance(loaded_root, str) and Path(loaded_root).is_dir()):
        return "claude_root_removed"
    return None


def plan_sessions(orca: Orca, state: dict, mode: str, only: Sequence[str]) -> list[dict]:
    initiator = os.environ.get("ORCA_TERMINAL_HANDLE")
    sessions: list[dict] = []
    for terminal in orca.terminals():
        host = agent_host(terminal)
        handle = terminal.get("handle")
        if host is None or not isinstance(handle, str) or not HANDLE.fullmatch(handle):
            continue
        if only and handle not in only:
            continue
        target = state["hosts"].get(host, {})
        entry = {
            "handle": handle,
            "host": host,
            "title": terminal.get("title"),
            "worktree": terminal.get("worktreePath"),
            "initiator": handle == initiator,
            "actions": [],
            "status": "pending",
            "detail": None,
        }
        if "error" in target:
            entry.update(status="blocked", detail=f"{host}_update_failed")
        else:
            if host == "claude":
                entry["actions"].append("reload")
            reason = compact_reason(host, read_marker(handle), target, mode)
            if reason:
                entry["actions"].append("compact")
                entry["compact_reason"] = reason
            if not entry["actions"]:
                entry.update(status="done", detail="already_current")
        sessions.append(entry)
    return sessions


def settle(read: Callable[[], object], until: Callable[[object], bool], sleep: Callable[[float], None], seconds: float = 3.0) -> object:
    deadline = time.time() + seconds
    value = read()
    while not until(value) and time.time() < deadline:
        sleep(0.3)
        value = read()
    return value


def claude_draft_state(orca: Orca, handle: str, draft: str, sleep: Callable[[float], None] = time.sleep) -> str:
    """Tell typed text from Claude Code's ghost prompt suggestion; return `empty`, `text`, or `interrupted`.

    Orca reports both as `draft`. Typing one character replaces a suggestion but appends to typed text, and a
    backspace restores the original draft. The backspace is sent only when the draft shows exactly the probe's own
    character, so input that arrives during the probe is never deleted.
    """
    orca.keys(handle, PROBE_KEY)
    try:
        probed = settle(lambda: orca.draft(handle), lambda value: value != draft, sleep)
    except RefreshError:
        return "interrupted"
    if probed not in (PROBE_KEY, draft + PROBE_KEY):
        return "interrupted"
    orca.keys(handle, BACKSPACE)
    try:
        restored = settle(lambda: orca.draft(handle), lambda value: value == draft, sleep)
    except RefreshError:
        return "interrupted"
    if restored != draft:
        return "interrupted"
    return "empty" if probed == PROBE_KEY else "text"


def ready(orca: Orca, entry: dict, live: dict[str, dict]) -> tuple[str | None, list[str]]:
    """Return (None, screen) when a command can be sent safely, otherwise the reason to wait."""
    terminal = live.get(entry["handle"])
    if terminal is None or agent_host(terminal) != entry["host"]:
        return "terminal_gone", []
    if terminal.get("connected") is not True or terminal.get("writable") is not True or terminal.get("orphaned") is True:
        return "terminal_unavailable", []
    if not orca.idle(entry["handle"]):
        return "busy", []
    lines, draft = orca.screen(entry["handle"])
    entry["observed_draft"] = draft if isinstance(draft, str) else None
    if not (isinstance(draft, str) and draft.strip()):
        state = input_state(entry["host"], lines)
        return (None if state == "empty" else ("unsent_input" if state == "text" else "input_unknown")), lines
    if entry["host"] != "claude" or entry.get("typed_draft") == draft:
        return "unsent_input", lines
    seen = entry.get("draft_seen")
    if not seen or seen[0] != draft:
        entry["draft_seen"] = (draft, time.time())
        return "input_settling", lines
    if time.time() - seen[1] < DRAFT_STABLE_SECONDS:
        return "input_settling", lines
    verdict = claude_draft_state(orca, entry["handle"], draft)
    if verdict == "interrupted":
        return "probe_interrupted", lines
    if verdict == "text":
        entry["typed_draft"] = draft
        return "unsent_input", lines
    return None, lines


def result_counts(lines: Sequence[str]) -> dict[str, int]:
    """Count result lines on screen; agent TUIs repaint, so a new result shows up as a higher count."""
    patterns = {
        "reloaded": RELOAD_DONE,
        "refused": RELOAD_REFUSED,
        "claude_compacted": CLAUDE_COMPACTED,
        "codex_compacted": CODEX_COMPACTED,
        "nothing_to_compact": CLAUDE_NOTHING_TO_COMPACT,
    }
    return {name: sum(1 for line in lines if pattern.search(line)) for name, pattern in patterns.items()}


def transcript_size(path: object) -> int:
    try:
        return Path(str(path)).stat().st_size if isinstance(path, str) else 0
    except OSError:
        return 0


def transcript_records(path: object, offset: int) -> list[dict]:
    """Return every complete JSON record appended to a host transcript after byte `offset`."""
    if not isinstance(path, str) or not Path(path).is_file():
        return []
    with open(path, "rb") as stream:
        size = stream.seek(0, os.SEEK_END)
        stream.seek(offset if 0 <= offset <= size else 0)
        chunk = stream.read()
    complete = chunk[: chunk.rfind(b"\n") + 1]
    records = []
    for line in complete.decode("utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def transcript_outcome(host: str, action: str, records: list[dict]) -> str | None:
    for record in records:
        content = str(record.get("content") or "") if record.get("subtype") == "local_command" else ""
        if host == "claude" and action == "reload" and content:
            if RELOAD_REFUSED.search(content):
                return "failed:reload_needs_force"
            if RELOAD_DONE.search(content):
                return "done"
        if host == "claude" and action == "compact" and content:
            if CLAUDE_NOTHING_TO_COMPACT.search(content):
                return "nothing_to_compact"
            if CLAUDE_COMPACT_ERROR.search(content):
                return "failed:compact_error"
        if host == "codex" and action == "compact" and record.get("type") == "compacted":
            return "done"
    return None


def claude_has_prompts(path: object) -> bool:
    """True unless the transcript proves the user never sent a prompt, so /clear cannot lose a conversation."""
    if not isinstance(path, str) or not Path(path).is_file():
        return True
    if Path(path).stat().st_size > TRANSCRIPT_TAIL_BYTES:
        return True
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return True
        message = record.get("message") if isinstance(record, dict) and record.get("type") == "user" else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            text = content.strip()
            if text not in COMMANDS.values() and not text.startswith(COMMAND_RECORD_PREFIXES):
                return True
        elif isinstance(content, list) and any(isinstance(part, dict) and part.get("type") == "text" for part in content):
            return True
    return False


def last_item_is(lines: Sequence[str], echo: str, result: re.Pattern) -> bool:
    """True when the newest conversation item above the Claude Code composer is `echo` followed by `result`."""
    separators = [index for index, line in enumerate(lines) if SEPARATOR.match(line)]
    if len(separators) < 2:
        return False
    above = lines[: separators[-2]]
    echoes = [index for index, line in enumerate(above) if line.strip().startswith("❯")]
    return bool(echoes) and above[echoes[-1]].strip() == f"❯ {echo}" and any(result.search(line) for line in above[echoes[-1] + 1:])


def newer_marker(entry: dict, marker: dict | None, target: dict) -> bool:
    """True only for a marker rewritten after the command was sent that carries the target instructions."""
    if not marker or marker == entry.get("marker_snapshot") or marker.get("digest") != target.get("digest"):
        return False
    written = parse_time(marker.get("written_at"))
    return bool(written and written >= entry["marker_before"])


def verify(orca: Orca, entry: dict, target: dict) -> str | None:
    """Return `done`, `nothing_to_compact`, `failed:<code>`, or None while still waiting."""
    action = entry["actions"][0]
    elapsed = time.time() - entry["sent_at"]
    marker = read_marker(entry["handle"])
    records = transcript_records(entry.get("transcript"), entry.get("transcript_offset", 0))
    from_transcript = transcript_outcome(entry["host"], action, records)
    if from_transcript:
        if entry["host"] == "codex":
            entry["note"] = "instructions_load_on_next_turn"
        return from_transcript
    if action == "clear":
        if newer_marker(entry, marker, target):
            entry["note"] = "empty_session_cleared"
            return "done"
        return "failed:clear_unconfirmed" if elapsed > CLEAR_TIMEOUT else None
    lines, _ = orca.screen(entry["handle"])
    grew = {name: count > entry["before"].get(name, 0) for name, count in result_counts(lines).items()}
    before_lines = entry.get("before_lines", [])
    if action == "reload":
        if grew["refused"] or (last_item_is(lines, "/reload-plugins", RELOAD_REFUSED) and not last_item_is(before_lines, "/reload-plugins", RELOAD_REFUSED)):
            return "failed:reload_needs_force"
        if grew["reloaded"] or (last_item_is(lines, "/reload-plugins", RELOAD_DONE) and not last_item_is(before_lines, "/reload-plugins", RELOAD_DONE)):
            return "done"
        return "failed:reload_unconfirmed" if elapsed > RELOAD_TIMEOUT else None
    if entry["host"] == "claude":
        if newer_marker(entry, marker, target):
            return "done"
        if grew["nothing_to_compact"]:
            return "nothing_to_compact"
        if grew["claude_compacted"]:
            entry.setdefault("compacted_at", time.time())
            if time.time() - entry["compacted_at"] > 30:
                return "failed:instructions_unconfirmed"
    elif grew["codex_compacted"]:
        entry["note"] = "instructions_load_on_next_turn"
        return "done"
    return "failed:compact_unconfirmed" if elapsed > COMPACT_TIMEOUT else None


def finish(entry: dict, outcome: str) -> None:
    finished = entry["actions"].pop(0)
    entry.setdefault("completed", []).append(finished if outcome == "done" else f"{finished}:{outcome[7:]}")
    if outcome != "done":
        entry.update(status="failed", detail=outcome[7:], actions=[])
    else:
        entry.update(status="pending" if entry["actions"] else "done", detail=None if entry["actions"] else "applied")


def step(orca: Orca, entry: dict, target: dict, live: dict[str, dict]) -> None:
    if entry["status"] == "sent":
        outcome = verify(orca, entry, target)
        if outcome is None:
            return
        if outcome == "nothing_to_compact":
            if claude_has_prompts((read_marker(entry["handle"]) or {}).get("transcript_path")):
                outcome = "failed:compact_needs_more_messages"
            else:
                entry["actions"][0] = "clear"
                entry.update(status="pending", detail="empty_session_needs_clear")
                return
        finish(entry, outcome)
        return
    if entry["status"] != "pending" or not entry["actions"]:
        return
    reason, lines = ready(orca, entry, live)
    entry["detail"] = reason
    if reason == "terminal_gone":
        entry.update(status="skipped", actions=[])
        return
    if reason == "probe_interrupted":
        entry.update(status="failed", detail="probe_interrupted_check_input", actions=[])
        return
    if entry["host"] == "codex" and reason in (None, "busy"):
        screen = lines if reason is None else orca.screen(entry["handle"])[0]
        if codex_fresh(screen):
            entry.update(status="done", detail="fresh_session_loads_on_first_turn", actions=[])
            return
    if reason:
        return
    marker = read_marker(entry["handle"])
    if entry["actions"][0] == "clear" and claude_has_prompts((marker or {}).get("transcript_path")):
        entry["actions"].insert(0, "compact")
        finish(entry, "failed:compact_needs_more_messages")
        return
    if entry["host"] == "claude" and orca.draft(entry["handle"]) != entry.get("observed_draft"):
        entry["detail"] = "input_changed"
        return
    entry["before"] = result_counts(lines)
    entry["before_lines"] = lines
    entry["transcript"] = (marker or {}).get("transcript_path")
    entry["transcript_offset"] = transcript_size(entry["transcript"])
    entry["marker_before"] = parse_time((marker or {}).get("written_at")) or 0.0
    entry["marker_snapshot"] = marker
    entry["sent_at"] = time.time()
    orca.send(entry["handle"], COMMANDS[entry["actions"][0]])
    entry["status"] = "sent"


def drive(orca: Orca, sessions: list[dict], state: dict, deadline: float, sleep: Callable[[float], None] = time.sleep) -> None:
    """Send commands until `deadline`, then stop starting new ones and keep verifying the ones already sent."""
    while True:
        if time.time() >= deadline:
            for entry in sessions:
                if entry["status"] == "pending":
                    entry.update(status="skipped", detail=entry.get("detail") or "deadline_reached")
        active = [entry for entry in sessions if entry["status"] in {"pending", "sent"}]
        if not active:
            return
        try:
            live = {item.get("handle"): item for item in orca.terminals()}
        except RefreshError:
            live = None
        for entry in active:
            if live is None:
                entry["detail"] = "terminal_list_unavailable"
                continue
            if entry["status"] == "pending" and time.time() >= deadline:
                entry.update(status="skipped", detail=entry.get("detail") or "deadline_reached")
                continue
            try:
                step(orca, entry, state["hosts"][entry["host"]], live)
            except RefreshError as error:
                entry.update(status="failed", detail=error.code, actions=[])
        sleep(POLL_SECONDS)


def public(entry: dict) -> dict:
    keys = ("host", "title", "worktree", "status", "detail", "completed", "actions", "compact_reason", "note", "initiator")
    view = {key: entry.get(key) for key in keys if entry.get(key) not in (None, [], False)}
    view["terminal"] = f"…{entry['handle'][-6:]}"
    return view


def spawn_self_apply(run_id: str) -> int:
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "self-apply", "--run-id", run_id],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
        cwd=state_root(),
    )
    return process.pid


def alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def command_plan(run_id: str, mode: str, only: Sequence[str]) -> dict:
    state = load_run(run_id)
    sessions = plan_sessions(Orca(), state, mode, only)
    return {"ok": True, "run_id": run_id, "sessions": [public(entry) for entry in sessions]}


def handled(state: dict, handle: str) -> str | None:
    """The status a session already reached in this run, ignoring a queue whose helper never ran or died."""
    status = state.get("sessions", {}).get(handle, {}).get("status")
    if status == "done":
        return status
    if status == "queued_after_turn":
        own = state.get("self") or {}
        if own.get("handle") == handle and (alive(own.get("helper_pid")) or state.get("self_finished_at")):
            return status
    return None


def command_apply(run_id: str, mode: str, only: Sequence[str], seconds: int, spawn: Callable[[str], int] = spawn_self_apply) -> dict:
    with exclusive("sessions"):
        state = load_run(run_id)
        orca = Orca()
        sessions = plan_sessions(orca, state, mode, only)
        for entry in sessions:
            previous = handled(state, entry["handle"])
            if previous:
                entry.update(status=previous, detail="already_handled_in_this_run", actions=[])
        others = [entry for entry in sessions if not entry["initiator"]]
        drive(orca, others, state, time.time() + seconds)
        own = next((entry for entry in sessions if entry["initiator"] and entry["status"] == "pending"), None)
        if own:
            try:
                pid = spawn(run_id)
            except OSError:
                own.update(status="failed", detail="helper_start_failed", actions=[])
            else:
                own.update(status="queued_after_turn", detail="waits_for_this_turn_to_end")
                state["self"] = {key: own[key] for key in ("handle", "host", "actions", "title", "worktree")}
                state["self"].update(compact_reason=own.get("compact_reason"), helper_pid=pid, helper_started_at=now())
                state.pop("self_finished_at", None)
        state["sessions"] = {**state.get("sessions", {}), **{entry["handle"]: public(entry) for entry in sessions}}
        state["applied_at"] = now()
        save_json(run_path(run_id), state)
    summary = {status: sum(1 for entry in sessions if entry["status"] == status) for status in {entry["status"] for entry in sessions}}
    return {"ok": all(entry["status"] in {"done", "queued_after_turn"} for entry in sessions), "run_id": run_id, "summary": summary, "sessions": [public(entry) for entry in sessions]}


def notify(orca: Orca, entry: dict, run_id: str, sleep: Callable[[float], None]) -> str:
    message = f"Plugin refresh run {run_id} finished for this session. Run `{status_command(run_id)}` and report the result."
    notice = {"handle": entry["handle"], "host": entry["host"]}
    deadline = time.time() + NOTIFY_SECONDS
    reason: str | None = "not_attempted"
    while time.time() < deadline:
        try:
            live = {item.get("handle"): item for item in orca.terminals()}
            reason, _ = ready(orca, notice, live)
            if reason is None and (entry["host"] != "claude" or orca.draft(entry["handle"]) == notice.get("observed_draft")):
                orca.send(entry["handle"], message)
                return "sent"
            if reason in {"terminal_gone", "probe_interrupted", "unsent_input"}:
                break
        except RefreshError as error:
            reason = error.code
        sleep(POLL_SECONDS)
    return f"not_sent:{reason}"


def command_self_apply(run_id: str, sleep: Callable[[float], None] = time.sleep) -> int:
    with exclusive("sessions", wait_seconds=SELF_WAIT_SECONDS):
        state = load_run(run_id)
        own = state.get("self")
        if not isinstance(own, dict):
            return 0
        entry = {**own, "actions": list(own["actions"]), "status": "pending", "initiator": True, "detail": None}
        orca = Orca()
        drive(orca, [entry], state, time.time() + SELF_WAIT_SECONDS, sleep=sleep)
        state = load_run(run_id)
        state["sessions"][entry["handle"]] = public(entry)
        state["self_finished_at"] = now()
        state["self_notification"] = "pending"
        save_json(run_path(run_id), state)
        notification = notify(orca, entry, run_id, sleep) if entry["status"] in {"done", "failed"} else "not_sent:session_skipped"
        state = load_run(run_id)
        state["self_notification"] = notification
        save_json(run_path(run_id), state)
    return 0


def status_command(run_id: str) -> str:
    prefix = f"XDG_STATE_HOME={shlex.quote(os.environ['XDG_STATE_HOME'])} " if os.environ.get("XDG_STATE_HOME") else ""
    return f"{prefix}python3 {shlex.quote(str(Path(__file__).resolve()))} status --run-id {run_id} --json"


def command_status(run_id: str) -> dict:
    state = load_run(run_id)
    return {
        "ok": True,
        "run_id": run_id,
        "hosts": state.get("hosts"),
        "sessions": list(state.get("sessions", {}).values()),
        "self_finished_at": state.get("self_finished_at"),
        "self_notification": state.get("self_notification"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    update = commands.add_parser("update")
    update.add_argument("--offline", action="store_true")
    update.add_argument("--json", action="store_true")
    commands.add_parser("apply-installed").add_argument("--json", action="store_true")
    for name in ("plan", "apply"):
        sub = commands.add_parser(name)
        sub.add_argument("--run-id", required=True)
        sub.add_argument("--compact", choices=("auto", "always", "never"), default="auto")
        sub.add_argument("--terminal", action="append", default=[])
        sub.add_argument("--json", action="store_true")
        if name == "apply":
            sub.add_argument("--timeout-seconds", type=int, default=DEFAULT_APPLY_SECONDS)
    commands.add_parser("self-apply").add_argument("--run-id", required=True)
    status = commands.add_parser("status")
    status.add_argument("--run-id", required=True)
    status.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "self-apply":
            return command_self_apply(args.run_id)
        if args.command == "update":
            output = command_update(args.offline)
        elif args.command == "apply-installed":
            output = command_apply_installed()
        elif args.command == "plan":
            output = command_plan(args.run_id, args.compact, args.terminal)
        elif args.command == "apply":
            output = command_apply(args.run_id, args.compact, args.terminal, max(30, args.timeout_seconds))
        else:
            output = command_status(args.run_id)
    except RefreshError as error:
        output = {"ok": False, "error": {"code": error.code, "message": error.message}}
    print(json.dumps(output, ensure_ascii=False, indent=1))
    return 0 if output.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
