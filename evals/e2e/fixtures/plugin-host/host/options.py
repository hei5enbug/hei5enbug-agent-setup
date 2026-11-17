from __future__ import annotations

import json
import os
from pathlib import Path


def load_options(root: Path) -> dict:
    return json.loads((Path(root) / "plugin.json").read_text(encoding="utf-8"))["userConfig"]


def option_value(name: str, environ: dict | None = None) -> str:
    source = os.environ if environ is None else environ
    return str(source.get(f"HOST_OPTION_{name.upper()}", "")).strip().lower()
