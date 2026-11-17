"""Custom checks for T27: a commit message that names the model setting the diff changes."""

from __future__ import annotations

import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "tool_marks.py"
    module = types.ModuleType("tool_marks")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def message_names_new_model(ctx):
    message = shared(ctx).head_message(ctx)
    if message is None:
        return False, "no commit was made", {}
    return "demo-model-y" in message, f"message: {message[:200]}", {}
