from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from refresh_install import CODEX_IDLE_EVENTS, rollout_last_record


TRANSCRIPT_TAIL_BYTES = 512 * 1024
COMMAND_RECORD_PREFIXES = ("<command-name>", "<local-command-caveat>", "<local-command-stdout>", "<local-command-stderr>")
COMMAND_OUTPUT_PREFIXES = COMMAND_RECORD_PREFIXES[2:]
COMMAND_NAME = re.compile(r"<command-name>\s*(/\S+?)\s*</command-name>")
INTERRUPT_PREFIX = "[Request interrupted by user"
BACKGROUND_IDS = (
    re.compile(r"^Command running in background with ID: ([\w-]+)", re.MULTILINE),
    re.compile(r"^Command (?:did not complete within its \d+s timeout and )?was moved to the background \(ID: ([\w-]+)", re.MULTILINE),
    re.compile(r"^Monitor started \(task ([\w-]+)", re.MULTILINE),
    re.compile(r"^(?:\w+(?: \w+)* launched in background\. )?Task ID: ([\w-]+)", re.MULTILINE),
)
ASYNC_AGENT = re.compile(r"^Async agent launched successfully", re.MULTILINE)
AGENT_ID = re.compile(r"agentId: ([\w-]+)")
QUOTED_ID = re.compile(r"\(ID: |with ID: |Task ID: |\(task ")
BACKGROUND_MENTION = re.compile(r"(?:\brun(?:s|ning)?|\bmoved)\b[^\n]{0,60}?\b(?:in|to) the background")
NOTIFIED_ID = re.compile(r"<task-id>([\w-]+)</task-id>")
STOPPED_ID = re.compile(r"Successfully stopped task: ([\w-]+)")
SCAN_MARKERS = (b"background", b"Async agent", b"Monitor started", b"Task ID:", b"<task-id>", b"stopped task")
EARLIER_SCANS: dict[str, dict] = {}


def text_of(content: object) -> str:
    """Every text in a transcript message, including text nested in tool results."""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return text_of(content.get("text")) + text_of(content.get("content"))
    if isinstance(content, list):
        return "\n".join(text_of(part) for part in content)
    return ""


def message_content(record: dict) -> object:
    message = record.get("message")
    return message.get("content") if isinstance(message, dict) else None


def plain_text(content: object) -> str | None:
    """The text of a message made only of text, or None when it also holds tool results or other parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list) and content and all(isinstance(part, dict) and part.get("type") == "text" for part in content):
        return "".join(str(part.get("text") or "") for part in content)
    return None


def classify(record: dict) -> str:
    """`neutral`, `command`, `output`, `finished`, or `active` for one Claude Code transcript record."""
    kind = record.get("type")
    if kind == "system":
        subtype = record.get("subtype")
        if subtype == "turn_duration":
            return "finished"
        return "output" if subtype == "local_command" else "neutral"
    if kind == "assistant":
        return "active"
    if kind != "user" or record.get("isMeta") or record.get("isCompactSummary"):
        return "neutral"
    text = (plain_text(message_content(record)) or "").lstrip()
    if text.startswith(INTERRUPT_PREFIX):
        return "finished"
    if text.startswith("<command-name>"):
        return "command"
    if text.startswith(COMMAND_RECORD_PREFIXES):
        return "output" if text.startswith(COMMAND_OUTPUT_PREFIXES) else "neutral"
    return "active"


def typed_command(record: dict) -> str | None:
    """The slash command name of a plain user record that is only a typed slash command, such as `/compact`."""
    if record.get("type") != "user":
        return None
    words = (plain_text(message_content(record)) or "").split()
    return words[0] if words and words[0].startswith("/") else None


def tool_result_texts(record: dict) -> list[str]:
    content = message_content(record)
    if record.get("type") != "user" or not isinstance(content, list):
        return []
    return [text_of(part.get("content")) for part in content if isinstance(part, dict) and part.get("type") == "tool_result"]


def launched_ids(text: str) -> tuple[list[str], bool]:
    """Background task IDs a tool result announces, and whether it mentions a background run it gives no ID for."""
    ids = [match.group(1) for pattern in BACKGROUND_IDS for match in pattern.finditer(text)]
    if ASYNC_AGENT.search(text):
        found = AGENT_ID.search(text)
        if found:
            ids.append(found.group(1))
        else:
            return ids, True
    first = text.split("\n", 1)[0]
    return ids, not ids and not QUOTED_ID.search(first) and bool(BACKGROUND_MENTION.search(first))


def wakeup_pending(record: dict, now: float) -> bool:
    if record.get("type") != "assistant":
        return False
    content = message_content(record)
    for part in content if isinstance(content, list) else []:
        if not (isinstance(part, dict) and part.get("type") == "tool_use"):
            continue
        if part.get("name") == "CronCreate":
            return True
        arguments = part.get("input") if isinstance(part.get("input"), dict) else {}
        if part.get("name") == "ScheduleWakeup" and arguments.get("stop") is not True:
            delay = arguments.get("delaySeconds")
            stamp = record.get("timestamp")
            try:
                due = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() + float(delay)
            except (AttributeError, ValueError, TypeError):
                return True
            if due > now:
                return True
    return False


def track_pending(record: dict, pending: set[str]) -> bool:
    """Add the background IDs a record launches and drop the ones it reports; True when it launches a run with no ID."""
    unknown = False
    for text in tool_result_texts(record):
        ids, no_id = launched_ids(text)
        unknown = unknown or no_id
        pending.update(ids)
        pending.difference_update(STOPPED_ID.findall(text))
    if record.get("type") == "user":
        pending.difference_update(NOTIFIED_ID.findall(text_of(message_content(record))))
    attachment = record.get("attachment")
    if record.get("type") == "attachment" and isinstance(attachment, dict) and attachment.get("type") == "queued_command":
        pending.difference_update(NOTIFIED_ID.findall(text_of(attachment.get("prompt"))))
    return unknown


def owes_notification(records: list[dict], now: float, earlier: set[str] | None = None) -> bool:
    """True when a background task, scheduled wakeup, or unrecognized background run may still report back.

    `earlier` holds the IDs still pending in the part of the file before `records`.
    """
    pending: set[str] = set(earlier or ())
    for record in records:
        if wakeup_pending(record, now):
            return True
        if track_pending(record, pending):
            return True
    return bool(pending)


def claude_state(records: list[dict], now: float | None = None, earlier: Callable[[], set[str]] | None = None) -> str | None:
    """`idle`, `busy`, or None for the host's own Claude Code turn record, judged from the transcript tail."""
    verdict = claude_turn(records, now, earlier)
    return None if verdict == "owing" else verdict


