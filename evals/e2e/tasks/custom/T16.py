"""Custom checks for T16: the comment reports the third completion criterion, which the draft left out."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "text_review_shared.py"
    module = types.ModuleType("text_review_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


OUT = "out/ticket-comment.txt"
THIRD_CRITERION = re.compile(r"수신(?:을)? 거부|opted out", re.IGNORECASE)


def third_criterion_present(ctx):
    text = shared(ctx).text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    hit = THIRD_CRITERION.search(text)
    return bool(hit), "third criterion reported" if hit else "the third criterion is missing", {}


def text_review_clean(ctx):
    helper = shared(ctx)
    return helper.review(ctx, "ticket-comment", helper.existing(ctx, OUT), rules="docs/writing-rules.md",
                         sources=("notes/request-demo-a.txt", "notes/verification-demo-a.txt",
                                  "notes/comment-draft-demo-a.txt"))


def ran_text_review(ctx):
    return shared(ctx).ran_text_review(ctx)
