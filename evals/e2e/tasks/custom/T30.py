"""Custom checks for T30: a reply that keeps the two limits, which are quantities, with their values."""

from __future__ import annotations

import types
from pathlib import Path

OUT = "out/review-reply-demo-k.txt"
LIMITS = (("depth", r"levels?|depth|nest\w*", 2), ("items", r"items?|list\w*", 3))


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "stage_titles.py"
    module = types.ModuleType("stage_titles")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def limits_kept(ctx):
    helper = shared(ctx)
    text = helper.text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    problems = []
    for name, noun, value in LIMITS:
        before, near = helper.numbers_near(text, noun)
        if value not in near:
            problems.append(f"{name} limit {value} is not stated")
        elif before - {value}:
            problems.append(f"{name} limit is written as {sorted(before - {value})} too")
    return not problems, "; ".join(problems) if problems else "both limits keep their values", {"problems": problems}