def claude_turn(records: list[dict], now: float | None = None, earlier: Callable[[], set[str]] | None = None) -> str | None:
    """Like `claude_state`, but `owing` when the turn ended while a background task, subagent, or wakeup still owes a notification."""
    if not records:
        return None
    kinds = [classify(record) for record in records]
    has_duration = any(record.get("type") == "system" and record.get("subtype") == "turn_duration" for record in records)
    output_seen = False
    finished_commands: set[str] = set()
    for index in range(len(records) - 1, -1, -1):
        kind = kinds[index]
        if kind == "output":
            output_seen = True
        elif kind == "command":
            if not output_seen:
                return "busy"
            finished_commands.update(COMMAND_NAME.findall(plain_text(message_content(records[index])) or ""))
        elif kind == "finished":
            return "owing" if owes_notification(records, time.time() if now is None else now, earlier() if earlier else None) else "idle"
        elif kind == "active" and typed_command(records[index]) not in finished_commands:
            return "busy" if has_duration else None
    return None


def transcript_tail(path: str) -> tuple[list[dict], int] | None:
    """The complete JSON records in the last TRANSCRIPT_TAIL_BYTES of a file and the offset where they begin, or None
    when the last line is partial."""
    with open(path, "rb") as stream:
        size = stream.seek(0, os.SEEK_END)
        start = max(0, size - TRANSCRIPT_TAIL_BYTES)
        stream.seek(start)
        data = stream.read()
    if not data.endswith(b"\n"):
        return None
    boundary = 0
    if start:
        boundary = start + data.find(b"\n") + 1
        data = data[data.find(b"\n") + 1:]
    records = []
    for line in data.split(b"\n"):
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(record, dict):
            records.append(record)
    return records, boundary


def earlier_pending(path: str, boundary: int) -> set[str]:
    """Background IDs still pending in the file before `boundary`, scanning only bytes not seen by an earlier call."""
    status = os.stat(path)
    cached = EARLIER_SCANS.get(path)
    if not cached or cached["inode"] != status.st_ino or cached["scanned"] > boundary or status.st_size < boundary:
        cached = EARLIER_SCANS[path] = {"inode": status.st_ino, "scanned": 0, "pending": set()}
    with open(path, "rb") as stream:
        stream.seek(cached["scanned"])
        while cached["scanned"] < boundary:
            line = stream.readline()
            if not line.endswith(b"\n"):
                break
            cached["scanned"] += len(line)
            if not any(marker in line for marker in SCAN_MARKERS):
                continue
            try:
                record = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(record, dict):
                track_pending(record, cached["pending"])
    return set(cached["pending"])


def record_state(host: str, path: object, now: float | None = None, detailed: bool = False) -> str | None:
    """`idle`, `busy`, or None (cannot decide) from the host's transcript or rollout file at `path`; with `detailed`, a Claude Code
    turn that ended while a background task still owes a notification is `owing` instead of None."""
    if not isinstance(path, str) or not path or not Path(path).is_file():
        return None
    try:
        if host == "codex":
            record = rollout_last_record(Path(path))
            payload = record.get("payload") if record else None
            if record is None:
                return None
            idle = record.get("type") == "event_msg" and isinstance(payload, dict) and payload.get("type") in CODEX_IDLE_EVENTS
            return "idle" if idle else "busy"
        tail = transcript_tail(path)
        if tail is None:
            return None
        records, boundary = tail
        earlier = (lambda: earlier_pending(path, boundary)) if boundary else None
        return claude_turn(records, now, earlier) if detailed else claude_state(records, now, earlier)
    except OSError:
        return None
