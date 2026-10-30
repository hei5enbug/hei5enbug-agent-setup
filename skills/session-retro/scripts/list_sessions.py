#!/usr/bin/env python3
"""List the Claude Code and Codex sessions that have records on one day or in one time range, for one working directory or all."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator, Sequence
from zoneinfo import ZoneInfo

from session_common import (
    DATE_FORMAT,
    UNREADABLE_LINE,
    InputError,
    TimeRange,
    add_range_arguments,
    check_range_arguments,
    decode_record,
    is_claude_utterance,
    is_codex_user_message,
    resolve_zone,
)

CLAUDE_PATH_UNSAFE = re.compile(r"[^A-Za-z0-9-]")


class ListingError(Exception):
    """An existing directory cannot be listed."""

    def __init__(self, path: Path, error: OSError) -> None:
        self.reason = f"cannot list directory: {reason_of(error)}"
        super().__init__(f"{self.reason}: {path}")


def reason_of(error: OSError) -> str:
    return error.strerror or type(error).__name__


def skip(path: Path | str, reason: str) -> dict[str, str]:
    return {"path": str(path), "reason": reason}


class Activity:
    """The records, and the user utterances among them, that fall inside the target day or range."""

    def __init__(self, window: TimeRange) -> None:
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
    path: Path, folder: Path, cwd: str | None, window: TimeRange, skipped: list[dict[str, str]]
) -> tuple[datetime, str, dict[str, Any]] | None:
    if os.stat(path).st_mtime < window.start.timestamp():
        return None
    reader = RecordReader(path)
    activity = Activity(window)
    entrypoint: str | None = None
    recorded_cwds: dict[str, None] = {}
    for record, when in reader:
        if entrypoint is None and isinstance(record.get("entrypoint"), str):
            entrypoint = record["entrypoint"]
        if isinstance(record.get("cwd"), str):
            recorded_cwds[record["cwd"]] = None
        activity.add(when, is_claude_utterance(record))
    # Different working directories can share one encoded project folder, such as /a/x.y and /a/x-y.
    if cwd is not None and recorded_cwds and cwd not in recorded_cwds:
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
    if cwd is None:
        item["cwd"] = next(iter(recorded_cwds), None)
    return activity.first, str(path), item


def claude_folders(claude_dir: Path, cwd: str | None) -> list[Path]:
    projects = claude_dir / "projects"
    if cwd is not None:
        return [projects / encode_cwd(cwd)]
    folders = []
    for entry in list_dir(projects) or []:
        try:
            if entry.is_dir():
                folders.append(Path(entry.path))
        except OSError as error:
            raise ListingError(Path(entry.path), error) from error
    return folders


def scan_claude(
    claude_dir: Path, cwd: str | None, window: TimeRange, skipped: list[dict[str, str]]
) -> list[tuple[datetime, str, dict[str, Any]]]:
    found = []
    for folder in claude_folders(claude_dir, cwd):
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


def scan_codex_file(
    path: Path, cwd: str | None, window: TimeRange, skipped: list[dict[str, str]]
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
        if cwd is not None and payload.get("cwd") != cwd:
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
    if cwd is None:
        item["cwd"] = payload["cwd"] if isinstance(payload.get("cwd"), str) else None
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
    codex_dir: Path, cwd: str | None, window: TimeRange, skipped: list[dict[str, str]]
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
    parser.add_argument("--date", help="target day as YYYY-MM-DD (default: today in the chosen time zone; excludes --since and --until)")
    parser.add_argument("--cwd", help="working directory of the sessions (default: current directory; excludes --all-cwd)")
    parser.add_argument("--all-cwd", action="store_true", help="list the sessions of every working directory")
    add_range_arguments(parser)
    parser.add_argument(
        "--claude-dir", help="Claude Code config directory (default: $CLAUDE_CONFIG_DIR, else ~/.claude)"
    )
    parser.add_argument("--codex-dir", help="Codex home directory (default: $CODEX_HOME, else ~/.codex)")
    return parser


def emit(result: dict[str, Any]) -> None:
    text = json.dumps(result, sort_keys=True, ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(text.encode("utf-8", errors="backslashreplace"))
    sys.stdout.buffer.flush()


def resolve_window(args: argparse.Namespace, zone: ZoneInfo | None) -> tuple[TimeRange, dict[str, str]]:
    """Return the span to scan and the output keys that name it."""
    check_range_arguments(args.since, args.until)
    if args.since is None:
        day = resolve_day(args.date, zone)
        return TimeRange.for_day(day, zone), {"date": day.isoformat()}
    if args.date is not None:
        raise InputError("--date cannot be combined with --since or --until")
    window = TimeRange.between(args.since, args.until, zone)
    return window, {"since": window.local_iso(window.start), "until": window.local_iso(window.end)}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.all_cwd and args.cwd is not None:
            raise InputError("--all-cwd cannot be combined with --cwd")
        zone, zone_name = resolve_zone(args.tz)
        window, span = resolve_window(args, zone)
        claude_dir = resolve_dir(args.claude_dir, "CLAUDE_CONFIG_DIR", ".claude", "--claude-dir")
        codex_dir = resolve_dir(args.codex_dir, "CODEX_HOME", ".codex", "--codex-dir")
    except InputError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    cwd = None if args.all_cwd else resolve_cwd(args.cwd)
    skipped: list[dict[str, str]] = []
    try:
        found = scan_claude(claude_dir, cwd, window, skipped) + scan_codex(codex_dir, cwd, window, skipped)
    except ListingError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    found.sort(key=lambda entry: (entry[0], entry[1]))
    emit(
        {
            **span,
            "tz": zone_name,
            "cwd": cwd,
            "sessions": [item for _, _, item in found],
            "skipped": sorted(skipped, key=lambda entry: (entry["path"], entry["reason"])),
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
