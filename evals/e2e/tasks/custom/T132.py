"""Custom checks for T132: one review fix reaches every document that states its point and matches the decision."""

from __future__ import annotations

import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "review_loop_shared.py"
    module = types.ModuleType("review_loop_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def ran_exactly_twice(ctx):
    return shared(ctx).run_count(ctx, 2)


def second_run_clean(ctx):
    runs = shared(ctx).runs_of(ctx)
    if len(runs) < 2:
        return False, "the review ran fewer than twice", {}
    flagged = [item["file"] for item in runs[1]["findings"]]
    return not flagged, "run 2 returned no findings" if not flagged else f"run 2 flagged {flagged}", {}


def all_files_state_the_decision(ctx):
    helper = shared(ctx)
    common = helper.common(ctx)
    bad = [name for name in common.RETRY_FILES
           if common.RETRY_WRONG.search(helper.read(ctx, name)) or not common.RETRY_RIGHT.search(helper.read(ctx, name))]
    return not bad, "all three files state 3" if not bad else f"not stating 3: {bad}", {}
