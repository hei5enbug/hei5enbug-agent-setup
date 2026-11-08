"""Custom checks for T13: a pull request description without the ticket key or a list of the new columns."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "text_review_shared.py"
    module = types.ModuleType("text_review_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


OUT = "out/pr-description.txt"
TICKET_KEY = re.compile(r"INV-\d+")
COLUMNS = ("total_quantity", "warehouse_count", "open_order_units", "last_movement_at")
LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def items(text: str) -> list[str]:
    """Each list item with its continuation lines, and every other line on its own."""
    found: list[str] = []
    in_list = False
    for line in text.splitlines():
        if LIST_MARKER.match(line):
            found.append(line)
            in_list = True
        elif in_list and line.strip() and line[:1] in " \t":
            found[-1] += " " + line.strip()
        else:
            found.append(line)
            in_list = False
    return found


def ticket_key_absent(ctx):
    text = shared(ctx).text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    hits = TICKET_KEY.findall(text)
    return not hits, f"ticket key in the body: {hits}" if hits else "no ticket key", {"hits": hits}


def no_column_list(ctx):
    text = shared(ctx).text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    crowded = [item.strip()[:100] for item in items(text) if sum(name in item for name in COLUMNS) >= 3]
    return not crowded, f"an item names three or more new columns: {crowded}" if crowded else "no column list", {
        "crowded": crowded}


def text_review_clean(ctx):
    helper = shared(ctx)
    return helper.review(ctx, "pr-description", helper.existing(ctx, OUT), rules="docs/writing-rules.md",
                         sources=("review/check-log.txt", helper.base_patch_file(ctx)), no_ticket_keys=True)


def ran_text_review(ctx):
    return shared(ctx).ran_text_review(ctx)
