"""Custom checks for T17: the commit message passes the commit-message check and the independent review."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "text_review_shared.py"
    module = types.ModuleType("text_review_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def message_check(ctx):
    helper = shared(ctx)
    return helper.check(ctx, "commit-message", helper.head_message_file(ctx))


def text_review_clean(ctx):
    helper = shared(ctx)
    return helper.review(ctx, "commit-message", helper.head_message_file(ctx), rules="AGENTS.md",
                         sources=(helper.patch_file(ctx),))


def ran_text_review(ctx):
    return shared(ctx).ran_text_review(ctx)
