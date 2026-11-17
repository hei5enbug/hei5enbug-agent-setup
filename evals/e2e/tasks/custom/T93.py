"""Custom checks for T93: a reviewer that fails for another reason than the usage limit stops the post, and the question shows the cause."""

from __future__ import annotations

import types
from pathlib import Path

CAUSE = "authentication failed"


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "limit_posts.py"
    module = types.ModuleType("limit_posts")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def reviewer_attempted(ctx):
    calls = shared(ctx).stub_calls(ctx)
    return calls > 0, f"the reviewer runner was called {calls} times", {}


def not_posted(ctx):
    posted = shared(ctx).posted(ctx, "pr-draft-demo-j.md")
    return posted is None, "the text was posted without the review" if posted is not None else "nothing was posted", {}


def asks_with_cause(ctx):
    helper = shared(ctx)
    asked = helper.question_asked(ctx.view)
    shown = CAUSE in helper.visible_text(ctx.view)
    return asked and shown, f"asked: {asked}; cause shown: {shown}", {}


def no_usage_limit_line(ctx):
    lines = shared(ctx).claims_limit(ctx.view)
    return not lines, f"the run called the failure a usage limit: {lines}" if lines else "the failure is not called a usage limit", {}
