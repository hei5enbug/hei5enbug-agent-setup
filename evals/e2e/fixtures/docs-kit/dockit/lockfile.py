"""An exclusive lock file that names the process holding it."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class Busy(RuntimeError):
    """Another process holds the lock."""


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def owner_of(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


@contextmanager
def held(path: Path, what: str) -> Iterator[None]:
    """Hold `path` as a lock for the block. The process that holds it may take it again; a lock left by a dead
    process is taken over."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mine = False
    while True:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            owner = owner_of(path)
            if owner == os.getpid():
                break
            if owner and alive(owner):
                raise Busy(f"{what} is in use by process {owner}")
            path.unlink(missing_ok=True)
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(str(os.getpid()))
        mine = True
        break
    try:
        yield
    finally:
        if mine:
            path.unlink(missing_ok=True)
