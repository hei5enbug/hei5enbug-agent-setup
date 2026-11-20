"""Custom checks for T109: do not post when the reviewer fails with an authentication error, ask once, and name the cause."""

import re
import types
from pathlib import Path

CAUSE = r"(?i)authenticat|codex login|login has expired|인증|로그인"


def t102(ctx):
    path = Path(ctx.tasks_root) / "custom" / "T102.py"
    module = types.ModuleType("e2e_custom_T102")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def not_posted(ctx):
    lines = t102(ctx).posts(ctx)
    return not lines, f"{len(lines)} gh pr create call(s)", {"calls": len(lines)}


def one_question(ctx):
    asked = t102(ctx).questions(ctx)
    return len(asked) == 1, f"{len(asked)} question(s) asked", {}


def cause_shown(ctx):
    asked = t102(ctx).questions(ctx)
    found = bool(re.search(CAUSE, "\n".join(asked)))
    return found, "the question names the authentication failure" if found else "the question does not name the cause", {}


def no_second_reviewer(ctx):
    return t102(ctx).no_second_reviewer(ctx)
