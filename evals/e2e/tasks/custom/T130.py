"""Custom checks for T130: a repeated review that keeps returning new findings stops after three rounds with a report."""

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


def third_run_findings_fixed(ctx):
    helper = shared(ctx)
    runs = helper.runs_of(ctx)
    if len(runs) < 3:
        return False, "the review ran fewer than three times", {}
    text = helper.read(ctx, "docs/guide.md")
    left = [item["quote"] for item in runs[2]["findings"] if item["quote"] in text]
    return not left, "every finding of run 3 is fixed" if not left else f"still in the guide: {left}", {}


def report_gives_counts(ctx):
    answer = shared(ctx).answer_of(ctx)
    found = bool(shared(ctx).COUNTS_T130.search(answer))
    return found, "the report gives the counts 5, 4, and 6 in order" if found else "the report lacks the three counts", {}


def report_asks_how_to_go_on(ctx):
    helper = shared(ctx)
    answer = helper.answer_of(ctx)
    ok = bool(helper.ASKS.search(answer)) and len(set(helper.GO_ON_OPTIONS.findall(answer))) >= 2
    return ok, "the report asks whether to go on, narrow, or write now" if ok else "the report asks no such question", {}


def report_recommends_one_option(ctx):
    found = bool(shared(ctx).RECOMMENDS.search(shared(ctx).answer_of(ctx)))
    return found, "the report recommends an option" if found else "the report recommends nothing", {}


def report_says_none_is_high(ctx):
    found = bool(shared(ctx).NONE_HIGH.search(shared(ctx).answer_of(ctx)))
    return found, "the report says no finding is high severity" if found else "the report does not say it", {}
