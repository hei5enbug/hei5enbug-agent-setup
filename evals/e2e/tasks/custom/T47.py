"""Custom check for T47: two deliverables with every decision stated, so no agreement step and no question."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "agreement_shared.py"
    module = types.ModuleType("agreement_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module



AGREEMENT_HEADING = re.compile(r"(?im)^#{1,6}\s*.*(rejected alternatives|completion criteria|기각한 대안|완료 기준)")


def no_agreement_no_question(ctx):
    s = shared(ctx)
    quiet, detail, data = s.no_question(ctx)
    drafted = any(AGREEMENT_HEADING.search(text) for text in ctx.view.get("assistant_texts", []))
    return quiet and not drafted, f"{detail}; specification headings shown: {drafted}", data
