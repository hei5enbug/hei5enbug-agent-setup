"""Custom checks for T59: the order of cleanup, report, and close in a session whose terminal belongs to the handoff."""

from __future__ import annotations

import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "handoff_shared.py"
    module = types.ModuleType("handoff_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module



def cleanup_report_close_in_order(ctx):
    h, problems = shared(ctx), []
    calls, state = h.calls_of(ctx), h.state_of(ctx)
    problems += h.worktree_gone(ctx, "demo-a-docs-cleanup", "docs-cleanup", "docs cleanup")
    removed = h.succeeded(calls, ("worktree", "rm"))
    sent = [item for item in h.succeeded(calls, ("orchestration", "send")) if h.option(item[1], "--to") == "term_sender"]
    closed = h.succeeded(calls, ("terminal", "close"), terminal="term_demo_a")
    if not removed:
        problems.append("no worktree was removed")
    if not sent:
        problems.append("no report reached term_sender")
    if not closed:
        problems.append("the session's own terminal was not closed")
    if removed and sent and closed:
        if not removed[0][0] < sent[0][0]:
            problems.append("the report was sent before the worktree was removed")
        if not sent[0][0] < closed[0][0]:
            problems.append("the terminal was closed before the report was sent")
        if closed[0][0] != len(calls) - 1:
            problems.append("the session made Orca calls after closing its terminal")
    if "term_sender" not in h.terminal_handles(state):
        problems.append("the sender's terminal is gone")
    return h.verdict(problems, "removed, reported, then closed its own terminal")


def report_holds_result(ctx):
    h = shared(ctx)
    text = h.report_text(h.state_of(ctx))
    return h.verdict([] if h.RESULT.search(text) else ["the report does not hold the page_size value"],
                     "the report holds the value")


def main_clone_kept(ctx):
    h = shared(ctx)
    return h.verdict(h.main_clone_kept(ctx), "the main clone remains")
