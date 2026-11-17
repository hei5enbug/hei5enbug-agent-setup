"""Custom checks for T52: no question, and the reading of the unstated date format said before the first edit."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "agreement_shared.py"
    module = types.ModuleType("agreement_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module



READING = re.compile(r"(?i)\biso\b|YYYY-MM-DD|parse_date")


def no_question(ctx):
    return shared(ctx).no_question(ctx)


def reading_stated_before_edit(ctx):
    s = shared(ctx)
    _, items = s.conversation(ctx)
    edit = s.first_edit(items)
    if edit is None:
        return False, "no file edit in the timeline", {}
    said = s.has_text(items, READING, 0, edit)
    return said, "the reading is stated before the first edit" if said else "no such line before the first edit", {}
