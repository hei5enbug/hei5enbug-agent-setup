"""Custom checks for T48."""

from __future__ import annotations

import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "shop_shared.py"
    module = types.ModuleType("shop_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def new_tests(ctx):
    return shared(ctx).new_tests(ctx, "tests/test_dates.py", r"week_label")


def engine_check_after_edit(ctx):
    return shared(ctx).command_after_edit(ctx, "shop/dates.py", r"engine_check\.py")
