"""Shared by the custom checks of the commit tasks: skill use, committed files, message shape, remaining changes."""

from __future__ import annotations

import json
import re

SKILL_NAME = re.compile(r"(^|:)suggest-commit$")
SKILL_FILE = "suggest-commit/SKILL.md"


def skill_invoked(ctx):
    """The skill ran: a Skill tool call by name, or, on a host with no Skill tool, a read of its SKILL.md."""
    for call in ctx.view.get("tool_calls", []):
        arguments = call.get("input") or {}
        if call.get("name") == "Skill" and SKILL_NAME.search(str(arguments.get("skill", ""))):
            return True, "Skill tool call", {}
        if call.get("name") in ("Read", "Bash") and SKILL_FILE in json.dumps(arguments):
            return True, "SKILL.md read", {}
    return False, "no Skill call and no SKILL.md read for suggest-commit", {}


def commits_since_base(ctx) -> list[str]:
    return [line for line in ctx.git("rev-list", f"{ctx.base}..HEAD").split() if line]


def head_files(ctx) -> list[str]:
    return sorted(line for line in ctx.git("diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "HEAD").split()
                  if line)


def head_message(ctx) -> str:
    return ctx.git("log", "-1", "--format=%B").strip()


def subject_only(ctx):
    """The newest commit message is one line: no body, no footer, no trailer."""
    if not commits_since_base(ctx):
        return False, "no commit was made", {}
    message = head_message(ctx)
    ok = bool(message) and "\n" not in message
    return ok, "subject alone" if ok else f"message has more than the subject: {message[:200]!r}", {}


def porcelain_lines(ctx) -> list[str]:
    return [line for line in ctx.porcelain.splitlines() if line]


def question_text(ctx) -> str:
    """The final answer plus the input of any question tool call, since the harness cannot answer a question."""
    asked = [json.dumps(call.get("input") or {}, ensure_ascii=False) for call in ctx.view.get("tool_calls", [])
             if call.get("name") == "AskUserQuestion"]
    return "\n".join([ctx.view.get("final_answer", ""), *asked])
