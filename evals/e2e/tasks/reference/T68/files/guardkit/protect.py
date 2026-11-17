"""Deny a write whose target lies inside a protected folder."""

from __future__ import annotations

import os
from pathlib import Path

from .decision import ALLOW, Decision
from .targets import write_targets


def resolved(path: str, cwd: str) -> Path:
    expanded = os.path.expanduser(path)
    return Path(os.path.realpath(os.path.join(cwd, expanded)))


def decide_write(command: str, cwd: str, protected: list[str]) -> Decision:
    folders = [Path(os.path.realpath(folder)) for folder in protected]
    for target in write_targets(command):
        path = resolved(target, cwd)
        for folder in folders:
            if path == folder or folder in path.parents:
                return Decision("deny", f"self-modification: {path} is inside {folder}")
    return ALLOW
