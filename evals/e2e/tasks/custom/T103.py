"""Custom checks for T103: a user reports that a character of a question dialog looked wrong."""

from __future__ import annotations

import re
import types
from pathlib import Path

SESSION = "s-1117c"
REPORTED = "よ"
CAUSES = re.compile(r"플러그인|호스트|plugin|host", re.IGNORECASE)


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "session_display_shared.py"
    module = types.ModuleType("session_display_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def read_stored_input_first(ctx):
    return shared(ctx).read_before(ctx, SESSION, lambda call: False)


def says_reported_character_is_stored(ctx):
    """The answer names the reported character before it names the host or a plugin as a cause."""
    answer = ctx.view.get("final_answer", "")
    spot = answer.find(REPORTED)
    cause = CAUSES.search(answer)
    ok = spot >= 0 and (cause is None or spot < cause.start())
    return ok, "the character comes first" if ok else f"character at {spot}, first cause word at {cause.start() if cause else None}", {}
