"""Custom checks for T65: a ticket comment names the stages it covers by title, and keeps its limits as numbers."""

from __future__ import annotations

import re
import types
from pathlib import Path

OUT = "out/ticket-comment.txt"
TITLES = {0: "Check and build", 1: "Add columns", 2: "Load data", 3: "Compare", 4: "Enable reads",
          5: "Enable writes", 6: "Watch", 7: "Remove old path", 8: "Confirm"}
COVERED = (0, 3, 4, 5, 6, 7, 8)
DEPTH = re.compile(r"\b2\s+levels?\b|\b(?:depth|nesting)\b[^.]{0,40}(?<![\w.])2(?!\w)", re.IGNORECASE)
COUNT = re.compile(r"\b3\s+items?\b|\bitems?\b[^.]{0,20}(?<![\w.])3(?!\w)", re.IGNORECASE)


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "stage_names_shared.py"
    module = types.ModuleType("stage_names_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def stages_named_in_order(ctx):
    helper = shared(ctx)
    text = helper.read(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    missing = [TITLES[number] for number in COVERED if not helper.has_title(text, TITLES[number])]
    extra = [TITLES[number] for number in (1, 2) if helper.has_title(text, TITLES[number])]
    cursor, misplaced = -1, []
    for number in COVERED:
        after = [at for at in helper.title_positions(text, TITLES[number]) if at > cursor]
        if after:
            cursor = after[0]
        elif TITLES[number] not in missing:
            misplaced.append(TITLES[number])
    problems = {"missing": missing, "not covered but named": extra, "out of order": misplaced}
    problems = {name: value for name, value in problems.items() if value}
    return not problems, "stages 0 and 3 to 8 are named in order" if not problems else str(problems), {}


def no_stage_by_number_alone(ctx):
    helper = shared(ctx)
    text = helper.read(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    alone = helper.numbers_without_title(text, TITLES)
    return not alone, "no stage is named by its number alone" if not alone else f"number without its title: {alone}", {}


def limits_kept(ctx):
    text = shared(ctx).read(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    missing = [name for name, pattern in (("depth of 2 levels", DEPTH), ("3 items", COUNT)) if not pattern.search(text)]
    return not missing, "both limits keep their numbers" if not missing else f"limit lost or changed: {missing}", {}
