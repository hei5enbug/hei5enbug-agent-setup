"""Custom checks for T19: the restart fact stays, the sentence nobody acts on goes, and the page fits its budget."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "text_review_shared.py"
    module = types.ModuleType("text_review_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


OUT = "out/wiki-page.txt"
BUDGET = 1500
RESTART_FACT = re.compile(r"demo-api[^\n.]{0,30}재시작")
UNNEEDED = re.compile(r"demo-api는 demo-flag[^\n.]{0,20}읽지")


def restart_fact_kept(ctx):
    text = shared(ctx).text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    hit = RESTART_FACT.search(text)
    return bool(hit), "restart fact kept" if hit else "the demo-api restart fact is missing", {}


def unneeded_sentence_removed(ctx):
    text = shared(ctx).text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    hit = UNNEEDED.search(text)
    return not hit, "the does-not-read sentence is still there" if hit else "the sentence is gone", {}


def within_budget(ctx):
    text = shared(ctx).text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    length = len(text.strip())
    return length <= BUDGET, f"{length} characters, budget {BUDGET}", {"length": length}


def text_review_clean(ctx):
    helper = shared(ctx)
    return helper.review(ctx, "shared-document", helper.existing(ctx, OUT), rules="docs/writing-rules.md",
                         sources=("notes/wiki-draft.txt",), budget=BUDGET)


def ran_text_review(ctx):
    return shared(ctx).ran_text_review(ctx)
