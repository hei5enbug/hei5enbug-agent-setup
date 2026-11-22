"""Shared by the custom checks of the repository-guidance tasks: skill use, untouched repository, answer shape."""

from __future__ import annotations

import json
import re

SKILL_NAME = re.compile(r"(^|:)mistake-enforcer$")
SKILL_FILE = "mistake-enforcer/SKILL.md"
FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
ENTRY_LINE = re.compile(r"Before [^\n]{3,}, read [`\"']?docs/adr/[\w./-]+")
ADR_MAX_LINES = 30
ADR_MIN_LINES = 3
REJECTED = re.compile(r"(?i)reject|not chosen|not kept|버린|제외|폐기|채택하지|쓰지 않")


def skill_invoked(ctx):
    """The skill ran: a Skill tool call by name, or, on a host with no Skill tool, a read of its SKILL.md."""
    for call in ctx.view.get("tool_calls", []):
        arguments = call.get("input") or {}
        if call.get("name") == "Skill" and SKILL_NAME.search(str(arguments.get("skill", ""))):
            return True, "Skill tool call", {}
        if call.get("name") in ("Read", "Bash") and SKILL_FILE in json.dumps(arguments):
            return True, "SKILL.md read", {}
    return False, "no Skill call and no SKILL.md read for mistake-enforcer", {}


def report_text(ctx) -> str:
    """The final answer plus the input of any question tool call, since the harness cannot answer a question."""
    asked = [json.dumps(call.get("input") or {}, ensure_ascii=False) for call in ctx.view.get("tool_calls", [])
             if call.get("name") == "AskUserQuestion"]
    return "\n".join([ctx.view.get("final_answer", ""), *asked])


def fenced_blocks(text: str) -> list[str]:
    return [block.strip("\n") for block in FENCE.findall(text)]


def repository_untouched(ctx):
    """The commit, the work tree, the branches, and the worktrees are what the setup left: nothing was written."""
    problems = []
    if ctx.git("rev-parse", "HEAD").strip() != ctx.base:
        problems.append("HEAD moved")
    dirty = [line for line in ctx.porcelain.splitlines() if line and "__pycache__" not in line and ".pytest_cache" not in line]
    if dirty:
        problems.append(f"work tree changed: {dirty[:4]}")
    branches = [line.strip(" *") for line in ctx.git("branch", "--list").splitlines() if line.strip()]
    if branches != ["main"]:
        problems.append(f"branches: {branches}")
    worktrees = [line for line in ctx.git("worktree", "list", "--porcelain").splitlines() if line.startswith("worktree ")]
    if len(worktrees) != 1:
        problems.append(f"{len(worktrees)} worktrees")
    return not problems, "; ".join(problems) or "repository untouched", {}
