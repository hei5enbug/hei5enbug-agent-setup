"""Custom checks for T31: a comment that names a division by its title and no number for two things."""

from __future__ import annotations

import re
import types
from pathlib import Path

OUT = "out/ticket-comment-demo-l.txt"
DIVISION = "Rollout"
ITEMS = {1: "Schema extension", 2: "Backfill", 3: "Cutover"}


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "stage_titles.py"
    module = types.ModuleType("stage_titles")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def division_named_by_title(ctx):
    helper = shared(ctx)
    text = helper.text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    if not helper.has_title(text, DIVISION):
        return False, f"the division is not named {DIVISION}", {}
    alone = [reference for reference, _, nearby in helper.references(text, helper.DIVISION_WORDS)
             if not helper.has_title(nearby, DIVISION)]
    return not alone, f"division named by number alone: {alone}" if alone else "the division is named by its title", {
        "alone": alone}


def item_keeps_title_with_number(ctx):
    helper = shared(ctx)
    text = helper.text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    paired = (1, 1) in helper.title_numbers(text, ITEMS)
    return paired, "item 1 keeps its title with its number" if paired else "item 1 is not written with its title and number", {}


def no_number_names_two_things(ctx):
    helper = shared(ctx)
    text = helper.text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    divisions = {number for _, numbers, _ in helper.references(text, helper.DIVISION_WORDS) for number in numbers}
    items = {written for written, _ in helper.title_numbers(text, ITEMS)}
    shared_numbers = sorted(divisions & items)
    return not shared_numbers, f"number {shared_numbers} names a division and an item" if shared_numbers else \
        "no number names two things", {"shared": shared_numbers}
