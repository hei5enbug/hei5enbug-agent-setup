"""Settings: a default here, overridden by the environment variable SHOP_<NAME>."""

from __future__ import annotations

import os

DEFAULTS = {
    "tax_percent": 8,
}


def get(name: str) -> int:
    raw = os.environ.get(f"SHOP_{name.upper()}")
    return int(raw) if raw is not None else DEFAULTS[name]
