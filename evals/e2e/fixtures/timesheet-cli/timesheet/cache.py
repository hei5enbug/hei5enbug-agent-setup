"""A small in-process cache whose values expire after a fixed number of seconds."""

from __future__ import annotations

import time
from typing import Any, Callable


class TtlCache:
    def __init__(self, ttl_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._items: dict[str, tuple[float, Any]] = {}

    def get_or_load(self, key: str, loader: Callable[[], Any]) -> Any:
        now = self._clock()
        held = self._items.get(key)
        if held is not None and now - held[0] < self.ttl_seconds:
            return held[1]
        value = loader()
        self._items[key] = (now, value)
        return value

    def clear(self) -> None:
        self._items.clear()
