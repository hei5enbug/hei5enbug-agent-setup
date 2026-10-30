#!/usr/bin/env python3
"""Condense Claude Code and Codex session records into one short line per user input, reply, tool call, and error.

Each kept record becomes `L<original line number> <kind> <text>`. The script copies text from the records and adds
nothing else. A record without a timestamp is dropped when a time range is given.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Sequence

from session_common import (
    UNREADABLE_LINE,
    InputError,
    TimeRange,
    add_range_arguments,
    check_range_arguments,
    claude_typed_texts,
    codex_payload,
    decode_record,
    resolve_zone,
)

KINDS = ("user", "reply", "tool", "error")
LIMITS = {"user": 2000, "reply": 300, "tool": 300, "error": 500}
NEWLINES = re.compile(r"\s*[\r\n]+\s*")
EMPTY_ERROR = "(no text)"
OUTPUT_SUFFIX = ".condensed.txt"
SUMMARY_KEYS = (
    "command", "cmd", "file_path", "path", "pattern", "url", "query", "skill", "subagent_type", "description", "prompt",
)
EXIT_PREFIX = re.compile(r"\s*Exit code:\s*(-?\d+)")
OUTPUT_TYPES = ("function_call_output", "custom_tool_call_output")
Event = tuple[str, str]


class ReadFailure(Exception):
    """An input file cannot be read."""


def reason_of(error: OSError) -> str:
    return error.strerror or type(error).__name__


def collapse(text: str) -> str:
    return NEWLINES.sub(" ", text).strip()


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…[{len(text) - limit} chars dropped]"


def as_text(value: Any) -> str:
    """Flatten a string, a list of text blocks, or any other JSON value into plain text."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [as_text(item.get("text") if isinstance(item, dict) and "text" in item else item) for item in value]
        return " ".join(part for part in parts if part)
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def summarize_input(value: Any) -> str:
    """Name the one field of a tool input that best tells what the call did."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return value
    if not isinstance(value, dict):
        return as_text(value)
    for key in SUMMARY_KEYS:
        if key in value and value[key] not in (None, ""):
            return f"{key}={as_text(value[key])}"
    for key, item in value.items():
        if isinstance(item, (str, int, float)) and item != "":
            return f"{key}={item}"
    return ""


def tool_event(name: Any, tool_input: Any) -> Event:
    label = name if isinstance(name, str) and name else "unknown"
    summary = summarize_input(tool_input)
    return "tool", f"{label} {summary}".strip()


def claude_attachment_events(record: dict[str, Any]) -> list[Event]:
    attachment = record.get("attachment")
    if isinstance(attachment, dict) and attachment.get("type") == "hook_blocking_error":
        return [("error", as_text(attachment.get("blockingError")) or "hook blocked")]
    return []


def claude_system_events(record: dict[str, Any]) -> list[Event]:
    if record.get("subtype") != "stop_hook_summary":
        return []
    errors = record.get("hookErrors")
    if isinstance(errors, list) and errors:
        return [("error", "hook error: " + as_text(errors))]
    if record.get("preventedContinuation"):
        return [("error", "hook prevented continuation: " + as_text(record.get("stopReason")))]
    return []


def claude_assistant_events(record: dict[str, Any]) -> list[Event]:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if record.get("isApiErrorMessage"):
        return [("error", as_text(content) or "API error")]
    if isinstance(content, str):
        return [("reply", content)] if content.strip() else []
    events: list[Event] = []
    for item in content if isinstance(content, list) else []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text" and as_text(item.get("text")).strip():
            events.append(("reply", as_text(item["text"])))
        elif item.get("type") == "tool_use":
            events.append(tool_event(item.get("name"), item.get("input")))
    return events


def claude_user_events(record: dict[str, Any]) -> list[Event]:
    events: list[Event] = [("user", text) for text in claude_typed_texts(record) if text.strip()]
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    for item in content if isinstance(content, list) and not record.get("isMeta") else []:
        if isinstance(item, dict) and item.get("type") == "tool_result" and item.get("is_error"):
            events.append(("error", as_text(item.get("content")) or EMPTY_ERROR))
    return events


def claude_events(record: dict[str, Any]) -> list[Event]:
    handlers = {
        "user": claude_user_events,
        "assistant": claude_assistant_events,
        "attachment": claude_attachment_events,
        "system": claude_system_events,
    }
    handler = handlers.get(record.get("type"))
    return handler(record) if handler else []


def failed_exit(code: Any) -> bool:
    return code not in (None, 0, "0")


def file_change_paths(changes: Any) -> str:
    entries = list(changes) if isinstance(changes, dict) else changes if isinstance(changes, list) else []
    paths = [
        as_text(entry.get("path") if isinstance(entry, dict) else entry) for entry in entries
    ]
    return " ".join(path for path in paths if path)


def codex_command_events(item: dict[str, Any]) -> list[Event]:
    command = as_text(item.get("command"))
    events: list[Event] = [tool_event("shell", {"command": command})]
    if failed_exit(item.get("exit_code")):
        events.append(("error", f"exit {item.get('exit_code')} {command} {as_text(item.get('aggregated_output'))}"))
    return events


def codex_file_change_events(item: dict[str, Any]) -> list[Event]:
    events: list[Event] = [tool_event("FileChange", {"path": file_change_paths(item.get("changes"))})]
    if item.get("status") not in (None, "completed"):
        events.append(("error", f"file change {item.get('status')}: {as_text(item.get('stderr'))}"))
    return events


def codex_item_events(item: dict[str, Any]) -> list[Event]:
    kind = item.get("type")
    if kind == "UserMessage":
        return [("user", as_text(item.get("content")))]
    if kind == "AgentMessage":
        return [("reply", as_text(item.get("content")))]
    if kind == "CommandExecution":
        return codex_command_events(item)
    if kind == "FileChange":
        return codex_file_change_events(item)
    return []


def codex_event_msg_events(payload: dict[str, Any]) -> list[Event]:
    kind = payload.get("type")
    if kind == "user_message":
        return [("user", as_text(payload.get("message")))]
    if kind == "agent_message":
        return [("reply", as_text(payload.get("message")))]
    if kind == "item_completed" and isinstance(payload.get("item"), dict):
        return codex_item_events(payload["item"])
    if kind == "error":
        return [("error", as_text(payload.get("message")) or "error")]
    if kind == "exec_command_end" and failed_exit(payload.get("exit_code")):
        return [("error", f"exit {payload['exit_code']} {as_text(payload.get('aggregated_output'))}")]
    if kind == "patch_apply_end" and payload.get("success") is False:
        return [("error", f"patch failed: {as_text(payload.get('stderr'))}")]
    if kind == "turn_aborted":
        return [("error", f"turn aborted: {as_text(payload.get('reason'))}")]
    return []


def failed_end_call_id(payload: dict[str, Any]) -> str | None:
    """Return the call id of an exec_command_end or patch_apply_end event that reports a failure."""
    kind = payload.get("type")
    failed = (kind == "exec_command_end" and failed_exit(payload.get("exit_code"))) or (
        kind == "patch_apply_end" and payload.get("success") is False
    )
    call_id = payload.get("call_id")
    return call_id if failed and isinstance(call_id, str) and call_id else None


def failed_call_ids(path: Path, window: TimeRange | None) -> set[str]:
    """Collect the call ids whose end event reports a failure, so a failed output is reported once."""
    found: set[str] = set()
    for _, record, when in numbered_records(path, {"unreadable_lines": 0}):
        if window is not None and (when is None or not window.contains(when)):
            continue
        payload = codex_payload(record, "event_msg")
        call_id = failed_end_call_id(payload) if payload is not None else None
        if call_id:
            found.add(call_id)
    return found


def output_failure(output: Any) -> Event | None:
    """Return an error event when a tool output records a nonzero exit code, as JSON metadata or an `Exit code:` line."""
    value = output
    if isinstance(output, str):
        try:
            value = json.loads(output)
        except ValueError:
            value = output
    if isinstance(value, dict):
        metadata = value.get("metadata")
        code = metadata.get("exit_code") if isinstance(metadata, dict) else None
        return ("error", f"exit {code} {as_text(value.get('output'))}") if failed_exit(code) else None
    match = EXIT_PREFIX.match(output) if isinstance(output, str) else None
    if match and match.group(1) != "0":
        return ("error", output)
    return None


def codex_output_events(payload: dict[str, Any], failed_calls: set[str]) -> list[Event]:
    if payload.get("call_id") in failed_calls:
        return []
    failure = output_failure(payload.get("output"))
    return [failure] if failure else []


def codex_response_item_events(payload: dict[str, Any], failed_calls: set[str]) -> list[Event]:
    kind = payload.get("type")
    if kind == "function_call":
        return [tool_event(payload.get("name"), payload.get("arguments"))]
    if kind == "custom_tool_call":
        return [tool_event(payload.get("name"), payload.get("input"))]
    if kind == "local_shell_call":
        action = payload.get("action")
        return [tool_event("shell", action.get("command") if isinstance(action, dict) else action)]
    if kind in OUTPUT_TYPES:
        return codex_output_events(payload, failed_calls)
    return []


def codex_events(record: dict[str, Any], failed_calls: set[str]) -> list[Event]:
    payload = codex_payload(record, "event_msg")
    if payload is not None:
        return codex_event_msg_events(payload)
    payload = codex_payload(record, "response_item")
    return codex_response_item_events(payload, failed_calls) if payload is not None else []


def is_codex_meta(record: dict[str, Any]) -> bool:
    return record.get("type") == "session_meta" and isinstance(record.get("payload"), dict)


def numbered_records(path: Path, counts: dict[str, int]) -> Iterator[tuple[int, dict[str, Any], datetime | None]]:
    """Yield each readable record with its 1-based physical line number and count the lines that are unreadable."""
    with open(path, "rb") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record, when = decode_record(line)
            except UNREADABLE_LINE:
                counts["unreadable_lines"] += 1
                continue
            yield number, record, when


def condense_lines(path: Path, window: TimeRange | None) -> tuple[str, list[str], dict[str, int]]:
    counts = {"unreadable_lines": 0}
    lines = {kind: 0 for kind in KINDS}
    host: str | None = None
    failed_calls: set[str] = set()
    out: list[str] = []
    for number, record, when in numbered_records(path, counts):
        if host is None:
            host = "codex" if is_codex_meta(record) else "claude"
            failed_calls = failed_call_ids(path, window) if host == "codex" else failed_calls
        if window is not None and (when is None or not window.contains(when)):
            continue
        events = codex_events(record, failed_calls) if host == "codex" else claude_events(record)
        for kind, text in events:
            body = truncate(collapse(text), LIMITS[kind])
            if not body and kind == "error":
                body = EMPTY_ERROR
            if body:
                out.append(f"L{number} {kind} {body}")
                lines[kind] += 1
    return host or "claude", out, {**lines, **counts}


def output_path(out_dir: Path, source: Path, used: set[Path]) -> Path:
    candidate = out_dir / (source.stem + OUTPUT_SUFFIX)
    index = 2
    while candidate in used:
        candidate = out_dir / f"{source.stem}-{index}{OUTPUT_SUFFIX}"
        index += 1
    used.add(candidate)
    return candidate


def condense_file(source: Path, target: Path, window: TimeRange | None) -> dict[str, Any]:
    try:
        host, lines, counts = condense_lines(source, window)
        input_bytes = source.stat().st_size
    except OSError as error:
        raise ReadFailure(f"cannot be read: {reason_of(error)}") from error
    data = "".join(line + "\n" for line in lines).encode("utf-8", errors="replace")
    try:
        target.write_bytes(data)
    except OSError as error:
        raise ReadFailure(f"output cannot be written: {reason_of(error)}") from error
    return {
        "input": str(source),
        "output": str(target),
        "host": host,
        "input_bytes": input_bytes,
        "output_bytes": len(data),
        "lines": {kind: counts[kind] for kind in KINDS},
        "unreadable_lines": counts["unreadable_lines"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", help="Claude Code session or Codex rollout JSONL files")
    parser.add_argument("--out", required=True, help="directory that receives one condensed text file per input")
    add_range_arguments(parser)
    return parser


def resolve_out(value: str) -> Path:
    path = Path(os.path.abspath(value))
    if path.exists() and not path.is_dir():
        raise InputError(f"--out is not a directory: {path}")
    return path


def resolve_window(args: argparse.Namespace) -> TimeRange | None:
    check_range_arguments(args.since, args.until)
    zone, _ = resolve_zone(args.tz)
    return None if args.since is None else TimeRange.between(args.since, args.until, zone)


def emit(result: dict[str, Any]) -> None:
    text = json.dumps(result, sort_keys=True, ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(text.encode("utf-8", errors="backslashreplace"))
    sys.stdout.buffer.flush()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        window = resolve_window(args)
        out_dir = resolve_out(args.out)
    except InputError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        print(f"error: cannot create {out_dir}: {reason_of(error)}", file=sys.stderr)
        return 1
    files: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    used: set[Path] = set()
    for name in args.files:
        source = Path(os.path.abspath(name))
        try:
            files.append(condense_file(source, output_path(out_dir, source, used), window))
        except ReadFailure as error:
            failed.append({"path": str(source), "reason": str(error)})
            print(f"error: {source}: {error}", file=sys.stderr)
    emit({"files": files, "failed": failed})
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
