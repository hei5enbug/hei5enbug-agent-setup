"""Custom checks for T105: a review loop whose count rises and then reaches zero finishes without a stop."""

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


def flagged_sentences_fixed(ctx):
    return shared(ctx).flagged_text_fixed(ctx, [1, 2, 3])


def last_run_clean(ctx):
    log = shared(ctx).log_of(ctx)
    ok = bool(log) and not log[-1]["findings"]
    return ok, "the last run returned no findings" if ok else "the last run still returned findings", {}


def script_untouched(ctx):
    return shared(ctx).script_untouched(ctx)


def no_stop_question(ctx):
    answer = ctx.view.get("final_answer", "")
    asked = shared(ctx).asks_whether_to_go_on(answer)
    return not asked, "the reply asks whether to go on" if asked else "the reply asks nothing", {}
