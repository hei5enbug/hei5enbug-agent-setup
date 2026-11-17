"""Custom checks for T46: two deliverables, two open decisions, and a specification approved before any file changes."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "agreement_shared.py"
    module = types.ModuleType("agreement_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module



def approved_specification(ctx):
    exchanges, _ = shared(ctx).conversation(ctx)
    held = shared(ctx).approvals(exchanges, True)
    return bool(held), f"{len(held)} approved request(s); the scripted user approves only a specification that holds both answers", {}


def no_edit_before_approval(ctx):
    s = shared(ctx)
    exchanges, items = s.conversation(ctx)
    held = s.approvals(exchanges, True)
    if not held:
        return False, "no approved specification", {}
    position, edit = s.where(items, held[0]), s.first_edit(items)
    return edit is None or (position is not None and position < edit), f"approval at {position}, first edit at {edit}", {}
