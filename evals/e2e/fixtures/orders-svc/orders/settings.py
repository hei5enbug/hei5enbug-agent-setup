"""Reads `config/settings.toml`, or the file `ORDERS_SETTINGS` names."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "config" / "settings.toml"


def load() -> dict[str, Any]:
    with Path(os.environ.get("ORDERS_SETTINGS") or DEFAULT_SETTINGS_PATH).open("rb") as handle:
        return tomllib.load(handle)


def get(section: str, key: str) -> Any:
    return load()[section][key]
