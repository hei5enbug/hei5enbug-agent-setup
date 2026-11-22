"""Custom checks for T32: a delegate in a terminal that already ran an agent closes nothing and keeps a dirty worktree."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "handoff_shared.py"
    module = types.ModuleType("handoff_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


KEPT_NAME = re.compile(r"login[ -]spike", re.IGNORECASE)


def no_terminal_closed(ctx):
    s = shared(ctx)
    problems = []
    closes = s.closes_of(ctx)
    if closes:
        problems.append(f"a terminal close was called: {[call['argv'] for call in closes][:2]}")
    expected = set(s.baseline_of(ctx)["terminals"])
    left = {item["handle"] for item in s.state_of(ctx)["terminals"]}
    if expected - left:
        problems.append(f"terminals are gone: {sorted(expected - left)}")
    return s.result(problems, "every terminal is still open")


def dirty_child_kept(ctx):
    s = shared(ctx)
    problems = []
    folder = s.work_of(ctx) / "demo-a-login-spike"
    baseline = next(item for item in s.baseline_of(ctx)["worktrees"].values()
                    if item["record"]["displayName"] == "login spike")
    entry = s.worktree_listed(s.state_of(ctx), "login spike")
    if not folder.is_dir():
        problems.append("the worktree folder is gone")
    elif "unsaved line" not in (folder / "work.txt").read_text(encoding="utf-8"):
        problems.append("the uncommitted change is gone")
    if s.branch_tip(Path(ctx.origin), "login-spike") != baseline["head"]:
        problems.append("the branch changed or is gone")
    if entry is None:
        problems.append("Orca no longer lists the worktree")
    elif entry["workspaceStatus"] != baseline["record"]["workspaceStatus"]:
        problems.append(f"its status changed to {entry['workspaceStatus']}")
    if s.calls_named(ctx, "worktree", "rm", ok_only=False):
        problems.append("a worktree removal was called")
    return s.result(problems, "kept as it was")


def report_names_kept_worktree(ctx):
    s = shared(ctx)
    reports = s.reports_to(ctx, s.SENDER_HANDLE)
    hit = [call for call in reports if KEPT_NAME.search(s.option(call, "--body") or "")]
    problems = [] if hit else ["no report to the sender's terminal names the kept worktree"]
    return s.result(problems, "the report names the kept worktree")
