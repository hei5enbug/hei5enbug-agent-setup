"""The JSON data file. Every module reads and writes it through `load` and `save`."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

EMPTY = {"customers": {}, "orders": []}


def load(path: str | os.PathLike[str]) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return json.loads(json.dumps(EMPTY))
    return json.loads(target.read_text(encoding="utf-8"))


def save(path: str | os.PathLike[str], data: dict[str, Any]) -> None:
    target = Path(path)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, target)
