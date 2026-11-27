from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Sequence

from refresh_host_record import COMMAND_RECORD_PREFIXES, TRANSCRIPT_TAIL_BYTES
from refresh_reload import judge_reload, local_text, reload_report
from refresh_screen import composer_bounds


COMMANDS = {"reload": "/reload-plugins", "compact": "/compact", "clear": "/clear"}
RELOAD_DONE = re.compile(r"Reloaded: \d+ plugins?")
RELOAD_REFUSED = re.compile(r"reload changes MCP tools|/reload-plugins --force", re.IGNORECASE)
CLAUDE_COMPACTED = re.compile(r"Compacted|Conversation compacted")
CODEX_COMPACTED = re.compile(r"Context compacted")
CLAUDE_NOTHING_TO_COMPACT = re.compile(r"Not enough messages to compact")
CLAUDE_COMPACT_ERROR = re.compile(r"Error during compaction|Compaction canceled")


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


def transcript_outcome(host: str, action: str, records: list[dict], entry: dict | None = None) -> str | None:
    for index, record in enumerate(records):
        content = str(record.get("content") or "") if record.get("subtype") == "local_command" else ""
        if host == "claude" and action == "reload" and content:
            if RELOAD_REFUSED.search(content):
                return "failed:reload_needs_force"
            if RELOAD_DONE.search(content):
                return judge_reload(entry, reload_report(local_text(records[index:])))
        if host == "claude" and action == "compact" and content:
            if CLAUDE_NOTHING_TO_COMPACT.search(content):
                return "nothing_to_compact"
            if CLAUDE_COMPACT_ERROR.search(content):
                return "failed:compact_error"
        if host == "codex" and action == "compact" and record.get("type") == "compacted":
            return "done"
    return None


def last_item_is(lines: Sequence[str], echo: str, result: re.Pattern) -> bool:
    """True when the newest conversation item above the Claude Code composer is `echo` followed by `result`."""
    bounds = composer_bounds(lines)
    if bounds is None:
        return False
    above = lines[:bounds[0]]
    echoes = [index for index, line in enumerate(above) if line.strip().startswith("❯")]
    return bool(echoes) and above[echoes[-1]].strip() == f"❯ {echo}" and any(result.search(line) for line in above[echoes[-1] + 1:])


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
