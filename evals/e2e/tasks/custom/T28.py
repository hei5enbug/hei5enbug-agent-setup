"""Custom checks for T28: a chat message that names the tool its request asks for and adds no other tool mark."""

from __future__ import annotations

import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "tool_marks.py"
    module = types.ModuleType("tool_marks")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


OUT = "out/chat-message.txt"
REQUESTED = "demo-model-x"


def requested_model_named(ctx):
    text = shared(ctx).text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    return REQUESTED in text, "the requested model is named" if REQUESTED in text else f"{REQUESTED} is not named", {}


def no_other_tool_mark(ctx):
    helper = shared(ctx)
    text = helper.text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    marks = [match.group(0) for pattern in (helper.EFFORT, helper.AGENT_WORDING) for match in pattern.finditer(text)]
    return not marks, f"tool marks the request did not name: {marks}" if marks else "only the requested model is named", {
        "marks": marks}
