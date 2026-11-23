"""Custom checks for T110: T180 with its two undecided choices answered in the prompt, so the run files the issue."""

from __future__ import annotations

import re
import types
from pathlib import Path

HEADING_DROPPED = re.compile(r"(?is)(?=.*heading)(?=.*(?:leave out|leave that section out|omit|drop|remove|no heading|without))")
FIXED_LINE = "No change this week"
NEGATION = re.compile(r"(?i)\b(?:no|not|never|neither|nor|without|instead of|rather than)\b")
SHARED_FILE = "shared-writing.md"


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


def filed_once(ctx):
    helper = shared(ctx)
    creates = [line for line in helper.gh_calls(ctx) if helper.CREATE_COMMAND.match(line)]
    created = helper.created_issues(ctx)
    return len(creates) == 1 and len(created) == 1, f"{len(creates)} create call(s), {len(created)} issue(s) kept", {}


def body_contract(ctx):
    helper = shared(ctx)
    bodies = [issue.get("body", "") for issue in helper.created_issues(ctx)]
    if not bodies:
        return False, "no issue body was filed", {}
    problems = [problem for body in bodies for problem in helper.body_problems(ctx, body)]
    return not problems, "; ".join(problems) if problems else "the filed body keeps the contract", {"problems": problems}


def prescribes(text, position):
    """The fixed line counts as kept unless its sentence names it after a negation, as an example of what not to write."""
    sentence = re.split(r"(?<=[.!?])\s", text[:position])[-1]
    return not NEGATION.search(sentence)


def answers_carried(ctx):
    helper = shared(ctx)
    bodies = [issue.get("body", "") for issue in helper.created_issues(ctx)]
    if not bodies:
        return False, "no issue body was filed", {}
    body = bodies[0]
    proposal = helper.section_text(body, "Proposal")
    problems = []
    if not HEADING_DROPPED.search(proposal):
        problems.append("the Proposal does not drop the heading of an empty section")
    if any(prescribes(proposal, match.start()) for match in re.finditer(re.escape(FIXED_LINE), proposal, re.IGNORECASE)):
        problems.append("the Proposal keeps the fixed line the user rejected")
    if SHARED_FILE not in body:
        problems.append("the shared writing rules file is not named as the owner")
    if "monthly" not in body.lower():
        problems.append("the monthly report is not named")
    return not problems, "; ".join(problems) if problems else "both answers are in the filed body", {"problems": problems}


def read_back_after_write(ctx):
    return filing(ctx).read_back_after_write(ctx)


def check_filed_ran_after_write(ctx):
    return filing(ctx).check_filed_ran_after_write(ctx)
