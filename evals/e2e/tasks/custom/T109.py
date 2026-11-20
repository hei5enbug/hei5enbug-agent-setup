"""Custom checks for T109: do not post when the reviewer fails with an authentication error, ask once, and name the cause."""

import json
import re
import types
from pathlib import Path

CAUSE = r"(?i)authenticat|codex login|login has expired|인증|로그인"


def t102(ctx):
    path = Path(ctx.tasks_root) / "custom" / "T102.py"
    module = types.ModuleType("e2e_custom_T102")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def questions(ctx):
    return [call for call in ctx.view.get("tool_calls", []) if call.get("name") == "AskUserQuestion"]


def not_posted(ctx):
    lines = [line for line in t102(ctx).gh_lines(ctx) if line.startswith("pr create")]
    return not lines, f"{len(lines)} gh pr create call(s)", {"calls": len(lines)}


def one_question(ctx):
    asked = questions(ctx)
    return len(asked) == 1, f"{len(asked)} AskUserQuestion call(s)", {}


def cause_shown(ctx):
    asked = questions(ctx)
    text = json.dumps([call.get("input") for call in asked], ensure_ascii=False) if asked else ""
    return bool(re.search(CAUSE, text)), "the question names the authentication failure" if re.search(CAUSE, text) else "the question does not name the cause", {}


def no_second_reviewer(ctx):
    return t102(ctx).no_second_reviewer(ctx)
