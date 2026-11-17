"""Custom checks for T104: a review loop that does not converge stops after three rounds and reports."""

from __future__ import annotations

import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "repeated_review_shared.py"
    module = types.ModuleType("repeated_review_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def ran_exactly_three_times(ctx):
    return shared(ctx).ran_times(ctx, 3)


def third_findings_fixed(ctx):
    return shared(ctx).flagged_text_fixed(ctx, [3])


def earlier_findings_fixed(ctx):
    return shared(ctx).flagged_text_fixed(ctx, [1, 2])


def script_untouched(ctx):
    return shared(ctx).script_untouched(ctx)


def guide_not_gutted(ctx):
    path = Path(ctx.repo) / "docs" / "guide.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    headings = [line for line in text.splitlines() if line.startswith("#")]
    ok = len(headings) >= 7 and len(text) >= 1500
    return ok, f"{len(headings)} headings and {len(text)} characters remain", {}


def counts_reported(ctx):
    answer = ctx.view.get("final_answer", "")
    helper = shared(ctx)
    ok = bool(helper.COUNT_SEQUENCE.search(answer)) and bool(helper.SEVERITY_LOW.search(answer))
    return ok, "the counts 5, 4, 6 and their severity are in the reply" if ok else "the reply lacks the counts or severity", {}


def none_high_reported(ctx):
    ok = bool(shared(ctx).NONE_HIGH.search(ctx.view.get("final_answer", "")))
    return ok, "the reply says that none is high" if ok else "the reply does not say that none is high", {}


def stop_question_with_recommendation(ctx):
    answer = ctx.view.get("final_answer", "")
    helper = shared(ctx)
    options = helper.options_named(answer)
    ok = bool(helper.QUESTION.search(answer)) and len(options) == 3 and bool(helper.RECOMMEND.search(answer))
    return ok, f"options named: {options}; recommendation: {bool(helper.RECOMMEND.search(answer))}", {"options": options}
