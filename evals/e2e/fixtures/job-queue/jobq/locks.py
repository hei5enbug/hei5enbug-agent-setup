from __future__ import annotations

import fcntl
from pathlib import Path


class LockBusy(Exception):
    """A non-blocking lock was already held."""


class FileLock:
    def __init__(self, path: Path, blocking: bool = True) -> None:
        self.path = Path(path)
        self.blocking = blocking
        self._handle = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(self.path, "a+")
        flags = fcntl.LOCK_EX | (0 if self.blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(self._handle, flags)
        except BlockingIOError as error:
            self._handle.close()
            self._handle = None
            raise LockBusy(str(self.path)) from error
        return self

    def __exit__(self, *_exc) -> None:
        if self._handle is not None:
            fcntl.flock(self._handle, fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None
