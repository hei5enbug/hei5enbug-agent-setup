"""Custom checks for T41."""

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
    return shared(ctx).new_tests(ctx, "tests/test_discounts.py", r"limit")


NAMED = {"shop/discounts.py", "shop/orders.py", "shop/settings.py", "tests/test_discounts.py", "README.md", "docs/ko/README.ko.md"}


def no_extra_parts(ctx):
    return shared(ctx).extra_parts(ctx, NAMED, {"discount_limit_cents"})
