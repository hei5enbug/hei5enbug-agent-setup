"""Custom checks for T94: two texts posted without a question after the usage limit, with one report line and a single reviewer call."""

from __future__ import annotations

import types
from pathlib import Path

NAMES = ("pr-draft-demo-l.md", "comment-draft-demo-k.md")


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "limit_posts.py"
    module = types.ModuleType("limit_posts")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def reviewer_attempted(ctx):
    calls = shared(ctx).stub_calls(ctx)
    return calls > 0, f"the reviewer runner was called {calls} times", {}


def posted_as_is(ctx):
    passed, detail = shared(ctx).posted_as_is(ctx, NAMES)
    return passed, detail, {}


def no_question(ctx):
    asked = shared(ctx).question_asked(ctx.view)
    return not asked, "the run asked about posting" if asked else "the run asked nothing", {}


def limit_line_reported(ctx):
    lines = shared(ctx).limit_lines(ctx.view)
    return len(lines) == 1, f"{len(lines)} lines say the review did not run because of the usage limit", {"lines": lines}


def reviewer_called_once(ctx):
    calls = shared(ctx).stub_calls(ctx)
    return calls == 1, f"the reviewer runner was called {calls} times", {}
