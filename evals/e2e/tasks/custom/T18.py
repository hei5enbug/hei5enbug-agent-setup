"""Custom checks for T18: the paragraph that restates the table is gone while the table and the facts stay."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "text_review_shared.py"
    module = types.ModuleType("text_review_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


OUT = "out/chat-message.txt"
RESTATEMENT = re.compile(r"위 표에서 보듯|세션 만료 시간이 60분으로")
TABLE_ROWS = (r"재시도 3회", r"CSV 내보내기", r"30분\s*(?:→|->)\s*60분")
FACTS = (r"10시", r"5분")


def restatement_removed(ctx):
    text = shared(ctx).text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    hit = RESTATEMENT.search(text)
    return not hit, f"the restating paragraph is still there: {hit.group(0)}" if hit else "the paragraph is gone", {}


def kept_content(ctx):
    text = shared(ctx).text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    missing = [pattern for pattern in (*TABLE_ROWS, *FACTS) if not re.search(pattern, text)]
    return not missing, f"missing: {missing}" if missing else "table rows and schedule facts kept", {"missing": missing}


def text_review_clean(ctx):
    helper = shared(ctx)
    return helper.review(ctx, "chat-message", helper.existing(ctx, OUT), rules="docs/writing-rules.md",
                         sources=("notes/release-draft.txt",))


def ran_text_review(ctx):
    return shared(ctx).ran_text_review(ctx)
