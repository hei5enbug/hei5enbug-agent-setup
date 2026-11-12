from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

from refresh_core import RefreshError
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
