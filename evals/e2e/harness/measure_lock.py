"""One machine-wide exclusive lock for real measurement runs, so two campaigns never overlap and contaminate wall time."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from harness.config import MEASURE_LOCK, MEASURE_LOCK_HOLDER_ENV

POLL_SECONDS = 1.0


class MeasureLockHeld(Exception):
    """Another process holds the measurement lock; the message names its pid and command."""


def read_holder(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def holder_text(holder: dict) -> str:
    if not holder:
        return "an unknown process"
    return f"pid {holder.get('pid', 'unknown')} (command: {holder.get('command', 'unknown')}, started {holder.get('started', 'unknown')})"


def inherited(path: Path) -> bool:
    """True when this process runs under the runner that holds the lock and named itself through the environment."""
    holder = read_holder(path)
    return bool(holder) and os.environ.get(MEASURE_LOCK_HOLDER_ENV) == str(holder.get("pid"))


def try_lock(handle) -> bool:
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def write_holder(handle, command: str) -> None:
    info = {"pid": os.getpid(), "command": command, "started": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    handle.seek(0)
    handle.truncate()
    handle.write(json.dumps(info) + "\n")
    handle.flush()


@contextlib.contextmanager
def hold(command: str, path: Path = MEASURE_LOCK, wait_seconds: float = 0.0, *,
         clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> Iterator[None]:
    """Hold the lock for the whole block. The kernel drops it when the process ends, even by a crash or a kill."""
    if inherited(path):
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+", encoding="utf-8")
    try:
        deadline = clock() + wait_seconds
        while not try_lock(handle):
            if clock() >= deadline:
                raise MeasureLockHeld(f"another measurement holds {path}: {holder_text(read_holder(path))}; "
                                      "wait with --wait-lock SECONDS or run after it ends")
            sleep(min(POLL_SECONDS, max(deadline - clock(), 0.0)))
        write_holder(handle, command)
        try:
            yield
        finally:
            handle.truncate(0)
    finally:
        handle.close()
