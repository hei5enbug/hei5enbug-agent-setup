"""The JSON file that holds the time entries."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import date
from typing import Any, Iterator

from .cache import TtlCache
from .settings import load_settings

LOCK_WAIT_SECONDS = 5.0
CACHE_SECONDS = 3600

_CACHE = TtlCache(ttl_seconds=CACHE_SECONDS)


class StoreError(Exception):
    """The data file cannot be read or locked."""


def _read_file() -> list[dict[str, Any]]:
    path = load_settings().data_file
    if not path.exists():
        return []
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StoreError(f"cannot read {path}: {exc}") from exc
    return entries if isinstance(entries, list) else []


def load() -> list[dict[str, Any]]:
    return _read_file()


def load_cached() -> list[dict[str, Any]]:
    return _CACHE.get_or_load("entries", _read_file)


def clear_cache() -> None:
    _CACHE.clear()


@contextmanager
def locked() -> Iterator[None]:
    """Hold the lock file while the data file changes, so parallel adds never lose an entry."""
    path = load_settings().data_file
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                raise StoreError(f"could not lock the store: {lock}") from None
            time.sleep(0.01)
    try:
        yield
    finally:
        os.close(handle)
        os.unlink(lock)


def save(entries: list[dict[str, Any]]) -> None:
    load_settings().data_file.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    clear_cache()


def add(entry_date: date, project: str, minutes: int) -> dict[str, Any]:
    with locked():
        entries = _read_file()
        entry = {"id": max((item["id"] for item in entries), default=0) + 1, "date": entry_date.isoformat(),
                 "project": project, "minutes": minutes}
        save([*entries, entry])
    return entry


def delete(entry_id: int) -> bool:
    with locked():
        entries = _read_file()
        kept = [item for item in entries if item["id"] != entry_id]
        if len(kept) == len(entries):
            return False
        save(kept)
    return True
