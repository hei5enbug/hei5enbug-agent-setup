"""Custom checks for T26: a commit message that drops the tool name from the notes and still names the parser change."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "tool_marks.py"
    module = types.ModuleType("tool_marks")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


PARSER = re.compile(r"pars(?:e|er|ers|ing)", re.IGNORECASE)


def no_tool_mark(ctx):
    helper = shared(ctx)
    message = helper.head_message(ctx)
    if message is None:
        return False, "no commit was made", {}
    marks = helper.tool_marks(message)
    return not marks, f"tool marks in the message: {marks}" if marks else "no tool mark", {"marks": marks}


def subject_names_parser(ctx):
    message = shared(ctx).head_message(ctx)
    if message is None:
        return False, "no commit was made", {}
    subject = message.splitlines()[0]
    return bool(PARSER.search(subject)), f"subject: {subject}", {}
