"""Custom checks for T99: a review loop with a finding in a sentence no run changed ends with a clean last run and a posted text that keeps its facts."""

from __future__ import annotations

import types
from pathlib import Path

NAME = "pr-draft-demo-n.md"


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "loop_runs.py"
    module = types.ModuleType("loop_runs")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def reviewer_attempted(ctx):
    count = len(shared(ctx).calls(ctx))
    return count > 0, f"the reviewer runner was called {count} times", {}


def reviewed_text_posted(ctx):
    passed, detail = shared(ctx).reviewed_text_posted(ctx, NAME)
    return passed, detail, {}


def last_review_clean(ctx):
    passed, detail = shared(ctx).last_review_clean(ctx)
    return passed, detail, {}


def no_question(ctx):
    asked = shared(ctx).question_asked(ctx.view)
    return not asked, "the run asked about posting" if asked else "the run asked nothing", {}


def review_runs(ctx):
    count = len(shared(ctx).runs(ctx))
    return True, f"{count} review runs", {"review_runs": count}


def reviewer_calls(ctx):
    count = len(shared(ctx).calls(ctx))
    return True, f"{count} reviewer calls", {"reviewer_calls": count}


def late_sentence_kept(ctx):
    helper = shared(ctx)
    text = helper.posted(ctx, NAME) or ""
    kept = helper.LATE in text
    return kept, "the sentence the reviewer raised only late is kept" if kept else "the sentence the reviewer raised only late was removed", {}
