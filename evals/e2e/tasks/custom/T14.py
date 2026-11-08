"""Custom checks for T14: the reply gives the reason the check runs inside the lock."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "text_review_shared.py"
    module = types.ModuleType("text_review_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


OUT = "out/review-reply.txt"
REASON = re.compile(r"동시|경쟁|race|둘 다|두 (?:요청|스레드)|여러 (?:요청|스레드)|원자|atomic|한꺼번에", re.IGNORECASE)


def gives_reason(ctx):
    text = shared(ctx).text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    hit = REASON.search(text)
    return bool(hit), f"reason found: {hit.group(0)}" if hit else "the reply gives no reason about concurrent calls", {}


def text_review_clean(ctx):
    helper = shared(ctx)
    return helper.review(ctx, "review-reply", helper.existing(ctx, OUT), rules="docs/writing-rules.md",
                         sources=("review/comment-1.txt", "inventory/ratelimit.py"))


def ran_text_review(ctx):
    return shared(ctx).ran_text_review(ctx)
