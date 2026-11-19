"""Custom checks for T83: a two-column profile that stacks at 375 px without sideways overflow."""

from __future__ import annotations

import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "ui_shared.py"
    module = types.ModuleType("ui_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


MODULE = "src/Profile.tsx"


def one(ctx, width: str, test_id: str):
    found = shared(ctx).boxes(ctx, MODULE, width, test_id)
    return found[0] if len(found) == 1 else None


def pair(ctx, width: str):
    return one(ctx, width, "col-left"), one(ctx, width, "col-right")


def columns_side_by_side_1280(ctx):
    left, right = pair(ctx, "1280")
    if left is None or right is None:
        return False, "col-left and col-right must each exist once at 1280 px", {}
    ok = shared(ctx).side_by_side(left, right)
    return ok, f"1280 px: left {round(left['left'])}-{round(left['right'])}, right {round(right['left'])}-{round(right['right'])}", {}


def columns_stack_375(ctx):
    left, right = pair(ctx, "375")
    if left is None or right is None:
        return False, "col-left and col-right must each exist once at 375 px", {}
    ok = shared(ctx).stacked(left, right) and left["width"] > 0 and right["width"] > 0
    return ok, f"375 px: left bottom {round(left['bottom'])}, right top {round(right['top'])}", {}


def no_overflow_1280(ctx):
    return shared(ctx).overflow_free(ctx, MODULE, "1280")


def no_overflow_375(ctx):
    return shared(ctx).overflow_free(ctx, MODULE, "375")


def content_kept(ctx):
    left, right = pair(ctx, "1280")
    if left is None or right is None:
        return False, "the columns are missing", {}
    missing = [word for word in ("Mina Park", "About") if word not in left["text"]]
    missing += [word for word in ("Activity", "Downloaded the March invoice") if word not in right["text"]]
    return not missing, f"missing from the columns: {missing}" if missing else "cards kept in their columns", {}


def renders(ctx):
    return shared(ctx).renders(ctx, MODULE)


def routing(ctx):
    return shared(ctx).routing(ctx, "designer")
