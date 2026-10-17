from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path


CHUNK_SIZE = 1024 * 1024
MAX_READ = 8 * CHUNK_SIZE
UNKNOWN = {"weekly_used_percent": None, "limit_reset_at": None, "observed_at": None}


def reverse_lines(path: Path):
    with path.open("rb") as stream:
        position = stream.seek(0, os.SEEK_END)
        remaining = min(position, MAX_READ)
        pending = b""
        while remaining:
            size = min(remaining, CHUNK_SIZE)
            position -= size
            stream.seek(position)
            parts = (stream.read(size) + pending).split(b"\n")
            pending = parts[0]
            yield from reversed(parts[1:])
            remaining -= size
        if position == 0:
            yield pending


def reject_constant(name: str):
    raise ValueError(name)


def last_event(path: Path):
    try:
        for line in reverse_lines(path):
            try:
                event = json.loads(line, parse_constant=reject_constant)
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(event, dict):
                continue
            payload = event.get("payload")
            if isinstance(payload, dict) and "rate_limits" in payload:
                return event
    except OSError:
        pass
    return None


def weekly_usage(home: Path, max_age: int):
    files = []
    try:
        for path in (home / "sessions").rglob("rollout-*.jsonl"):
            try:
                files.append((path.stat().st_mtime_ns, path))
            except OSError:
                continue
    except OSError:
        return UNKNOWN
    chosen = None
    for modified, path in sorted(files, reverse=True)[:10]:
        event = last_event(path)
        if event is None:
            continue
        observed = event.get("timestamp")
        if not isinstance(observed, str):
            return UNKNOWN
        try:
            moment = datetime.fromisoformat(observed)
            if moment.tzinfo is None:
                return UNKNOWN
            stamp = moment.timestamp()
        except (ValueError, OverflowError, OSError):
            return UNKNOWN
        if chosen is None or (stamp, modified) > chosen[:2]:
            chosen = (stamp, modified, event)
    if chosen is None:
        return UNKNOWN
    stamp, _, event = chosen
    now = time.time()
    if now - stamp > max_age or stamp - now > 60:
        return UNKNOWN
    limits = event["payload"]["rate_limits"]
    if not isinstance(limits, dict):
        return UNKNOWN
    weekly = next((entry for slot in ("primary", "secondary")
                   if isinstance(entry := limits.get(slot), dict)
                   and entry.get("window_minutes") == 10080), None)
    if weekly is None:
        return UNKNOWN
    used, reset = weekly.get("used_percent"), weekly.get("resets_at")
    if type(used) not in (int, float) or type(reset) is not int or reset <= now:
        return UNKNOWN
    try:
        if not math.isfinite(used):
            return UNKNOWN
    except OverflowError:
        return UNKNOWN
    return {"weekly_used_percent": used, "limit_reset_at": reset, "observed_at": event["timestamp"]}


def nonnegative_seconds(value: str) -> int:
    try:
        seconds = int(value)
        if seconds >= 0:
            return seconds
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("must be a nonnegative integer")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path)
    parser.add_argument("--max-age-seconds", type=nonnegative_seconds, default=86400)
    args = parser.parse_args()
    home = args.home if args.home is not None else Path(os.environ.get("CODEX_HOME", "~/.codex"))
    print(json.dumps(weekly_usage(home.expanduser(), args.max_age_seconds)))


if __name__ == "__main__":
    main()
