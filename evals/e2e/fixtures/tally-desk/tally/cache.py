"""A small time-to-live cache for functions of one argument."""

from __future__ import annotations

import time
from functools import wraps
from typing import Any, Callable


def ttl_cached(seconds: float) -> Callable[[Callable[[str], Any]], Callable[[str], Any]]:
    """Keep each result of a one-argument function for `seconds`; `cache_clear()` forgets them all."""

    def decorate(function: Callable[[str], Any]) -> Callable[[str], Any]:
        kept: dict[str, tuple[float, Any]] = {}

        @wraps(function)
        def wrapper(key: str) -> Any:
            hit = kept.get(key)
            if hit is not None and time.monotonic() - hit[0] < seconds:
                return hit[1]
            value = function(key)
            kept[key] = (time.monotonic(), value)
            return value

        wrapper.cache_clear = kept.clear  # type: ignore[attr-defined]
        return wrapper

    return decorate
