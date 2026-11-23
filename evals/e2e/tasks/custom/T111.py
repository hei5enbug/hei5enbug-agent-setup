"""Custom checks for T111: T181 with the open question answered in the prompt, so the run updates the covering issue."""

from __future__ import annotations

import re
import types
from pathlib import Path

COVERED_NUMBER = 12
KEPT_RULE = re.compile(r"(?is)(?:leave\s+that\s+(?:team\s+)?section\s+out|\b(?:omit|drop|remove|skip)\s+that\s+(?:team\s+)?section)\b[^.\n]{0,160}\bheading\b")
ALL_EMPTY = re.compile(r"(?is)\b(?:every|all|each)\b[^.\n]{0,120}\b(?:empty|no items|without items)\b|\bno (?:team )?sections? (?:has|have|contains?) (?:any )?items")
ONE_LINE = re.compile(r"(?is)\b(?:single|one)\b[^.\n]{0,24}\b(?:line|sentence|message|notice)\b|one-line|single-line")


def load(ctx, name):
    path = Path(ctx.tasks_root) / "custom" / name
    module = types.ModuleType(name)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def shared(ctx):
    return load(ctx, "skill_issue_shared.py")


def filing(ctx):
    return load(ctx, "filing_shared.py")


def skill_invoked(ctx):
    return shared(ctx).skill_invoked(ctx)


def no_blocking_question(ctx):
    return filing(ctx).no_blocking_question(ctx)


def duplicate_search_ran(ctx):
    helper = shared(ctx)
    searches = [line for line in helper.gh_calls(ctx) if helper.SEARCH_COMMAND.match(line)]
    return bool(searches), f"{len(searches)} tracker search call(s)", {}


def no_new_issue(ctx):
    helper = shared(ctx)
    creates = [line for line in helper.gh_calls(ctx) if helper.CREATE_COMMAND.match(line)]
    return not creates and not helper.created_issues(ctx), (
        f"a new issue was created: {creates[:2]}" if creates else "no new issue was created"), {"creates": creates}


def covered_issue(ctx):
    return next((item for item in shared(ctx).tracker_issues(ctx) if item["number"] == COVERED_NUMBER), None)


def covering_issue_intact(ctx):
    issue = covered_issue(ctx)
    if issue is None:
        return False, "the open issue was not updated", {}
    kept = bool(KEPT_RULE.search(shared(ctx).section_text(str(issue.get("body", "")), "Proposal")))
    return kept, "the edited body keeps the original Proposal" if kept else "the edit dropped the original Proposal", {}


def answer_merged(ctx):
    issue = covered_issue(ctx)
    if issue is None:
        return False, "the open issue was not updated", {}
    original = str(filing(ctx).seeded_issue(ctx, COVERED_NUMBER).get("body", ""))
    kept = set(original.splitlines())
    added = "\n".join(line for line in str(issue.get("body", "")).splitlines() if line not in kept)
    problems = []
    if not added.strip():
        problems.append("the body did not change")
    if not ALL_EMPTY.search(added):
        problems.append("the added text does not state the case where every section is empty")
    if not ONE_LINE.search(added):
        problems.append("the added text does not state the one-line output for that case")
    return not problems, "; ".join(problems) if problems else "the answer is merged into the open issue", {"problems": problems}


def read_back_after_write(ctx):
    return filing(ctx).read_back_after_write(ctx)


def check_filed_ran_after_write(ctx):
    return filing(ctx).check_filed_ran_after_write(ctx)
