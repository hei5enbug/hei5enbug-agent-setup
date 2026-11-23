"""Custom checks for T49."""

from __future__ import annotations

import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "agreement_shared.py"
    module = types.ModuleType("agreement_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def approved_before_edit(ctx):
    return shared(ctx).approved_before_edit(ctx)


def approved_holds_answers(ctx):
    return shared(ctx).approved_specification_holds_answers(ctx, "T49.json")
