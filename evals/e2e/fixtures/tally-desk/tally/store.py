"""Entries file access."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_ENTRIES = "data/entries.json"


def entries_path() -> Path:
    return Path(os.environ.get("TALLY_DATA", DEFAULT_ENTRIES))


def load_entries() -> list[dict[str, Any]]:
    with entries_path().open(encoding="utf-8") as stream:
        return list(json.load(stream)["entries"])
