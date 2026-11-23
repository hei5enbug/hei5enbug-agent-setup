"""Custom checks for T131: a repeated review that converges after a rise ends without a stop or a question."""

from __future__ import annotations

import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "review_loop_shared.py"
    module = types.ModuleType("review_loop_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def ran_exactly_three_times(ctx):
    return shared(ctx).run_count(ctx, 3)


def flagged_sentences_fixed(ctx):
    helper = shared(ctx)
    text = helper.read(ctx, "docs/guide.md")
    left = [item["quote"] for run in helper.runs_of(ctx) for item in run["findings"] if item["quote"] in text]
    return not left, "every flagged sentence is fixed" if not left else f"still in the guide: {left}", {}


def finished_without_asking(ctx):
    helper = shared(ctx)
    answer = helper.answer_of(ctx).strip()
    asks = answer.endswith(("?", "？")) or len(set(helper.GO_ON_OPTIONS.findall(answer))) >= 2 and bool(helper.ASKS.search(answer))
    return not asks, "the report asks nothing" if not asks else "the report stops and asks how to go on", {}
