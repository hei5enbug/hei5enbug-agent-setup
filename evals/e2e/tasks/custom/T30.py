"""Custom checks for T30: a pull request description cuts a list of files that its diff already shows."""

from __future__ import annotations

import types
from pathlib import Path

OUT = "out/pr-description.txt"
FILES = ("demo_a.py", "demo_b.py", "demo_c.py")
BEHAVIOR = "empty name"


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "identifier_lists_shared.py"
    module = types.ModuleType("identifier_lists_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def first_review_cuts_file_list(ctx):
    helper = shared(ctx)
    payload, reason = helper.first_review(ctx)
    if payload is None:
        return False, reason, {}
    stopped = helper.reached_reviewer(payload, "pr-description")
    if stopped:
        return False, stopped, {}
    removable = helper.quoting(payload, FILES, "removable")
    detail = "the reviewer reported the file list as removable" if removable else "no removable finding quotes the file list"
    return bool(removable), detail, {"removable": removable}


def file_list_cut(ctx):
    text = shared(ctx).read(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    listed = [line.strip()[:100] for line in text.splitlines() if all(name in line for name in FILES)]
    if listed:
        return False, f"a line still names all three files: {listed}", {}
    if BEHAVIOR not in text.lower():
        return False, "the behavior change is missing", {}
    return True, "the file list is cut and the behavior change is stated", {}
