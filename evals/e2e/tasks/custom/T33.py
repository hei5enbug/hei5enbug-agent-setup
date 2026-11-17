"""Custom checks for T33: the review of a description under rules that ask for no names cuts the list of changed files."""

from __future__ import annotations

import types
from pathlib import Path

DRAFT = "pr-draft-demo-i.md"
NAMES = ("demo_a.py", "demo_b.py", "demo_c.py")


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "review_runs.py"
    module = types.ModuleType("review_runs")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def reached_reviewer(ctx):
    payload, detail = shared(ctx).first_review(ctx, DRAFT)
    return payload is not None, detail, {}


def item_removable(ctx):
    helper = shared(ctx)
    payload, detail = helper.first_review(ctx, DRAFT)
    if payload is None:
        return False, detail, {}
    cut = helper.removable_quoting(payload, NAMES)
    return bool(cut), "the list of changed files is reported as removable" if cut else "no removable finding quotes the list of changed files", {
        "findings": payload["findings"]}
