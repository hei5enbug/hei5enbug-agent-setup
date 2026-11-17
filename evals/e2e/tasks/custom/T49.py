"""Custom checks for T49: a requirements agreement asked for by name, approved, and then a stop with no file edit."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "agreement_shared.py"
    module = types.ModuleType("agreement_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module



NEXT = re.compile(r"(?i)next|다음|진행|구현|계획|plan|implement")


def approved_specification(ctx):
    exchanges, _ = shared(ctx).conversation(ctx)
    held = shared(ctx).approvals(exchanges, True)
    return bool(held), f"{len(held)} approved request(s)", {}


def stops_and_asks_next(ctx):
    exchanges, _ = shared(ctx).conversation(ctx)
    approved = [i for i, item in enumerate(exchanges) if item.get("approval") is True]
    if not approved:
        return False, "no approved specification", {}
    after = [item for item in exchanges[approved[0] + 1:] if item.get("ended")]
    asked = [item for item in after if NEXT.search(item["question"])]
    return bool(asked), f"{len(after)} question(s) after the approval, {len(asked)} ask what to do next", {}


def no_file_edit(ctx):
    _, items = shared(ctx).conversation(ctx)
    edit = shared(ctx).first_edit(items)
    return edit is None and not ctx.changes, f"first edit at {edit}; changed paths: {sorted(ctx.changes)}", {}
