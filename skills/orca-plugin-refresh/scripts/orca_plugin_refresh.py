#!/usr/bin/env python3
"""Update hei5enbug-agent-setup and companion plugins, then apply installed versions to idle Orca agent sessions."""

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
import threading
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
REQUIRED_HOOKS = {
    "claude": (
        ("SessionStart", "scripts/session_context.py"),
        ("SubagentStart", "scripts/session_context.py"),
        ("UserPromptSubmit", "scripts/session_context.py"),
        ("PreToolUse", "scripts/datagrip_guard.py"),
        ("PostToolUse", "scripts/language_guard.py"),
        ("Stop", "scripts/language_guard.py"),
    ),
    "codex": (
        ("SessionStart", "scripts/session_context.py"),
        ("SubagentStart", "scripts/session_context.py"),
        ("PreToolUse", "scripts/agent_guard.py"),
        ("PreToolUse", "scripts/datagrip_guard.py"),
        ("PermissionRequest", "scripts/datagrip_guard.py"),
        ("PostToolUse", "scripts/language_guard.py"),
        ("Stop", "scripts/language_guard.py"),
    ),
}
REQUIRED_HOOK_TARGETS = {host: tuple(dict.fromkeys(script for _, script in hooks)) for host, hooks in REQUIRED_HOOKS.items()}
DEFAULT_HOOKS = "./hooks/hooks.json"
HOOK_LAUNCHER = "scripts/hook_python.sh"
LAUNCHED_SCRIPT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.py")
HOOK_ROOT = "${CLAUDE_PLUGIN_ROOT}/"
COMPANION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}@[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
COMPANION_LIMIT = 10
COMPANION_ENV = "HEI5ENBUG_REFRESH_PLUGINS"
CODEX_TURN_ENV = ("CODEX_THREAD_ID", "CODEX_SESSION_ID")
CODEX_IDLE_EVENTS = {"task_complete", "turn_aborted"}
ROLLOUT_RECENT_SECONDS = 30 * 60
ROLLOUT_TAIL_BYTES = 64 * 1024
HOOKS_TRUST_WARNING = {"code": "codex_hooks_need_trust", "message": "Hook definitions changed; review and trust the plugin hooks in Codex /hooks, or they are skipped."}
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
PROBE_RETRIES = 3
PROBE_RECHECK_SECONDS = 3.0
TRANSCRIPT_TAIL_BYTES = 512 * 1024
BACKSPACE = "\x7f"
SEPARATOR = re.compile(r"^\s*─{8,}\s*$")
TITLED_SEPARATOR = re.compile(r"^─{8,} \S.* ─+\s*$")
CODEX_FOOTER = re.compile(r"^\s{2}\S.* · ")
POLL_SECONDS = 2.0
FINAL_STATUSES = frozenset({"done", "skipped", "failed"})
RELOAD_TIMEOUT = 45.0
COMPACT_TIMEOUT = 300.0
SELF_WAIT_SECONDS = 60 * 60
NOTIFY_SECONDS = 120
DEFAULT_APPLY_SECONDS = 20
FOLLOW_UP_SECONDS = 60 * 60
IDLE_CONFIRM_SECONDS = 3.0
INSTALL_CHECK_SECONDS = 30.0


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


def load_plugin_script(name: str):
    path = PLUGIN_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"hei5enbug_{name}", path)
    if spec is None or spec.loader is None or not path.is_file():
        raise RefreshError("plugin_incomplete", f"The plugin's {name}.py is missing.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SESSION_CONTEXT = load_plugin_script("session_context")


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
        root = codex_home() / "plugins" / "cache" / MARKETPLACE / PLUGIN / str(matches[0].get("version"))
    version = matches[0].get("version")
    if not isinstance(version, str) or not root.is_absolute() or not root.is_dir():
        raise RefreshError(f"{host}_root_missing", f"The installed {host} plugin directory is unavailable.")
    return {"version": version, "root": root.resolve().as_posix(), "item": matches[0]}


def inside(root: Path, path: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def validate_claude_mod(root: Path, manifest: dict) -> None:
    missing = RefreshError("plugin_hook_target_missing", "An installed claude plugin mod file is missing.")
    hooks = manifest.get("hooks")
    if isinstance(hooks, list):
        hooks = hooks[0] if hooks else None
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


def read_manifest(host: str, root: Path, plugin: str, version: str) -> dict:
    manifest_path = root / (".claude-plugin/plugin.json" if host == "claude" else ".codex-plugin/plugin.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RefreshError("plugin_manifest_missing", f"The installed {host} plugin manifest is unavailable or unreadable.") from error
    if not isinstance(manifest, dict) or manifest.get("name") != plugin or manifest.get("version") != version:
        raise RefreshError("plugin_manifest_mismatch", f"The installed {host} plugin manifest does not match version {version}.")
    return manifest


def hook_file_entries(host: str, manifest: dict | None) -> list[tuple[str, bool]]:
    """Return the hook file paths the host loads, in load order, each with whether another check owns it.

    Claude Code always loads hooks/hooks.json and then merges the manifest `hooks` paths; the first listed path is
    the mod config, which validate_claude_mod checks. Codex loads the manifest `hooks` paths, or hooks/hooks.json
    when the manifest lists none.
    """
    value = manifest.get("hooks") if isinstance(manifest, dict) else None
    listed = [value] if isinstance(value, str) else list(value) if isinstance(value, list) else []
    entries = [(DEFAULT_HOOKS, False)] if host == "claude" else []
    entries += [(item, host == "claude" and index == 0) for index, item in enumerate(listed)]
    if not entries:
        entries = [(DEFAULT_HOOKS, False)]
    seen: set = set()
    return [(path, owned) for path, owned in entries
            if not isinstance(path, str) or not (path in seen or seen.add(path))]


def read_hook_file(host: str, root: Path, entry: str, strict: bool, owned: bool) -> tuple[bytes, dict] | None:
    """Read one hook file; None means it is skipped, and a problem it cannot skip raises."""
    invalid = RefreshError("plugin_hooks_invalid", f"The installed {host} plugin hooks are unsupported.")
    missing = RefreshError("plugin_hooks_missing", f"The installed {host} plugin hooks are unavailable or unreadable.")
    path = root / entry if isinstance(entry, str) and entry.startswith("./") else None
    if path is None or not inside(root, path):
        if strict and not owned:
            raise invalid
        return None
    try:
        data = path.read_bytes()
        payload = json.loads(data.decode("utf-8"))
    except FileNotFoundError as error:
        if strict and not owned:
            raise missing from error
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        if owned:
            return None
        raise missing from error
    if not isinstance(payload, dict) or not isinstance(payload.get("hooks"), dict):
        if owned or (not strict and entry != DEFAULT_HOOKS):
            return None
        raise invalid
    return data, payload["hooks"]


def scan_hook_events(host: str, root: Path, events: dict, strict: bool) -> set[tuple[str, str]]:
    """Require every plugin-root hook target in one hook file to exist; return each (event, script) it registers."""
    invalid = RefreshError("plugin_hooks_invalid", f"The installed {host} plugin hooks are unsupported.")
    unsupported_target = RefreshError("plugin_hooks_invalid", f"The installed {host} plugin hook target is unsupported.")
    seen_targets: set[tuple[str, str]] = set()
    for event, groups in events.items():
        if not isinstance(groups, list):
            raise invalid
        for group in groups:
            entries = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(entries, list):
                raise invalid
            for entry in entries:
                if not isinstance(entry, dict) or (entry.get("type") == "command" and not isinstance(entry.get("command"), str)):
                    raise invalid
                if entry.get("type") != "command":
                    if strict:
                        raise invalid
                    continue
                try:
                    argv = shlex.split(entry["command"])
                except ValueError as error:
                    if strict:
                        raise invalid from error
                    continue
                hits = [index for index, item in enumerate(argv) if item.startswith(HOOK_ROOT)]
                if strict and not any(hits):
                    raise unsupported_target
                for index in hits:
                    relative_target = argv[index].removeprefix(HOOK_ROOT)
                    targets = [relative_target]
                    if relative_target == HOOK_LAUNCHER:
                        script = argv[index + 1] if index + 1 < len(argv) else ""
                        if not LAUNCHED_SCRIPT.fullmatch(script):
                            raise unsupported_target
                        targets.append(f"scripts/{script}")
                    for target in targets:
                        if not (root / target).is_file():
                            raise RefreshError("plugin_hook_target_missing", f"An installed {host} plugin hook target is missing.")
                    seen_targets.add((event, targets[-1]))
    return seen_targets


def check_hooks(host: str, root: Path, strict: bool, manifest: dict | None = None) -> tuple[bytes | None, set[tuple[str, str]]]:
    """Read the hook files the host loads and require every plugin-root hook target to exist.

    Strict mode is this plugin's contract: every file the host loads must exist and every hook must be a recognizable
    command. Otherwise a missing file is allowed and hooks without a plugin-root target are skipped. The returned
    bytes cover every loaded file in load order, so a change to any of them changes the digest; None means no file.
    """
    records: list[bytes] = []
    seen_targets: set[tuple[str, str]] = set()
    for entry, owned in hook_file_entries(host, manifest):
        loaded = read_hook_file(host, root, entry, strict, owned)
        if loaded is None:
            continue
        data, events = loaded
        if strict and not events:
            raise RefreshError("plugin_hooks_invalid", f"The installed {host} plugin hooks are unsupported.")
        seen_targets |= scan_hook_events(host, root, events, strict)
        records.append(entry.encode("utf-8") + b"\0" + data + b"\0")
    return (b"".join(records) if records else None), seen_targets


def validate_install(host: str, install: dict) -> dict:
    root = Path(install["root"])
    manifest = read_manifest(host, root, PLUGIN, install["version"])
    hooks_bytes, seen_targets = check_hooks(host, root, strict=True, manifest=manifest)
    if not set(REQUIRED_HOOKS[host]) <= seen_targets:
        raise RefreshError("plugin_hook_target_missing", f"The installed {host} plugin hooks omit a required target.")
    if hooks_bytes is None:
        raise RefreshError("plugin_hooks_missing", f"The installed {host} plugin hooks are unavailable or unreadable.")
    if host == "claude":
        validate_claude_mod(root, manifest)
    try:
        digest = SESSION_CONTEXT.instructions_digest(root)
    except OSError as error:
        raise RefreshError("plugin_digest_missing", f"The installed {host} plugin instruction digest could not be read.") from error
    if not isinstance(digest, str) or not digest:
        raise RefreshError("plugin_digest_missing", f"The installed {host} plugin instruction digest is missing.")
    return {"digest": digest, "hooks": hashlib.sha256(hooks_bytes).hexdigest()}


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def rollout_idle(path: Path) -> bool:
    """True only when the last complete line of a Codex rollout file records the end of a turn."""
    with path.open("rb") as stream:
        size = stream.seek(0, os.SEEK_END)
        start = max(0, size - ROLLOUT_TAIL_BYTES)
        stream.seek(start)
        data = stream.read()
    if not data.endswith(b"\n"):
        return False
    lines = data.split(b"\n")
    if start:
        lines = lines[1:]
    lines = [line for line in lines if line.strip()]
    if not lines:
        return False
    try:
        record = json.loads(lines[-1].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(record, dict):
        return False
    payload = record.get("payload")
    return record.get("type") == "event_msg" and isinstance(payload, dict) and payload.get("type") in CODEX_IDLE_EVENTS


def install_gate(host: str) -> RefreshError | None:
    """Why an install on `host` must wait, or None. A Codex update deletes the old install, so no Codex turn may run."""
    if host != "codex":
        return None
    if any(name in os.environ for name in CODEX_TURN_ENV):
        return RefreshError("update_deferred_active_session", "This command runs inside a Codex turn.")
    unknown = RefreshError("update_deferred_unknown_session_state", "The Codex session state could not be read.")
    sessions = codex_home() / "sessions"
    errors: list[OSError] = []
    recent: list[Path] = []
    try:
        if not sessions.exists():
            return None
        for folder, _, names in os.walk(sessions, onerror=errors.append):
            for name in names:
                if not (name.startswith("rollout-") and name.endswith(".jsonl")):
                    continue
                path = Path(folder) / name
                try:
                    modified = path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if time.time() - modified <= ROLLOUT_RECENT_SECONDS:
                    recent.append(path)
        if errors:
            return unknown
        for path in recent:
            if not rollout_idle(path):
                return RefreshError("codex_turn_in_progress", "A recent Codex session has a turn in progress.")
    except Exception:
        return unknown
    return None


def recovery_command(root: str | None, companions: Sequence[str] = ()) -> str:
    current = Path(__file__).resolve()
    try:
        relative = current.relative_to(PLUGIN_ROOT)
    except ValueError:
        relative = current.name
    candidate = Path(root) / relative if root else current
    script = candidate if candidate.is_file() else current
    also = "".join(f" --also {shlex.quote(plugin_id)}" for plugin_id in companions)
    return f"python3 {shlex.quote(str(script))} update{also} --json"


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


def run_install(host: str, plugin_id: str, context: dict) -> RefreshError | None:
    """Refresh the plugin's marketplace at most once per run, then update the plugin.

    The host gate is checked again right before each install command. A gate that fails is returned instead of
    raised and stays in `context`, so no further install runs on that host in this run.
    """
    marketplaces = context.setdefault("marketplaces_updated", {})

    def blocked() -> RefreshError | None:
        if not context.get("blocked"):
            context["blocked"] = install_gate(host)
        return context["blocked"]

    marketplace = plugin_id.partition("@")[2]
    cli = executable(host)
    if marketplace in marketplaces:
        if marketplaces[marketplace]:
            raise marketplaces[marketplace]
    else:
        if blocked():
            return context["blocked"]
        marketplaces[marketplace] = None
        try:
            run([cli, "plugin", "marketplace", "update" if host == "claude" else "upgrade", marketplace], timeout=180)
        except RefreshError as error:
            marketplaces[marketplace] = error
            raise
    if blocked():
        return context["blocked"]
    run([cli, "plugin", "update" if host == "claude" else "add", plugin_id], timeout=180)
    return None


def local_source(host: str, plugin_id: str, item: object, context: dict) -> dict | None:
    """{version, note?} when the plugin loads from a local source, which is never installed; None otherwise."""
    name, _, marketplace = plugin_id.partition("@")
    if not isinstance(item, dict):
        return None
    if host == "claude":
        entry = claude_marketplace(context, marketplace)
        if entry and entry.get("source") in ("directory", "file"):
            return {"version": folder_version(entry, name), "note": "loads_from_folder_on_reload"}
        return None
    source = item.get("marketplaceSource")
    if (source.get("sourceType") if isinstance(source, dict) else None) != "git":
        return {"version": item.get("version") if isinstance(item.get("version"), str) else None}
    return None


def update_host(host: str, context: dict | None = None) -> dict:
    context = {} if context is None else context
    before = installed(host)
    before_snapshot = validate_install(host, before)
    local = local_source(host, PLUGIN_ID, before.get("item"), context)
    if local:
        version = local["version"] or before["version"]
        result = {
            "before_version": version,
            "after_version": version,
            "root": before["root"],
            "previous_root": before["root"],
            "digest": before_snapshot["digest"],
            "instructions_changed": False,
            "warnings": [],
            "local_source": True,
        }
        if local.get("note"):
            result["note"] = local["note"]
        return result
    blocked = run_install(host, PLUGIN_ID, context)
    if blocked:
        blocked.details.update(root=before["root"], recovery_command=recovery_command(before["root"], context.get("ids", ())))
        raise blocked
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
        result["warnings"].append(dict(HOOKS_TRUST_WARNING))
    return result


def companion_entries(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        return [part for part in re.split(r"[,\s]+", value) if part]
    return list(value) if isinstance(value, list) else [value]


def companion_ids(also: Sequence[str]) -> tuple[list[str], dict]:
    """The companion plugin IDs: --also, else the environment variable, else the saved Claude option."""
    extra: dict = {}
    entries = list(also) or companion_entries(os.environ.get(COMPANION_ENV))
    if not entries:
        saved, problem = load_plugin_script("plugin_toggles").saved_options(("refresh_plugins",))
        if problem:
            extra["notice"] = f"Ignored the saved refresh_plugins option: {problem}."
        entries = companion_entries(saved.get("refresh_plugins"))
    ids: list[str] = []
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, str) or not COMPANION_ID.fullmatch(entry):
            raise RefreshError("plugin_id_invalid", "A refresh plugin entry is not a valid plugin@marketplace ID.", {"entry": index})
        if entry != PLUGIN_ID and entry not in ids:
            ids.append(entry)
    if len(ids) > COMPANION_LIMIT:
        extra["companions_dropped"] = len(ids) - COMPANION_LIMIT
    return ids[:COMPANION_LIMIT], extra


def claude_marketplace(context: dict, marketplace: str) -> dict | None:
    if "marketplaces" not in context:
        payload = run_json([executable("claude"), "plugin", "marketplace", "list", "--json"])
        context["marketplaces"] = [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
    entries = [item for item in context["marketplaces"] if item.get("name") == marketplace]
    return entries[0] if len(entries) == 1 else None


def folder_version(entry: dict, name: str) -> str | None:
    """The version of a plugin that loads from a local marketplace folder, or None when any lookup step fails."""
    location = entry.get("installLocation")
    if not isinstance(location, str) or not location:
        return None
    base = Path(location)
    try:
        catalog = json.loads((base / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        source = next(item["source"] for item in catalog["plugins"] if isinstance(item, dict) and item.get("name") == name)
        if not isinstance(source, str):
            return None
        folder = base / source
        if not inside(base, folder):
            return None
        version = json.loads((folder / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, StopIteration):
        return None
    return version if isinstance(version, str) and version else None


def describe_plugin(host: str, plugin_id: str, context: dict) -> dict | None:
    """The plugin's listing on `host` as {version, root, local, note?}, or None unless it is installed and enabled exactly once."""
    name, _, marketplace = plugin_id.partition("@")
    payload = run_json([executable(host), "plugin", "list", "--json"])
    if host == "claude":
        items = [item for item in payload if isinstance(item, dict) and item.get("id") == plugin_id] if isinstance(payload, list) else []
    else:
        listed = payload.get("installed") if isinstance(payload, dict) else None
        items = [item for item in listed if isinstance(item, dict) and item.get("pluginId") == plugin_id] if isinstance(listed, list) else []
    if len(items) != 1 or items[0].get("enabled") is not True:
        return None
    item = items[0]
    local = local_source(host, plugin_id, item, context)
    if local:
        return {"root": None, "local": True, **local}
    if host == "claude":
        root = Path(str(item.get("installPath") or ""))
    else:
        root = codex_home() / "plugins" / "cache" / marketplace / name / str(item.get("version"))
    version = item.get("version")
    if not isinstance(version, str) or not version or not root.is_absolute() or not root.is_dir():
        raise RefreshError(f"{host}_root_missing", f"The installed {host} plugin directory is unavailable.")
    return {"version": version, "root": root.resolve(), "local": False}


def hooks_digest(host: str, root: Path) -> str | None:
    """Hash every hook file the installed plugin loads, in load order; None when it has none or they cannot be read."""
    manifest_path = root / (".claude-plugin/plugin.json" if host == "claude" else ".codex-plugin/plugin.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        hooks_bytes, _ = check_hooks(host, root, strict=False, manifest=manifest)
    except (OSError, UnicodeError, ValueError, RefreshError):
        return None
    return hashlib.sha256(hooks_bytes).hexdigest() if hooks_bytes is not None else None


def validate_companion(host: str, plugin_id: str, found: dict) -> str | None:
    """Check the installed manifest and every plugin-root hook target; return the hook files digest, None without one."""
    root = found["root"]
    manifest = read_manifest(host, root, plugin_id.partition("@")[0], found["version"])
    hooks_bytes, _ = check_hooks(host, root, strict=False, manifest=manifest)
    return hashlib.sha256(hooks_bytes).hexdigest() if hooks_bytes is not None else None


def refresh_companion(host: str, plugin_id: str, update: bool, context: dict) -> dict:
    result = {"plugin": plugin_id, "status": "error", "before_version": None, "after_version": None, "warnings": []}
    try:
        found = describe_plugin(host, plugin_id, context)
        if found is None:
            result["status"] = "not_installed"
            return result
        result["before_version"] = result["after_version"] = found["version"]
        if found["local"]:
            result["status"] = "local_source"
            if found.get("note"):
                result["note"] = found["note"]
            return result
        before_hooks = hooks_digest(host, found["root"])
        if update:
            blocked = run_install(host, plugin_id, context)
            if blocked:
                result.update(status="deferred", code=blocked.code, message=blocked.message)
                return result
            found = describe_plugin(host, plugin_id, context)
            if found is None or found["local"]:
                raise RefreshError(f"{host}_plugin_missing", f"The {host} plugin is not installed and enabled exactly once after the update.")
            result["after_version"] = found["version"]
        after_hooks = validate_companion(host, plugin_id, found)
        result["status"] = "updated" if result["after_version"] != result["before_version"] else "current"
        if update and host == "codex" and before_hooks != after_hooks:
            result["warnings"].append(dict(HOOKS_TRUST_WARNING))
    except RefreshError as error:
        result.update(status="error", code=error.code, message=error.message)
    except (OSError, ValueError):
        result.update(status="error", code="plugin_check_failed", message=f"A {host} plugin file could not be checked.")
    return result


def host_failure(error: RefreshError) -> dict:
    entry = {"error": {"code": error.code, "message": error.message}}
    for key in ("root", "recovery_command"):
        if key in error.details:
            entry[key] = error.details[key]
    return entry


def refresh_report(run_id: str, hosts: dict[str, dict], extra: dict) -> dict:
    save_json(run_path(run_id), {"run_id": run_id, "created_at": now(), "hosts": hosts, "sessions": {}})
    failed = any("error" in value or any(item["status"] == "error" for item in value["plugins"]) for value in hosts.values())
    return {"ok": not failed, "run_id": run_id, "script": continuation_script(hosts), "hosts": hosts, **extra}


def command_update(also: Sequence[str] = ()) -> dict:
    ids, extra = companion_ids(also)
    run_id = uuid.uuid4().hex
    hosts: dict[str, dict] = {}
    for host in HOSTS:
        context: dict = {"ids": ids}
        try:
            hosts[host] = update_host(host, context)
        except RefreshError as error:
            hosts[host] = host_failure(error)
        except (OSError, ValueError):
            hosts[host] = host_failure(RefreshError("plugin_check_failed", f"A {host} plugin file could not be checked."))
        hosts[host]["plugins"] = [refresh_companion(host, plugin_id, True, context) for plugin_id in ids]
    return refresh_report(run_id, hosts, extra)


def command_apply_installed(also: Sequence[str] = ()) -> dict:
    ids, extra = companion_ids(also)
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
            hosts[host] = host_failure(error)
        except (OSError, ValueError):
            hosts[host] = host_failure(RefreshError("plugin_check_failed", f"A {host} plugin file could not be checked."))
        context: dict = {}
        hosts[host]["plugins"] = [refresh_companion(host, plugin_id, False, context) for plugin_id in ids]
    return refresh_report(run_id, hosts, extra)


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

    @staticmethod
    def wait_result(stdout: str) -> bool:
        """Read an idle wait: True when satisfied, False when it timed out, an error for anything else."""
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as error:
            raise RefreshError("invalid_json", "Orca returned unreadable JSON for a wait.") from error
        if isinstance(payload, dict) and payload.get("ok") is False:
            error = payload.get("error")
            if isinstance(error, dict) and error.get("code") == "timeout":
                return False
            raise RefreshError("orca_rejected", "Orca could not report whether the terminal is idle.")
        wait = payload.get("result", {}).get("wait") if isinstance(payload, dict) else None
        return isinstance(wait, dict) and wait.get("satisfied") is True

    def idle(self, handle: str) -> bool:
        result = run([*self.command, "terminal", "wait", "--terminal", handle, "--for", "tui-idle", "--timeout-ms", "500", "--json"], timeout=15, check=False)
        return self.wait_result(result.stdout)

    def wait_idle(self, handle: str, timeout_ms: float, track: Callable[[subprocess.Popen], None] | None = None) -> bool:
        """Block until Orca reports the agent idle, which acts as the completion callback; False when the wait times out."""
        argv = [*self.command, "terminal", "wait", "--terminal", handle, "--for", "tui-idle", "--timeout-ms", str(max(1, int(timeout_ms))), "--json"]
        try:
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except OSError as error:
            raise RefreshError("orca_wait_failed", "Orca could not start an idle wait.") from error
        if track:
            track(process)
        try:
            stdout, _ = process.communicate(timeout=timeout_ms / 1000 + 30)
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.communicate()
            raise RefreshError("orca_wait_hung", "Orca did not finish an idle wait.") from error
        return self.wait_result(stdout)

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


def marker_host(terminal: dict) -> str | None:
    """The host this plugin's session marker names for a terminal that Orca recorded no agentIdentity for."""
    handle = terminal.get("handle")
    if terminal.get("agentIdentity") or not isinstance(handle, str):
        return None
    host = (read_marker(handle) or {}).get("host")
    return host if host in ("claude", "codex") else None


def terminal_host(orca: Orca, terminal: dict) -> str | None:
    """Orca's agentIdentity, or, when Orca recorded none, the marker's host while that host's composer still ends the
    screen. A marker outlives the session, so a shell left in the terminal never matches."""
    host = marker_host(terminal)
    if host is None:
        return agent_host(terminal)
    try:
        lines, _ = orca.screen(terminal["handle"])
    except RefreshError:
        return None
    return host if screen_host(lines) == host else None


def screen_host(lines: Sequence[str]) -> str | None:
    """The agent whose composer ends the screen, followed only by its indented footer."""
    def footer_only(rest: Sequence[str]) -> bool:
        return all(not line.strip() or line[:1].isspace() for line in rest)

    bounds = composer_bounds(lines)
    claude = bounds is not None and footer_only(lines[bounds[1] + 1:])
    prompts = [index for index, line in enumerate(lines) if line.strip().startswith("›")]
    codex = bool(prompts) and input_state("codex", lines) != "unknown" and footer_only(lines[prompts[-1] + 1:])
    return None if claude == codex else "claude" if claude else "codex"


def opening_rule(line: str) -> bool:
    """Claude Code may print the session name at the end of the composer's top rule."""
    return bool(SEPARATOR.match(line) or TITLED_SEPARATOR.match(line))


def composer_bounds(lines: Sequence[str]) -> tuple[int, int] | None:
    """Find the composer, keeping indented draft rules inside its body."""
    for closing in range(len(lines) - 1, 0, -1):
        if not SEPARATOR.match(lines[closing]):
            continue
        bounds = None
        for opening in range(closing - 1, -1, -1):
            if not opening_rule(lines[opening]):
                continue
            if closing - opening >= 2 and lines[opening + 1].strip().startswith("❯"):
                bounds = opening, closing
                # Prefer the enclosing composer over indented rules in its draft.
                if not lines[opening][:1].isspace():
                    break
            elif bounds is not None and not lines[opening][:1].isspace():
                break
        return bounds
    return None


def input_state(host: str, lines: Sequence[str]) -> str:
    """Return `empty`, `text`, or `unknown` for the composer line of an agent TUI screen."""
    if host == "claude":
        bounds = composer_bounds(lines)
        if bounds is not None:
            opening, closing = bounds
            body = [line.strip() for line in lines[opening + 1:closing]]
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
        host = terminal_host(orca, terminal)
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


def terminal_gone(entry: dict, live: dict[str, dict]) -> bool:
    """True when the session's terminal left Orca's list or no longer runs the entry's agent host."""
    terminal = live.get(entry["handle"])
    return terminal is None or (marker_host(terminal) or agent_host(terminal)) != entry["host"]


def probe_left_input_clean(orca: Orca, handle: str, draft: str) -> bool:
    """True when the draft is back to its pre-probe value or empty, so no probe character of ours remains."""
    try:
        after = settle(lambda: orca.draft(handle), lambda value: value == draft or not (isinstance(value, str) and value.strip()), time.sleep, PROBE_RECHECK_SECONDS)
    except RefreshError:
        return False
    return after == draft or not (isinstance(after, str) and after.strip())


def ready(orca: Orca, entry: dict, live: dict[str, dict]) -> tuple[str | None, list[str]]:
    """Return (None, screen) when a command can be sent safely, otherwise the reason to wait."""
    if terminal_gone(entry, live):
        return "terminal_gone", []
    terminal = live[entry["handle"]]
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
        retries = entry.get("probe_retries") or 0
        if retries < PROBE_RETRIES and probe_left_input_clean(orca, entry["handle"], draft):
            entry["probe_retries"] = retries + 1
            entry.pop("draft_seen", None)
            return "input_settling", lines
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
    bounds = composer_bounds(lines)
    if bounds is None:
        return False
    above = lines[:bounds[0]]
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


def drive(orca: Orca, sessions: list[dict], state: dict, deadline: float, sleep: Callable[[float], None] = time.sleep, expire: str = "skipped") -> None:
    """Send commands until `deadline`, then stop starting new ones and keep verifying the ones already sent.

    A session still pending at the deadline takes the `expire` status: `skipped`, or `deferred` for the helper.
    """
    while True:
        if time.time() >= deadline:
            for entry in sessions:
                if entry["status"] == "pending":
                    entry.update(status=expire, detail=entry.get("detail") or "deadline_reached")
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
                entry.update(status=expire, detail=entry.get("detail") or "deadline_reached")
                continue
            try:
                step(orca, entry, state["hosts"][entry["host"]], live)
            except RefreshError as error:
                entry.update(status="failed", detail=error.code, actions=[])
        sleep(POLL_SECONDS)


class IdleWaiters:
    """One background Orca idle wait per busy session; the helper acts when a wait reports the session idle."""

    def __init__(self, orca: Orca) -> None:
        self.orca = orca
        self.lock = threading.Lock()
        self.results: dict[str, bool] = {}
        self.threads: dict[str, threading.Thread] = {}
        self.failed: set[str] = set()
        self.processes: list[subprocess.Popen] = []
        self.by_handle: dict[str, list[subprocess.Popen]] = {}
        self.cancelled: set[str] = set()
        self.stopping = False

    def track(self, process: subprocess.Popen, handle: str | None = None) -> None:
        with self.lock:
            self.processes.append(process)
            if handle is not None:
                self.by_handle.setdefault(handle, []).append(process)
            stopping = self.stopping or handle in self.cancelled
        if stopping:
            self.end(process)

    def cancel(self, handle: str) -> None:
        """End one session's idle wait, including a process that registers after this call."""
        with self.lock:
            self.cancelled.add(handle)
            self.results.pop(handle, None)
            processes = list(self.by_handle.get(handle, []))
        for process in processes:
            self.end(process)

    @staticmethod
    def end(process: subprocess.Popen) -> None:
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    def start(self, handle: str, deadline: float) -> None:
        if self.stopping or self.waiting(handle):
            return

        def wait() -> None:
            try:
                idle = self.orca.wait_idle(handle, max(1.0, deadline - time.time()) * 1000, lambda process: self.track(process, handle))
            except (RefreshError, OSError):
                with self.lock:
                    self.failed.add(handle)
                return
            with self.lock:
                self.results[handle] = idle

        with self.lock:
            self.results.pop(handle, None)
        thread = threading.Thread(target=wait, daemon=True)
        self.threads[handle] = thread
        thread.start()

    def waiting(self, handle: str) -> bool:
        thread = self.threads.get(handle)
        return bool(thread and thread.is_alive())

    def take(self, handle: str) -> bool | None:
        with self.lock:
            return self.results.pop(handle, None)

    def stop(self) -> None:
        """Kill every Orca wait, including one registered while stopping, so the helper leaves no child process behind."""
        with self.lock:
            self.stopping = True
            processes = list(self.processes)
        for process in processes:
            self.end(process)
        for thread in list(self.threads.values()):
            thread.join(timeout=5)


def install_current(host: str, target: dict, cache: dict[str, tuple[float, bool]]) -> bool:
    """True while the installed plugin still matches the run's target; rechecked at most every INSTALL_CHECK_SECONDS."""
    checked = cache.get(host)
    if checked and time.time() - checked[0] < INSTALL_CHECK_SECONDS:
        return checked[1]
    try:
        current = installed(host)
        snapshot = validate_install(host, current)
        same = current["root"] == target.get("root") and snapshot["digest"] == target.get("digest")
    except RefreshError:
        same = False
    cache[host] = (time.time(), same)
    return same


def still_needed(entry: dict, state: dict, cache: dict[str, tuple[float, bool]]) -> None:
    """Before a deferred send, stop on a changed install and drop actions the session no longer needs."""
    host = entry["host"]
    target = state["hosts"][host]
    if not install_current(host, target, cache):
        entry.update(status="skipped", detail="install_changed", actions=[])
        return
    marker = read_marker(entry["handle"])
    written = parse_time((marker or {}).get("written_at")) or 0.0
    if marker and written >= entry.get("deferred_at", float("inf")) and compact_reason(host, marker, target, "auto") is None:
        entry.update(status="done", detail="already_current", actions=[])
        return
    if "compact" in entry["actions"] and compact_reason(host, marker, target, state.get("compact_mode", "auto")) is None:
        entry["actions"].remove("compact")
    if not entry["actions"]:
        entry.update(status="done", detail="already_current")


def follow_up(orca: Orca, entries: list[dict], state: dict, sleep: Callable[[float], None] = time.sleep, waiters: IdleWaiters | None = None,
              progress: Callable[[list[dict]], None] | None = None) -> None:
    """Apply deferred sessions when Orca reports them idle, each before its own deadline, then end every wait.

    `progress` receives the entries that reached a final status since its last call.
    """
    waiters = waiters or IdleWaiters(orca)
    cache: dict[str, tuple[float, bool]] = {}
    reported: set[str] = set()

    def report() -> None:
        finished = [entry for entry in entries if entry["status"] in FINAL_STATUSES and entry["handle"] not in reported]
        if finished and progress:
            reported.update(entry["handle"] for entry in finished)
            progress(finished)

    try:
        while True:
            active = [entry for entry in entries if entry["status"] in {"pending", "sent"}]
            if not active:
                return
            try:
                live = {item.get("handle"): item for item in orca.terminals()}
            except RefreshError:
                live = None
            for entry in active:
                report()
                if entry["status"] == "pending":
                    if live is not None and terminal_gone(entry, live):
                        waiters.cancel(entry["handle"])
                        entry.update(status="skipped", detail="terminal_gone", actions=[])
                        continue
                    if time.time() >= entry["deadline"]:
                        busy = entry.get("detail") in (None, "busy", "waiting_for_idle", "deadline_reached")
                        entry.update(status="skipped", detail="not_idle_before_deadline" if busy else entry["detail"], actions=[])
                        continue
                    if live is None:
                        entry["detail"] = "terminal_list_unavailable"
                        continue
                    handle = entry["handle"]
                    if handle not in waiters.failed and entry.get("detail") in ("busy", "waiting_for_idle", "deadline_reached"):
                        idle = waiters.take(handle)
                        if idle is None:
                            waiters.start(handle, entry["deadline"])
                            entry["detail"] = "waiting_for_idle"
                            continue
                        if not idle:
                            continue
                        sleep(IDLE_CONFIRM_SECONDS)
                    still_needed(entry, state, cache)
                    if entry["status"] != "pending":
                        continue
                    if time.time() >= entry["deadline"]:
                        entry.update(status="skipped", detail="not_idle_before_deadline", actions=[])
                        continue
                try:
                    step(orca, entry, state["hosts"][entry["host"]], live)
                except RefreshError as error:
                    entry.update(status="failed", detail=error.code, actions=[])
            report()
            sleep(POLL_SECONDS)
    finally:
        waiters.stop()


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
    if status == "deferred":
        helper = state.get("helper") or {}
        if any(item.get("handle") == handle for item in state.get("follow_up", [])) and (alive(helper.get("pid")) or state.get("helper_finished_at")):
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
                entry.update(status=previous, detail="already_handled_in_this_run", actions=[], handled=True)
        others = [entry for entry in sessions if not entry["initiator"] and not entry.get("handled")]
        drive(orca, others, state, time.time() + seconds, expire="deferred")
        own = next((entry for entry in sessions if entry["initiator"] and entry["status"] == "pending"), None)
        deferred = [entry for entry in others if entry["status"] == "deferred"]
        helper = state.get("helper") or {}
        helper_waiting = alive(helper.get("pid")) and not state.get("helper_finished_at")
        initiator = next((entry for entry in sessions if entry["initiator"]), None)
        state["initiator"] = {"handle": initiator["handle"], "host": initiator["host"]} if initiator else None
        state["compact_mode"] = mode
        if own or deferred:
            handed = time.time()
            items = [
                {key: entry.get(key) for key in ("handle", "host", "actions", "title", "worktree", "compact_reason", "detail", "probe_retries")} | {"deferred_at": handed}
                for entry in deferred
            ]
            handed_off = True
            if helper_waiting:
                pid = helper["pid"]
                state["follow_up"] = [*state.get("follow_up", []), *items]
            else:
                try:
                    pid = spawn(run_id)
                except OSError:
                    handed_off = False
                    if own:
                        own.update(status="failed", detail="helper_start_failed", actions=[])
                    for entry in deferred:
                        entry.update(status="skipped", detail="helper_start_failed", actions=[])
                else:
                    state["helper"] = {"pid": pid, "started_at": now()}
                    state.pop("helper_finished_at", None)
                    state["follow_up"] = items
                    if not own:
                        state.pop("self", None)
            if handed_off and own:
                own.update(status="queued_after_turn", detail="waits_for_this_turn_to_end")
                state["self"] = {key: own[key] for key in ("handle", "host", "actions", "title", "worktree")}
                state["self"].update(compact_reason=own.get("compact_reason"), helper_pid=pid, helper_started_at=now(), deferred_at=handed)
                state.pop("self_finished_at", None)
        state["sessions"] = {**state.get("sessions", {}), **{entry["handle"]: public(entry) for entry in sessions}}
        state["applied_at"] = now()
        save_json(run_path(run_id), state)
    summary = {status: sum(1 for entry in sessions if entry["status"] == status) for status in {entry["status"] for entry in sessions}}
    return {"ok": all(entry["status"] in {"done", "queued_after_turn", "deferred"} for entry in sessions), "run_id": run_id, "summary": summary, "sessions": [public(entry) for entry in sessions]}


def notify(orca: Orca, entry: dict, run_id: str, sleep: Callable[[float], None]) -> str:
    message = f"Plugin refresh run {run_id} finished. Run `{status_command(run_id)}` and report every session, including any that were not refreshed."
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


def command_self_apply(run_id: str, sleep: Callable[[float], None] = time.sleep, waiters: IdleWaiters | None = None) -> int:
    """The one detached helper: finish deferred sessions and this session, then send one result notice and exit."""
    with exclusive("sessions", wait_seconds=SELF_WAIT_SECONDS):
        state = load_run(run_id)
        own = state.get("self")
        follow = [item for item in state.get("follow_up", []) if isinstance(item, dict)]
        if not isinstance(own, dict) and not follow:
            return 0
        start = time.time()
        entries = [
            {**item, "actions": list(item["actions"]), "status": "pending", "initiator": False,
             "detail": item.get("detail") or "busy", "deadline": item.get("deferred_at", start) + FOLLOW_UP_SECONDS}
            for item in follow
        ]
        own_entry = None
        if isinstance(own, dict):
            own_entry = {**own, "actions": list(own["actions"]), "status": "pending", "initiator": True, "detail": None, "deadline": start + SELF_WAIT_SECONDS}
            entries.append(own_entry)
        orca = Orca()

        def record(finished: list[dict]) -> None:
            try:
                saved = load_run(run_id)
                views = {entry["handle"]: public(entry) for entry in finished}
                sessions = saved.setdefault("sessions", {})
                if any(sessions.get(handle) != view for handle, view in views.items()):
                    sessions.update(views)
                    save_json(run_path(run_id), saved)
            except (RefreshError, OSError):
                pass

        follow_up(orca, entries, state, sleep=sleep, waiters=waiters, progress=record)
        state = load_run(run_id)
        for entry in entries:
            state["sessions"][entry["handle"]] = public(entry)
        finished = now()
        state["helper_finished_at"] = finished
        if own_entry:
            state["self_finished_at"] = finished
        state["self_notification"] = "pending"
        save_json(run_path(run_id), state)
        if own_entry:
            notification = notify(orca, own_entry, run_id, sleep) if own_entry["status"] in {"done", "failed"} else "not_sent:session_skipped"
        elif isinstance(state.get("initiator"), dict):
            notification = notify(orca, dict(state["initiator"]), run_id, sleep)
        else:
            notification = "not_sent:no_orca_initiator"
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
        "not_refreshed": [item for item in state.get("sessions", {}).values() if item.get("status") in {"skipped", "failed", "blocked"}],
        "helper_finished_at": state.get("helper_finished_at"),
        "self_finished_at": state.get("self_finished_at"),
        "self_notification": state.get("self_notification"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("update", "apply-installed"):
        sub = commands.add_parser(name)
        sub.add_argument("--also", action="append", default=[], metavar="PLUGIN@MARKETPLACE")
        sub.add_argument("--json", action="store_true")
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
            output = command_update(args.also)
        elif args.command == "apply-installed":
            output = command_apply_installed(args.also)
        elif args.command == "plan":
            output = command_plan(args.run_id, args.compact, args.terminal)
        elif args.command == "apply":
            output = command_apply(args.run_id, args.compact, args.terminal, max(5, args.timeout_seconds))
        else:
            output = command_status(args.run_id)
    except RefreshError as error:
        output = {"ok": False, "error": {"code": error.code, "message": error.message}}
        if "entry" in error.details:
            output = {"ok": False, "status": "error", "code": error.code, "entry": error.details["entry"], "error": output["error"]}
    print(json.dumps(output, ensure_ascii=False, indent=1))
    return 0 if output.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
