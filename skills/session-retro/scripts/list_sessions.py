#!/usr/bin/env python3
"""List the Claude Code and Codex sessions that have records on one day for one working directory."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DATE_FORMAT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
CLAUDE_PATH_UNSAFE = re.compile(r"[^A-Za-z0-9-]")
LOCALTIME_LINK = "/etc/localtime"
ZONEINFO_MARKER = "zoneinfo/"
UNREADABLE_LINE = (ValueError, OverflowError, RecursionError)
ZONE_LOOKUP_ERRORS = (ZoneInfoNotFoundError, ValueError, OSError)


class InputError(Exception):
    """An argument value is invalid."""


class ListingError(Exception):
    """An existing directory cannot be listed."""

    def __init__(self, path: Path, error: OSError) -> None:
        self.reason = f"cannot list directory: {reason_of(error)}"
        super().__init__(f"{self.reason}: {path}")


def reason_of(error: OSError) -> str:
    return error.strerror or type(error).__name__


def skip(path: Path | str, reason: str) -> dict[str, str]:
    return {"path": str(path), "reason": reason}


class Window:
    """The target day, [00:00, 24:00) in the chosen time zone, as UTC instants."""

    def __init__(self, day: date, zone: ZoneInfo | None) -> None:
        self.zone = zone
        try:
            self.start = midnight_utc(day, zone)
            self.end = midnight_utc(day + timedelta(days=1), zone)
        except (OverflowError, ValueError) as error:
            raise InputError(f"date is outside the supported range: {day.isoformat()}") from error

    def contains(self, when: datetime) -> bool:
        return self.start <= when < self.end

    def local_iso(self, when: datetime) -> str:
        return when.astimezone(self.zone).isoformat()


def midnight_utc(day: date, zone: ZoneInfo | None) -> datetime:
    return datetime.combine(day, time.min, tzinfo=zone).astimezone(timezone.utc)


class Activity:
    """The records, and the user utterances among them, that fall inside the target day."""

    def __init__(self, window: Window) -> None:
        self.window = window
        self.first: datetime | None = None
        self.last: datetime | None = None
        self.user_messages = 0

    def add(self, when: datetime | None, is_user_message: bool) -> None:
        if when is None or not self.window.contains(when):
            return
        if self.first is None or when < self.first:
            self.first = when
        if self.last is None or when > self.last:
            self.last = when
        if is_user_message:
            self.user_messages += 1


def decode_record(line: bytes) -> tuple[dict[str, Any], datetime | None]:
    record = json.loads(line)
    if not isinstance(record, dict):
        raise ValueError("record is not an object")
    stamp = record.get("timestamp")
    if stamp is None:
        return record, None
    if not isinstance(stamp, str):
        raise ValueError("timestamp is not text")
    when = datetime.fromisoformat(stamp)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return record, when.astimezone(timezone.utc)


class RecordReader:
    """Streams the records of one JSONL transcript and counts the lines it cannot use."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.unreadable = 0

    def __iter__(self) -> Iterator[tuple[dict[str, Any], datetime | None]]:
        with open(self.path, "rb") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    decoded = decode_record(line)
                except UNREADABLE_LINE:
                    self.unreadable += 1
                    continue
                yield decoded


def list_dir(path: Path) -> list[os.DirEntry[str]] | None:
    """Return the sorted entries, or None when the directory does not exist."""
    try:
        with os.scandir(path) as entries:
            return sorted(entries, key=lambda entry: entry.name)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as error:
        raise ListingError(path, error) from error


def encode_cwd(cwd: str) -> str:
    return CLAUDE_PATH_UNSAFE.sub("-", cwd)


LOCAL_COMMAND_PREFIXES = ("<command-", "<local-command-")


def is_typed_text(text: Any) -> bool:
    """Return whether text is something the user typed, not a local command record."""
    return isinstance(text, str) and not text.lstrip().startswith(LOCAL_COMMAND_PREFIXES)


def is_claude_utterance(record: dict[str, Any]) -> bool:
    if record.get("type") != "user" or record.get("isMeta"):
        return False
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return is_typed_text(content)
    return isinstance(content, list) and any(
        isinstance(item, dict) and item.get("type") == "text" and is_typed_text(item.get("text"))
        for item in content
    )


def count_subagent_transcripts(folder: Path, session_id: str, skipped: list[dict[str, str]]) -> int:
    directory = folder / session_id / "subagents"
    try:
        entries = list_dir(directory)
    except ListingError as error:
        skipped.append(skip(directory, error.reason))
        return 0
    return sum(1 for entry in entries or [] if entry.name.endswith(".jsonl"))


