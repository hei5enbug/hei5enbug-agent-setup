"""Custom checks for T26: the commit message leaves out the reviewing model and its subject names the parser change."""

from __future__ import annotations

import re
import types
from pathlib import Path

MODEL = re.compile(r"demo-model-x", re.IGNORECASE)


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "text_review_shared.py"
    module = types.ModuleType("text_review_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def message(ctx):
    return ctx.git("log", "-1", "--format=%B", f"{ctx.base}..HEAD").strip()


def message_without_model(ctx):
    text = message(ctx)
    if not text:
        return False, "no commit was made", {}
    hit = MODEL.search(text)
    return not hit, "neither the subject nor the body names the model" if not hit else "the message names the model", {}


def subject_names_parser(ctx):
    subject = message(ctx).splitlines()[0] if message(ctx) else ""
    return "parser" in subject.lower(), f"subject: {subject!r}", {}


def ran_text_review(ctx):
    return shared(ctx).ran_text_review(ctx)
