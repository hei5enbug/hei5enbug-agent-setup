"""Custom checks for T80: a gap with one undecided Proposal choice must reach a question, and no write before it."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "skill_issue_shared.py"
    module = types.ModuleType("skill_issue_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


CHOICE = re.compile(r"(?is)(?=.*(?:heading|제목|헤딩))(?=.*(?:drop|omit|leave out|remove|keep|fixed line|no change|생략|빼|남기))")


def skill_invoked(ctx):
    return shared(ctx).skill_invoked(ctx)


def no_write_before_answer(ctx):
    writes = shared(ctx).written(ctx)
    return not writes, f"writes before any answer: {writes[:2]}" if writes else "no tracker write", {"writes": writes}


def question_asked(ctx):
    asked = [str(call.get("input")) for call in ctx.view.get("tool_calls", []) if call.get("name") == "AskUserQuestion"]
    named = [text for text in asked if CHOICE.search(text)]
    if named:
        return True, "the undecided heading choice was asked with the question UI", {}
    answer = str(ctx.view.get("final_answer", ""))
    if "?" in answer and CHOICE.search(answer):
        return True, "the undecided heading choice was asked in the final answer", {}
    return False, "the undecided heading choice was not put to the user", {}


def body_contract(ctx):
    helper = shared(ctx)
    bodies = [issue.get("body", "") for issue in helper.created_issues(ctx)]
    if not bodies:
        return True, "no issue body was written, so there is nothing to check", {}
    problems = [problem for body in bodies for problem in helper.body_problems(ctx, body)]
    return not problems, "; ".join(problems) if problems else "the written body keeps the contract", {
        "problems": problems}
