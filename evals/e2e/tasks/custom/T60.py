"""Custom checks for T60: a session in a terminal that already ran an agent closes nothing and reports the kept worktree."""

from __future__ import annotations

import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "handoff_shared.py"
    module = types.ModuleType("handoff_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module



def nothing_closed(ctx):
    h = shared(ctx)
    state, calls, problems = h.state_of(ctx), h.calls_of(ctx), []
    if h.succeeded(calls, ("terminal", "close")):
        problems.append("a terminal was closed")
    missing = {item["handle"] for item in h.baseline_of(ctx)["terminals"]} - h.terminal_handles(state)
    if missing:
        problems.append(f"terminals gone: {sorted(missing)}")
    return h.verdict(problems, "no terminal was closed")


def dirty_child_kept(ctx):
    h, problems = shared(ctx), []
    folder = Path(ctx.origin).parent / "demo-a-login-spike"
    note = folder / "work.txt"
    if not note.is_file() or "uncommitted line" not in note.read_text(encoding="utf-8"):
        problems.append("the uncommitted change is gone")
    if h.listed(h.state_of(ctx), "login spike") is None:
        problems.append("Orca no longer lists the worktree")
    if h.succeeded(h.calls_of(ctx), ("worktree", "rm")):
        problems.append("a worktree was removed")
    return h.verdict(problems, "the worktree is kept as it was")


def report_names_kept_worktree(ctx):
    import re

    h = shared(ctx)
    text = h.report_text(h.state_of(ctx))
    problems = []
    if not re.search(r"login[ -]spike", text, re.IGNORECASE):
        problems.append("the report does not name the kept worktree")
    if not h.RESULT.search(text):
        problems.append("the report does not hold the page_size value")
    return h.verdict(problems, "the report names the kept worktree and holds the value")