def report_unreadable(path: Path, reader: "RecordReader", has_day_records: bool, skipped: list[dict[str, str]]) -> None:
    if not reader.unreadable:
        return
    reason = f"{reader.unreadable} unreadable lines"
    if not has_day_records:
        reason += "; no readable record on the day"
    skipped.append(skip(path, reason))


def scan_claude_file(
    path: Path, folder: Path, cwd: str, window: Window, skipped: list[dict[str, str]]
) -> tuple[datetime, str, dict[str, Any]] | None:
    if os.stat(path).st_mtime < window.start.timestamp():
        return None
    reader = RecordReader(path)
    activity = Activity(window)
    entrypoint: str | None = None
    recorded_cwds: set[str] = set()
    for record, when in reader:
        if entrypoint is None and isinstance(record.get("entrypoint"), str):
            entrypoint = record["entrypoint"]
        if isinstance(record.get("cwd"), str):
            recorded_cwds.add(record["cwd"])
        activity.add(when, is_claude_utterance(record))
    # Different working directories can share one encoded project folder, such as /a/x.y and /a/x-y.
    if recorded_cwds and cwd not in recorded_cwds:
        return None
    report_unreadable(path, reader, activity.first is not None, skipped)
    if activity.first is None or activity.last is None:
        return None
    item = {
        "host": "claude",
        "path": str(path),
        "session_id": path.stem,
        "first_record": window.local_iso(activity.first),
        "last_record": window.local_iso(activity.last),
        "user_messages": activity.user_messages,
        "source": entrypoint,
        "parent_session_id": None,
        "subagent_transcripts": count_subagent_transcripts(folder, path.stem, skipped),
    }
    return activity.first, str(path), item


def scan_claude(
    claude_dir: Path, cwd: str, window: Window, skipped: list[dict[str, str]]
) -> list[tuple[datetime, str, dict[str, Any]]]:
    folder = claude_dir / "projects" / encode_cwd(cwd)
    found = []
    for entry in list_dir(folder) or []:
        if not entry.name.endswith(".jsonl"):
            continue
        path = Path(entry.path)
        try:
            if entry.is_dir():
                continue
            scanned = scan_claude_file(path, folder, cwd, window, skipped)
        except OSError as error:
            skipped.append(skip(path, f"cannot be read: {reason_of(error)}"))
            continue
        if scanned is not None:
            found.append(scanned)
    return found


def codex_source(source: Any) -> tuple[str | None, str | None]:
    """Return the session source label and the parent session id of a Codex subagent."""
    if isinstance(source, str):
        return source, None
    if isinstance(source, dict) and "subagent" in source:
        spawn = source["subagent"]
        spawn = spawn.get("thread_spawn") if isinstance(spawn, dict) else None
        parent = spawn.get("parent_thread_id") if isinstance(spawn, dict) else None
        return "subagent", parent if isinstance(parent, str) else None
    return (None if source is None else "unknown"), None


def is_codex_user_message(record: dict[str, Any]) -> bool:
    """Count a typed user turn in either Codex format: an older `user_message` event or a completed `UserMessage` item.

    A `response_item` with the user role also carries injected context, such as instructions and the environment,
    so it is never counted.
    """
    payload = record.get("payload")
    if record.get("type") != "event_msg" or not isinstance(payload, dict):
        return False
    if payload.get("type") == "user_message":
        return True
    item = payload.get("item")
    return payload.get("type") == "item_completed" and isinstance(item, dict) and item.get("type") == "UserMessage"


def scan_codex_file(
    path: Path, cwd: str, window: Window, skipped: list[dict[str, str]]
) -> tuple[datetime, str, dict[str, Any]] | None:
    if os.stat(path).st_mtime < window.start.timestamp():
        return None
    reader = RecordReader(path)
    activity = Activity(window)
    with closing(iter(reader)) as records:
        first = next(records, None)
        payload = first[0].get("payload") if first else None
        if first is None or first[0].get("type") != "session_meta" or not isinstance(payload, dict):
            skipped.append(skip(path, "first record is not session_meta"))
            return None
        if payload.get("cwd") != cwd:
            return None
        activity.add(first[1], False)
        for record, when in records:
            activity.add(when, is_codex_user_message(record))
    report_unreadable(path, reader, activity.first is not None, skipped)
    if activity.first is None or activity.last is None:
        return None
    source, parent = codex_source(payload.get("source"))
    session_id = payload.get("id")
    item = {
        "host": "codex",
        "path": str(path),
        "session_id": session_id if isinstance(session_id, str) else None,
        "first_record": window.local_iso(activity.first),
        "last_record": window.local_iso(activity.last),
        "user_messages": activity.user_messages,
        "source": source,
        "parent_session_id": parent,
        "subagent_transcripts": None,
    }
    return activity.first, str(path), item


