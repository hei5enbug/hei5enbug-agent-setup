"""Custom checks for T43."""

from __future__ import annotations

import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "shop_shared.py"
    module = types.ModuleType("shop_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def files_changed(ctx):
    return shared(ctx).files_changed(ctx)


def new_tests(ctx):
    return shared(ctx).new_tests(ctx, "tests/test_cli.py", r"export")
