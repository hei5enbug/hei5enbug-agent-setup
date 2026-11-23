"""Custom checks for T29: a review reply keeps the names of the added tests that the rules require."""

from __future__ import annotations

import types
from pathlib import Path

OUT = "out/review-reply.txt"
TESTS = ("test_demo_alpha", "test_demo_beta", "test_demo_gamma")


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "identifier_lists_shared.py"
    module = types.ModuleType("identifier_lists_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def first_review_keeps_test_names(ctx):
    helper = shared(ctx)
    payload, reason = helper.first_review(ctx)
    if payload is None:
        return False, reason, {}
    stopped = helper.reached_reviewer(payload, "review-reply")
    if stopped:
        return False, stopped, {}
    removable = helper.quoting(payload, TESTS, "removable")
    detail = f"removable finding on a required test name: {removable}" if removable else "the reviewer kept the test names"
    return not removable, detail, {"removable": removable}


def all_test_names_kept(ctx):
    text = shared(ctx).read(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    missing = [name for name in TESTS if name not in text]
    return not missing, "all three added tests are named" if not missing else f"test name missing: {missing}", {}
