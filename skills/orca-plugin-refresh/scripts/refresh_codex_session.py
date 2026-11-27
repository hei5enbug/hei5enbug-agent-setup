from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Mapping

from refresh_core import HANDLE, SESSION_CONTEXT, RefreshError
from refresh_install import CODEX_TURN_ENV
from refresh_process import ProcessOs, find_session_process

THREAD_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
OPTION = re.compile(r"^\s{2,}((?:-[\w?],\s+)?--[\w-]+)(?:\s+(\[[^]]+\]|<[^>]+>))?")


def rollout_identity(marker: dict | None) -> tuple[str | None, bool]:
    path = (marker or {}).get("transcript_path")
    if not isinstance(path, str):
        return None, False
    identity = None
    try:
        with Path(path).open(encoding="utf-8") as stream:
            for line in stream:
                record = json.loads(line)
                payload = record.get("payload", {})
                if record.get("type") == "session_meta":
                    value = payload.get("id")
                    identity = value if isinstance(value, str) and THREAD_ID.fullmatch(value) else None
                if record.get("type") == "turn_context" or (record.get("type") == "event_msg" and payload.get("type") == "task_started"):
                    return identity, True
    except (OSError, ValueError, AttributeError):
        return None, False
    return identity, False


def replaced_before_start(handle: str, marker: dict | None, target: dict, system: ProcessOs | None = None) -> bool | None:
    times = [item.get("installed_at") for item in [target, *target.get("plugins", [])]]
    times = [value for value in times if isinstance(value, (int, float))]
    if not times or not rollout_identity(marker)[1]:
        return False
    system = system or ProcessOs()
    try:
        process = find_session_process(handle, system, "codex")
    except RefreshError:
        return None
    started = system.started_at(process.pid) if process else None
    return any(started < installed for installed in times) if started is not None else None


def resume_arguments(argv: tuple[str, ...], help_text: str | None) -> list[str] | None:
    table = {}
    for line in (help_text or "").splitlines():
        match = OPTION.match(line)
        if match:
            for option in match[1].split(", "):
                table[option.strip()] = bool(match[2])
    if not table:
        return None
    kept = []
    items = list(argv[1:])
    index = 0
    while index < len(items):
        token = items[index]
        index += 1
        if token == "--":
            break
        if not token.startswith("-"):
            if token in {"exec", "fork", "app-server", "mcp-server"}:
                return None
            continue
        name, separator, _ = token.partition("=")
        if name in {"--last", "--all"}:
            continue
        if name not in table:
            return None
        values = []
        if table[name] and not separator:
            if index >= len(items):
                return None
            values = [items[index]]
            index += 1
        kept.extend([token, *values])
    return kept


def resume_line(executable: str, config_dir: str | None, arguments: list[str], thread_id: str) -> str:
    prefix = [f"CODEX_HOME={shlex.quote(config_dir)}"] if config_dir else []
    return " ".join([*prefix, shlex.quote(executable), "resume", shlex.quote(thread_id),
                     *(shlex.quote(item) for item in arguments)])


ROLLOUT_META_BYTES = 1024 * 1024


def rollout_cwd(path: str) -> str | None:
    """The working folder in a rollout's first record; no prompt text is read."""
    try:
        with Path(path).open("rb") as stream:
            record = json.loads(stream.readline(ROLLOUT_META_BYTES))
    except (OSError, ValueError):
        return None
    payload = record.get("payload") if isinstance(record, dict) else None
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    return cwd if isinstance(cwd, str) else None


def marker_handles() -> dict[str, str]:
    """Each Codex session marker's rollout path mapped to the Orca terminal handle that wrote it."""
    directory = SESSION_CONTEXT.marker_directory()
    found: dict[str, str] = {}
    if directory is None:
        return found
    try:
        files = sorted(directory.glob("*.json"))
    except OSError:
        return found
    for file in files:
        try:
            marker = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        path = marker.get("transcript_path") if isinstance(marker, dict) else None
        if isinstance(marker, dict) and marker.get("host") == "codex" and isinstance(path, str) and HANDLE.fullmatch(file.stem):
            found[path] = file.stem
    return found


def gate_sessions(error: RefreshError, environ: Mapping[str, str] = os.environ) -> list[dict]:
    """The Codex sessions an install gate names, one per busy rollout, matched to an Orca terminal through the Codex
    markers' transcript paths. A rollout no marker names is `outside_orca`. The session running the command, when the
    gate is `update_deferred_active_session`, comes first and is marked `own`."""
    rollouts = [path for path in error.details.get("rollouts", []) if isinstance(path, str)]
    markers = marker_handles()
    sessions: list[dict] = []
    own_rollout = None
    if error.code == "update_deferred_active_session":
        handle = environ.get("ORCA_TERMINAL_HANDLE")
        handle = handle if isinstance(handle, str) and HANDLE.fullmatch(handle) else None
        thread = next((environ[name] for name in CODEX_TURN_ENV if environ.get(name)), None)
        own_rollout = next((path for path in rollouts if thread and Path(path).name.endswith(f"-{thread}.jsonl")), None)
        own_rollout = own_rollout or next((path for path, owner in markers.items() if handle and owner == handle), None)
        sessions.append({"rollout": own_rollout, "handle": handle, "outside_orca": handle is None, "own": True,
                         "worktree": rollout_cwd(own_rollout) if own_rollout else None})
    for path in rollouts:
        if path == own_rollout:
            continue
        handle = markers.get(path)
        sessions.append({"rollout": path, "handle": handle, "outside_orca": handle is None, "own": False, "worktree": rollout_cwd(path)})
    return sessions
