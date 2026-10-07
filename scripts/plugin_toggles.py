from __future__ import annotations

import os
from pathlib import Path


OFF_VALUES = {"false", "0", "off", "no"}


def detect_host() -> str:
    root = Path(__file__).resolve().parents[1]
    codex_root = os.environ.get("PLUGIN_ROOT")
    return "codex" if codex_root and Path(codex_root).resolve() == root else "claude"


def variable_name(key: str, host: str) -> str:
    prefix = "HEI5ENBUG_" if host == "codex" else "CLAUDE_PLUGIN_OPTION_"
    return prefix + key.upper()


def enabled(key: str) -> bool:
    """Return False only when the host's toggle for `key` is set to an off value."""
    value = os.environ.get(variable_name(key, detect_host()), "")
    return value.strip().casefold() not in OFF_VALUES
