"""Custom checks for T67: the worktree of demo-b is removed by the hook's detached run once its worker has ended."""

from __future__ import annotations

import os
import subprocess
import time
import types
from pathlib import Path

BRANCH = "feature/ABC-123"
WAIT_SECONDS = float(os.environ.get("E2E_CLEANUP_WAIT_SECONDS", "60"))
QUIET_SECONDS = min(3.0, WAIT_SECONDS)


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "handoff_shared.py"
    module = types.ModuleType("handoff_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def git(path: Path, *arguments: str) -> str:
    return subprocess.run(["git", "-C", str(path), *arguments], capture_output=True, text=True,
                          check=False).stdout.strip()


def settled(ctx) -> None:
    """Wait for the hook's run: a successful removal, then a quiet call log, or the wait limit."""
    h = shared(ctx)
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline and not h.succeeded(h.calls_of(ctx), ("worktree", "rm")):
        time.sleep(0.5)
    last = -1
    while time.monotonic() < deadline and len(h.calls_of(ctx)) != last:
        last = len(h.calls_of(ctx))
        time.sleep(QUIET_SECONDS)


def worker_pushed_branch(ctx):
    h, problems = shared(ctx), []
    calls = h.calls_of(ctx)
    if not h.succeeded(calls, ("worktree", "create")):
        problems.append("no `orca worktree create` succeeded")
    if not h.succeeded(calls, ("orchestration", "worker-start")):
        problems.append("no `orca orchestration worker-start` succeeded")
    origin = h.work_of(ctx) / "demo-b-origin.git"
    if not git(origin, "branch", "--list", BRANCH):
        problems.append(f"origin has no {BRANCH}")
    elif git(origin, "rev-list", "--count", f"main..{BRANCH}") in ("", "0"):
        problems.append(f"{BRANCH} on origin holds no commit of the worker")
    return h.verdict(problems, "the worktree was created, the worker ran and pushed its branch")


def removed_by_hook(ctx):
    h, problems = shared(ctx), []
    settled(ctx)
    calls, work = h.calls_of(ctx), h.work_of(ctx)
    removals = [call for _, call in h.succeeded(calls, ("worktree", "rm"))]
    if not removals:
        problems.append("no worktree was removed")
    for call in removals:
        if call.get("cwd") != "/":
            problems.append("the session removed a worktree itself instead of the hook's detached run")
    if (work / "demo-b-ABC-123").exists():
        problems.append("the worktree folder is still there")
    if h.listed(h.state_of(ctx), "ABC-123") is not None:
        problems.append("Orca still lists the worktree")
    if git(work / "demo-b", "branch", "--list", BRANCH):
        problems.append("the local branch is still there")
    return h.verdict(problems, "the hook's run removed the worktree and its local branch")


def remote_and_clones_kept(ctx):
    h, problems = shared(ctx), []
    work = h.work_of(ctx)
    if not git(work / "demo-b-origin.git", "branch", "--list", BRANCH):
        problems.append(f"origin/{BRANCH} is gone")
    if not (work / "demo-b").is_dir() or not Path(ctx.origin).is_dir():
        problems.append("a main clone is gone")
    state = h.state_of(ctx)
    for repo in ("demo-a", "demo-b"):
        if not any(item["repoId"] == repo and item["isMainWorktree"] for item in state["worktrees"]):
            problems.append(f"Orca no longer lists the {repo} main clone")
    return h.verdict(problems, "the remote branch and both main clones remain")
