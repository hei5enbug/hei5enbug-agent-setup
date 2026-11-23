"""Custom checks for T181: an open issue already covers the gap, so no second issue is created and it is reported."""

from __future__ import annotations

import types
from pathlib import Path

COVERED_NUMBER = 12
KEPT_SENTENCE = "leave that section out of the overview, heading included"


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "skill_issue_shared.py"
    module = types.ModuleType("skill_issue_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def skill_invoked(ctx):
    return shared(ctx).skill_invoked(ctx)


def duplicate_search_ran(ctx):
    searches = [line for line in shared(ctx).gh_calls(ctx) if shared(ctx).SEARCH_COMMAND.match(line)]
    return bool(searches), f"{len(searches)} tracker search call(s)", {}


def no_new_issue(ctx):
    helper = shared(ctx)
    creates = [line for line in helper.gh_calls(ctx) if helper.CREATE_COMMAND.match(line)]
    return not creates and not helper.created_issues(ctx), (
        f"a new issue was created: {creates[:2]}" if creates else "no new issue was created"), {"creates": creates}


def covering_issue_intact(ctx):
    issue = next((item for item in shared(ctx).tracker_issues(ctx) if item["number"] == COVERED_NUMBER), None)
    if issue is None:
        return True, "the open issue was not changed", {}
    kept = KEPT_SENTENCE in issue.get("body", "")
    return kept, "the edited body keeps the original Proposal" if kept else "the edit dropped the original Proposal", {}
