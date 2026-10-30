"""Time-range, time-zone, and record-decoding helpers shared by the session-retro scripts."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DATE_FORMAT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
INSTANT_FORMAT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(:[0-9]{2})?")
INSTANT_HINT = "expected YYYY-MM-DDTHH:MM"
LOCALTIME_LINK = "/etc/localtime"
ZONEINFO_MARKER = "zoneinfo/"
UNREADABLE_LINE = (ValueError, OverflowError, RecursionError)
ZONE_LOOKUP_ERRORS = (ZoneInfoNotFoundError, ValueError, OSError)
LOCAL_COMMAND_PREFIXES = ("<command-", "<local-command-")


class InputError(Exception):
    """An argument value is invalid."""


class TimeRange:
    """A half-open span [start, end) of UTC instants, shown in the chosen time zone."""

    def __init__(self, start: datetime, end: datetime, zone: ZoneInfo | None) -> None:
        self.zone = zone
        self.start = start
        self.end = end

    @classmethod
    def for_day(cls, day: date, zone: ZoneInfo | None) -> "TimeRange":
        try:
            return cls(midnight_utc(day, zone), midnight_utc(day + timedelta(days=1), zone), zone)
        except (OverflowError, ValueError) as error:
            raise InputError(f"date is outside the supported range: {day.isoformat()}") from error

    @classmethod
    def between(cls, since: str, until: str | None, zone: ZoneInfo | None) -> "TimeRange":
        start = parse_instant(since, "--since", zone)
        end = datetime.now(timezone.utc) if until is None else parse_instant(until, "--until", zone)
        if start >= end:
            raise InputError("--since must be earlier than --until")
        return cls(start, end, zone)

    def contains(self, when: datetime) -> bool:
        return self.start <= when < self.end

    def local_iso(self, when: datetime) -> str:
        return when.astimezone(self.zone).isoformat()


def midnight_utc(day: date, zone: ZoneInfo | None) -> datetime:
    return datetime.combine(day, time.min, tzinfo=zone).astimezone(timezone.utc)


def parse_instant(value: str, option: str, zone: ZoneInfo | None) -> datetime:
    """Read a local date-time such as 2026-10-14T09:00 in the chosen zone and return it as a UTC instant."""
    try:
        if not INSTANT_FORMAT.fullmatch(value):
            raise ValueError(value)
        local = datetime.fromisoformat(value).replace(tzinfo=zone)
        return local.astimezone(timezone.utc)
    except (ValueError, OverflowError) as error:
        raise InputError(f"invalid {option}: {value} ({INSTANT_HINT})") from error


def add_range_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--since", help=f"start of a time range, inclusive, as a local date-time ({INSTANT_HINT}[:SS])")
    parser.add_argument("--until", help="end of the time range, exclusive (default: now); requires --since")
    parser.add_argument("--tz", help="IANA time zone that defines the day or range (default: local time zone)")


def check_range_arguments(since: str | None, until: str | None) -> None:
    if until is not None and since is None:
        raise InputError("--until requires --since")


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


def is_typed_text(text: Any) -> bool:
    """Return whether text is something the user typed, not a local command record."""
    return isinstance(text, str) and not text.lstrip().startswith(LOCAL_COMMAND_PREFIXES)


def claude_typed_texts(record: dict[str, Any]) -> list[str]:
    """Return the texts a user typed in one Claude Code record; tool results and meta records hold none."""
    if record.get("type") != "user" or record.get("isMeta"):
        return []
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return [content] if is_typed_text(content) else []
    if not isinstance(content, list):
        return []
    return [
        item["text"]
        for item in content
        if isinstance(item, dict) and item.get("type") == "text" and is_typed_text(item.get("text"))
    ]


def is_claude_utterance(record: dict[str, Any]) -> bool:
    return bool(claude_typed_texts(record))


def codex_payload(record: dict[str, Any], record_type: str) -> dict[str, Any] | None:
    payload = record.get("payload")
    return payload if record.get("type") == record_type and isinstance(payload, dict) else None


def is_codex_user_message(record: dict[str, Any]) -> bool:
    """Count a typed user turn in either Codex format: an older `user_message` event or a completed `UserMessage` item.

    A `response_item` with the user role also carries injected context, such as instructions and the environment,
    so it is never counted.
    """
    payload = codex_payload(record, "event_msg")
    if payload is None:
        return False
    if payload.get("type") == "user_message":
        return True
    item = payload.get("item")
    return payload.get("type") == "item_completed" and isinstance(item, dict) and item.get("type") == "UserMessage"
