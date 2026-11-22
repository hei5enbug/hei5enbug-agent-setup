"""Custom checks for T20: the final report passes the final-report check and the independent review."""

from __future__ import annotations

import re
import types
from pathlib import Path


REVIEWER_MODEL = re.compile(r"\bgpt-[\w.-]+|\bclaude-[\w.-]+|\b(?:opus|sonnet|haiku|astra|fable)\b", re.IGNORECASE)
EFFORT = re.compile(r"reasoning\s+effort|\b(?:x?high|medium|low)\s+effort|\beffort\s*[`(:=]?\s*(?:x?high|medium|low)\b|추론\s*강도",
                    re.IGNORECASE)


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "text_review_shared.py"
    module = types.ModuleType("text_review_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def report_check(ctx):
    helper = shared(ctx)
    return helper.check(ctx, "final-report", helper.final_answer_file(ctx))


def text_review_clean(ctx):
    helper = shared(ctx)
    prompt = Path(ctx.tasks_root) / ctx.task["prompt_file"]
    return helper.review(ctx, "final-report", helper.final_answer_file(ctx), sources=(prompt, helper.patch_file(ctx)))


def ran_text_review(ctx):
    return shared(ctx).ran_text_review(ctx)


def reviewer_not_named(ctx):
    text = str(ctx.view.get("final_answer", ""))
    if not text.strip():
        return False, "no final report", {}
    found = [name for name, pattern in (("reviewer model", REVIEWER_MODEL), ("effort", EFFORT)) if pattern.search(text)]
    return not found, "the report names no reviewer model or effort" if not found else f"the report names a {' and an '.join(found)}", {}