def rollout_files(root: Path, skipped: list[dict[str, str]]) -> Iterator[Path]:
    def note(error: OSError) -> None:
        skipped.append(skip(error.filename or root, f"cannot list directory: {reason_of(error)}"))

    if list_dir(root) is None:
        return
    for directory, dirnames, filenames in os.walk(root, onerror=note):
        dirnames.sort()
        for name in sorted(filenames):
            if name.startswith("rollout-") and name.endswith(".jsonl"):
                yield Path(directory, name)


def scan_codex(
    codex_dir: Path, cwd: str, window: Window, skipped: list[dict[str, str]]
) -> list[tuple[datetime, str, dict[str, Any]]]:
    found = []
    for path in rollout_files(codex_dir / "sessions", skipped):
        try:
            scanned = scan_codex_file(path, cwd, window, skipped)
        except OSError as error:
            skipped.append(skip(path, f"cannot be read: {reason_of(error)}"))
            continue
        if scanned is not None:
            found.append(scanned)
    return found


def local_zone() -> tuple[ZoneInfo | None, str]:
    """Return the system zone as an IANA zone when it can be named, else None for system-local time."""
    configured = os.environ.get("TZ", "").lstrip(":")
    if configured:
        candidates = [configured]
    else:
        target = os.path.realpath(LOCALTIME_LINK)
        candidates = [target.split(ZONEINFO_MARKER, 1)[1]] if ZONEINFO_MARKER in target else []
    for name in candidates:
        try:
            return ZoneInfo(name), name
        except ZONE_LOOKUP_ERRORS:
            continue
    return None, datetime.now().astimezone().tzname() or "local"


def resolve_zone(name: str | None) -> tuple[ZoneInfo | None, str]:
    if name is None:
        return local_zone()
    try:
        return ZoneInfo(name), name
    except ZONE_LOOKUP_ERRORS as error:
        raise InputError(f"unknown time zone: {name}") from error


def resolve_day(value: str | None, zone: ZoneInfo | None) -> date:
    if value is None:
        return datetime.now(zone).date()
    try:
        if not DATE_FORMAT.fullmatch(value):
            raise ValueError(value)
        return date.fromisoformat(value)
    except ValueError as error:
        raise InputError(f"invalid date: {value} (expected YYYY-MM-DD)") from error


def resolve_dir(value: str | None, env_name: str, fallback: str, option: str) -> Path:
    path = value or os.environ.get(env_name) or str(Path.home() / fallback)
    path = os.path.abspath(path)
    if os.path.exists(path) and not os.path.isdir(path):
        raise InputError(f"{option} is not a directory: {path}")
    return Path(path)


def resolve_cwd(value: str | None) -> str:
    if value is None:
        return os.getcwd()
    return os.path.realpath(value) if os.path.exists(value) else os.path.abspath(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="target day as YYYY-MM-DD (default: today in the chosen time zone)")
    parser.add_argument("--cwd", help="working directory of the sessions (default: current directory)")
    parser.add_argument("--tz", help="IANA time zone that defines the day (default: local time zone)")
    parser.add_argument(
        "--claude-dir", help="Claude Code config directory (default: $CLAUDE_CONFIG_DIR, else ~/.claude)"
    )
    parser.add_argument("--codex-dir", help="Codex home directory (default: $CODEX_HOME, else ~/.codex)")
    return parser


def emit(result: dict[str, Any]) -> None:
    text = json.dumps(result, sort_keys=True, ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(text.encode("utf-8", errors="backslashreplace"))
    sys.stdout.buffer.flush()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        zone, zone_name = resolve_zone(args.tz)
        day = resolve_day(args.date, zone)
        window = Window(day, zone)
        claude_dir = resolve_dir(args.claude_dir, "CLAUDE_CONFIG_DIR", ".claude", "--claude-dir")
        codex_dir = resolve_dir(args.codex_dir, "CODEX_HOME", ".codex", "--codex-dir")
    except InputError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    cwd = resolve_cwd(args.cwd)
    skipped: list[dict[str, str]] = []
    try:
        found = scan_claude(claude_dir, cwd, window, skipped) + scan_codex(codex_dir, cwd, window, skipped)
    except ListingError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    found.sort(key=lambda entry: (entry[0], entry[1]))
    emit(
        {
            "date": day.isoformat(),
            "tz": zone_name,
            "cwd": cwd,
            "sessions": [item for _, _, item in found],
            "skipped": sorted(skipped, key=lambda entry: (entry["path"], entry["reason"])),
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
