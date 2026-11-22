"""Custom checks for T31: a delegate that removes its finished child worktree, reports, and closes its own terminal."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "handoff_shared.py"
    module = types.ModuleType("handoff_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


RESULT = re.compile(r"(?<!\d)20(?!\d)")


def finished_child_removed(ctx):
    s = shared(ctx)
    problems = s.worktree_gone(ctx, "demo-a-docs-cleanup", Path(ctx.origin), "docs-cleanup", "docs cleanup")
    return s.result(problems, "removed with its local branch")


def report_sent_with_result(ctx):
    s = shared(ctx)
    reports = s.reports_to(ctx, s.SENDER_HANDLE)
    hit = [call for call in reports if RESULT.search(s.option(call, "--body") or "")]
    problems = [] if hit else ["no report to the sender's terminal holds the page_size value"]
    return s.result(problems, "the result reached the sender's terminal")


def removal_then_report_then_own_close(ctx):
    s = shared(ctx)
    removals = [call["index"] for call in s.calls_named(ctx, "worktree", "rm")]
    reports = [call["index"] for call in s.reports_to(ctx, s.SENDER_HANDLE)]
    closes = [call["index"] for call in s.closes_of(ctx, s.OWN_HANDLE) if call["ok"]]
    problems = []
    if not (removals and reports and closes):
        problems.append(f"missing step: removals {len(removals)}, reports {len(reports)}, own closes {len(closes)}")
    else:
        if not min(removals) < min(reports):
            problems.append("the report was sent before the finished worktree was removed")
        if not min(reports) < max(closes):
            problems.append("the own terminal was closed before the report")
        if any(call["index"] > max(closes) for call in s.calls_of(ctx)):
            problems.append("an Orca call came after the own terminal was closed")
    return s.result(problems, "removal, report, own close, in that order, and nothing after")


def main_clone_kept(ctx):
    s = shared(ctx)
    return s.result(s.main_clone_problems(ctx), "the main clone remains")
