"""Custom checks for T79: a required ticket key with no value makes commit mode stop and ask."""

from __future__ import annotations

import re
import types
from pathlib import Path

ASKS = re.compile(r"[?？]|주세요|알려|입력|말씀")
NAMES_KEY = re.compile(r"티켓|이슈|식별자|번호|ticket|identifier|issue|key|ABC-", re.IGNORECASE)


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "commit_shared.py"
    module = types.ModuleType("commit_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def skill_invoked(ctx):
    return shared(ctx).skill_invoked(ctx)


def asked_for_value(ctx):
    text = shared(ctx).question_text(ctx)
    ok = bool(ASKS.search(text) and NAMES_KEY.search(text))
    return ok, "the answer asks for the ticket key" if ok else f"no question for the key: {text[:200]!r}", {}


def index_untouched(ctx):
    """Stop before any write: nothing was staged."""
    staged = [line for line in shared(ctx).porcelain_lines(ctx) if line[0] not in " ?"]
    return not staged, f"staged: {staged}" if staged else "index untouched", {"staged": staged}
