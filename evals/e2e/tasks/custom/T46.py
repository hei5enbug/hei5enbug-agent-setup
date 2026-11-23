"""Custom checks for T46."""

from __future__ import annotations

import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "shop_shared.py"
    module = types.ModuleType("shop_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def regression_test_added(ctx):
    return shared(ctx).reproducing_test(ctx)
