"""Custom checks for T66: a chat message names the division by its title and keeps each item's title with its number."""

from __future__ import annotations

import re
import types
from pathlib import Path

OUT = "out/chat-message.txt"
DIVISION = "Rollout"
ITEMS = {1: "Schema extension", 2: "Backfill", 3: "Reads cutover"}
PHASE_BEFORE = re.compile(r"phases?\s*$", re.IGNORECASE)


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "stage_names_shared.py"
    module = types.ModuleType("stage_names_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def title_of(text, match):
    if PHASE_BEFORE.search(text[:match.start()]):
        return DIVISION
    return ITEMS.get(int(match.group(0)))


def division_named(ctx):
    helper = shared(ctx)
    text = helper.read(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    if not helper.has_title(text, DIVISION):
        return False, f"the division is not named {DIVISION}", {}
    alone = [match.group(0) for match in helper.NUMBER.finditer(text)
             if PHASE_BEFORE.search(text[:match.start()]) and not helper.beside_title(text, match, DIVISION)]
    return not alone, "the division is named Rollout" if not alone else f"phase number without its title: {alone}", {}


def item_keeps_title_and_number(ctx):
    helper = shared(ctx)
    text = helper.read(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    found = [match for match in helper.NUMBER.finditer(text)
             if int(match.group(0)) == 1 and not PHASE_BEFORE.search(text[:match.start()])
             and helper.beside_title(text, match, ITEMS[1])]
    return bool(found), "the item keeps its title with its number" if found else f"{ITEMS[1]} has no number 1 beside it", {}


def no_number_alone(ctx):
    helper = shared(ctx)
    text = helper.read(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    alone = helper.numbers_without_title(text, ITEMS, title_of)
    return not alone, "no number stands alone" if not alone else f"number without its title: {alone}", {}
