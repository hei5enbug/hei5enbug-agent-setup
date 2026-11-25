"""Custom checks for T66: a chat message names the division and items by their titles."""

from __future__ import annotations

import re
import types
from pathlib import Path

OUT = "out/chat-message.txt"
DIVISION = "Rollout"
ITEMS = {1: "Schema extension", 2: "Backfill", 3: "Reads cutover"}
PHASE_BEFORE = re.compile(r"phases?\s*$", re.IGNORECASE)
BREAK_AFTER_NUMBER = re.compile(r"""[ \t)\]"']*(?:[.!?]\s|\n)""")


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
    title = ITEMS[1]
    if not helper.has_title(text, title):
        return False, f"the item is not named {title}", {}
    for match in helper.NUMBER.finditer(text):
        if int(match.group(0)) != 1:
            continue
        prefix = text[:match.start()]
        beside_item = helper.beside_title(text, match, title)
        beside_division = helper.beside_title(text, match, DIVISION)
        if (beside_item and beside_division and not BREAK_AFTER_NUMBER.match(text, match.end())
                and not prefix.rstrip(" \t").endswith("\n")):
            return False, "one number labels both the division and the item", {}
        if not (beside_item or beside_division or PHASE_BEFORE.search(prefix) or helper.is_quantity(text, match)):
            return False, "the item is named by its number alone", {}
    return True, f"the item is named {title}", {}


def no_number_alone(ctx):
    helper = shared(ctx)
    text = helper.read(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    alone = helper.numbers_without_title(text, ITEMS, title_of)
    return not alone, "no number stands alone" if not alone else f"number without its title: {alone}", {}
