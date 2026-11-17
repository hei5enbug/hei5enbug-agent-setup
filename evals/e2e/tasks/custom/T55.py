"""Custom checks for T55: how many worktrees the session created and how many workers it ran at once."""

from __future__ import annotations

import re
import types
from pathlib import Path

ADDED_TEST_DEF = re.compile(r"^\+\s*def\s+test_")


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "worker_concurrency.py"
    module = types.ModuleType("worker_concurrency")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def isolated_worktrees_created(ctx):
    module = shared(ctx)
    worktrees = module.worktrees_created(ctx.view)
    concurrent = module.concurrent_launches(ctx.view)
    detail = f"{worktrees} worktree(s) created, {len(concurrent)} case(s) of workers at once, {len(module.launches(ctx.view))} worker launch(es)"
    return True, detail, {"worktrees": worktrees, "concurrent": len(concurrent), "workers": len(module.launches(ctx.view))}


def tests_added(ctx):
    diff = ctx.git("diff", ctx.base, "--", "tests")
    added = [path for path, status in ctx.changes.items() if status == "A" and path.startswith("tests/")]
    count = len(ADDED_TEST_DEF.findall(diff)) + sum(
        len(re.findall(r"^\s*def test_", (ctx.repo / path).read_text(encoding="utf-8", errors="replace"), re.MULTILINE))
        for path in added
    )
    return count >= 2, f"{count} test function(s) added", {"added_tests": count}
