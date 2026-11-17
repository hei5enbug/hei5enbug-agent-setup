"""Custom checks for T29: a comment that names the stages of a procedure by their titles, in order, and never by number alone."""

from __future__ import annotations

import types
from pathlib import Path

OUT = "out/ticket-comment-demo-j.txt"
PROCEDURE = {0: "Check and build", 1: "Add columns", 2: "Load data", 3: "Compare", 4: "Enable reads",
             5: "Enable writes", 6: "Watch", 7: "Remove old path", 8: "Confirm"}
NAMED = [PROCEDURE[number] for number in (0, 3, 4, 5, 6, 7, 8)]


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "stage_titles.py"
    module = types.ModuleType("stage_titles")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def stages_named_in_order(ctx):
    helper = shared(ctx)
    text = helper.text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    missing = helper.missing_in_order(text, NAMED)
    return not missing, f"titles missing or out of order: {missing}" if missing else "stages 0 and 3 to 8 are named in order", {
        "missing": missing}


def no_stage_by_number_alone(ctx):
    helper = shared(ctx)
    text = helper.text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    alone = helper.number_alone(text, PROCEDURE)
    return not alone, f"stages named by number alone: {alone}" if alone else "no stage is named by number alone", {
        "alone": alone}


def titles_match_numbers(ctx):
    helper = shared(ctx)
    text = helper.text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    wrong = helper.wrong_numbers(text, PROCEDURE)
    return not wrong, f"numbers beside a title of another stage: {wrong}" if wrong else "every number matches its title", {
        "wrong": wrong}
