"""Custom checks for T32: the review of a reply whose rules require the added test names does not cut those names."""

from __future__ import annotations

import types
from pathlib import Path

DRAFT = "reply-draft-demo-h.md"
NAMES = ("test_demo_alpha", "test_demo_beta", "test_demo_gamma")


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "review_runs.py"
    module = types.ModuleType("review_runs")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def reached_reviewer(ctx):
    payload, detail = shared(ctx).first_review(ctx, DRAFT)
    return payload is not None, detail, {}


def item_not_removable(ctx):
    helper = shared(ctx)
    payload, detail = helper.first_review(ctx, DRAFT)
    if payload is None:
        return False, detail, {}
    cut = helper.removable_quoting(payload, NAMES)
    return not cut, f"removable findings on the test names: {cut}" if cut else "the test names are not reported as removable", {
        "findings": payload["findings"]}
