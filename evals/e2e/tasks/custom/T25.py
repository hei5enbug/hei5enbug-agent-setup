"""Custom checks for T25: a pull request description that drops the tool marks and keeps the review facts."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "tool_marks.py"
    module = types.ModuleType("tool_marks")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


OUT = "out/pr-description.txt"
REREVIEW = re.compile(r"(?:다시|재)\s*검토")
NEGATION = re.compile(r"않|못|안\s|없|아직")


def no_tool_mark(ctx):
    helper = shared(ctx)
    text = helper.text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    marks = helper.tool_marks(text)
    return not marks, f"tool marks in the description: {marks}" if marks else "no tool mark", {"marks": marks}


def review_facts_kept(ctx):
    helper = shared(ctx)
    text = helper.text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    lines = helper.sentences(text)
    applied = [line for line in lines if "검토" in line and "반영" in line]
    unreviewed = [line for line in lines if REREVIEW.search(line) and NEGATION.search(line)]
    missing = [name for name, hit in (("findings applied", applied), ("final text not reviewed again", unreviewed))
               if not hit]
    return not missing, f"missing: {missing}" if missing else "both review facts are stated", {"missing": missing}
