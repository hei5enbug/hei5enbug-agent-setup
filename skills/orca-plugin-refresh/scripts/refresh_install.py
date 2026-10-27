from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import time
from pathlib import Path

import refresh_core as core
from refresh_core import MARKETPLACE, PLUGIN, PLUGIN_ID, SESSION_CONTEXT, RefreshError, run_json


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
CODEX_TURN_ENV = ("CODEX_THREAD_ID", "CODEX_SESSION_ID")
CODEX_IDLE_EVENTS = {"task_complete", "turn_aborted"}
ROLLOUT_RECENT_SECONDS = 30 * 60
ROLLOUT_TAIL_BYTES = 64 * 1024
HOOKS_TRUST_WARNING = {"code": "codex_hooks_need_trust", "message": "The plugin's hooks or files changed, which resets Codex hook trust; review and trust the plugin hooks in Codex /hooks, or they are skipped."}
BUNDLE_SKIPPED_DIRS = frozenset({"__pycache__", ".venv"})


def installed(host: str) -> dict:
    if host == "claude":
        payload = run_json([core.executable("claude"), "plugin", "list", "--json"])
        matches = [item for item in payload if isinstance(item, dict) and item.get("id") == PLUGIN_ID] if isinstance(payload, list) else []
        if len(matches) != 1 or matches[0].get("enabled") is not True:
            raise RefreshError("claude_plugin_missing", "The Claude Code plugin is not installed and enabled exactly once.")
        root = Path(str(matches[0].get("installPath") or ""))
    else:
        payload = run_json([core.executable("codex"), "plugin", "list", "--json"])
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
    cli = core.executable(host)
    if marketplace in marketplaces:
        if marketplaces[marketplace]:
            raise marketplaces[marketplace]
    else:
        if blocked():
            return context["blocked"]
        marketplaces[marketplace] = None
        try:
            core.run([cli, "plugin", "marketplace", "update" if host == "claude" else "upgrade", marketplace], timeout=180)
        except RefreshError as error:
            marketplaces[marketplace] = error
            raise
    if blocked():
        return context["blocked"]
    core.run([cli, "plugin", "update" if host == "claude" else "add", plugin_id], timeout=180)
    return None


def hooks_digest(host: str, root: Path) -> str | None:
    """Hash every hook file the installed plugin loads, in load order; None when it has none or they cannot be read."""
    manifest_path = root / (".claude-plugin/plugin.json" if host == "claude" else ".codex-plugin/plugin.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        hooks_bytes, _ = check_hooks(host, root, strict=False, manifest=manifest)
    except (OSError, UnicodeError, ValueError, RefreshError):
        return None
    return hashlib.sha256(hooks_bytes).hexdigest() if hooks_bytes is not None else None


def bundle_digest(root: Path) -> str | None:
    """Hash every file of an installed plugin the way Codex scopes hook trust, skipping bytecode, virtual environments,
    and package metadata; None when the folder cannot be read."""
    digest = hashlib.sha256()
    try:
        for path in sorted(Path(root).rglob("*")):
            relative = path.relative_to(root)
            if (set(relative.parts) & BUNDLE_SKIPPED_DIRS or any(part.endswith(".egg-info") for part in relative.parts)
                    or path.suffix == ".pyc" or not path.is_file()):
                continue
            digest.update(relative.as_posix().encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    except OSError:
        return None
    return digest.hexdigest()


def codex_trust_reset(hooks_before: str | None, hooks_after: str | None, bundle_before: str | None,
                      bundle_after: str | None) -> bool:
    """Whether an install leaves Codex hook trust to redo: the hook definitions changed, or a plugin that has hooks
    changed any file, since Codex ties trust to the whole plugin."""
    return hooks_before != hooks_after or (hooks_after is not None and (bundle_before != bundle_after or bundle_after is None))
