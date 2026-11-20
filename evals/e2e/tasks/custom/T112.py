"""Custom checks for T112: a new invoices screen of three rows that fits at 1280 px and at 375 px."""

from __future__ import annotations

import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "ui_shared.py"
    module = types.ModuleType("ui_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


MODULE = "src/Invoices.tsx"
TOLERANCE_PX, ROWS = 1, 3
EXPECTED = (("March invoice", "$120.00", "Paid"), ("April invoice", "$120.00", "Paid"), ("May invoice", "$135.00", "Due"))


def rows(ctx, width: str):
    return sorted(shared(ctx).boxes(ctx, MODULE, width, "invoice-row"), key=lambda box: (round(box["top"]), box["left"]))


def invoices_listed(ctx):
    found = rows(ctx, "1280")
    if len(found) != ROWS or len(shared(ctx).boxes(ctx, MODULE, "1280", "invoice-list")) != 1:
        return False, f"expected one invoice-list and {ROWS} invoice-row elements, found {len(found)} rows", {}
    missing = [word for row, words in zip(found, EXPECTED) for word in words if word not in row["text"]]
    return not missing, f"missing from the rows: {missing}" if missing else "three invoices with name, amount, and status", {}


def rows_stacked_1280(ctx):
    found = rows(ctx, "1280")
    stacked = len(found) == ROWS and all(lower["top"] >= upper["bottom"] - TOLERANCE_PX for upper, lower in zip(found, found[1:]))
    return stacked, f"{len(found)} rows at 1280 px, one under the other: {stacked}", {}


def rows_visible_375(ctx):
    found = rows(ctx, "375")
    outside = [round(row["right"]) for row in found if row["right"] > 375 + TOLERANCE_PX or row["width"] <= 0]
    return len(found) == ROWS and not outside, f"{len(found)} rows at 375 px; right edges past the screen: {outside}", {}


def no_overflow_1280(ctx):
    return shared(ctx).overflow_free(ctx, MODULE, "1280")


def no_overflow_375(ctx):
    return shared(ctx).overflow_free(ctx, MODULE, "375")


def renders(ctx):
    return shared(ctx).renders(ctx, MODULE)


def routing(ctx):
    return shared(ctx).routing(ctx, "designer")


def designer_xhigh(ctx):
    return shared(ctx).designer_effort(ctx, "xhigh")
