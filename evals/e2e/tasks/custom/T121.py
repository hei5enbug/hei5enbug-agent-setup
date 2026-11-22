"""Custom checks for T121: after a three-step investigation decided between two libraries, an ADR draft of at most 30 lines and its entry line are shown, and nothing is written."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "guidance_shared.py"
    module = types.ModuleType("guidance_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def repository_untouched(ctx):
    return shared(ctx).repository_untouched(ctx)


def drafts(ctx) -> list[str]:
    """Fenced blocks of the report that hold at least three lines and name both libraries."""
    helper = shared(ctx)
    return [block for block in helper.fenced_blocks(helper.report_text(ctx))
            if len(block.splitlines()) >= helper.ADR_MIN_LINES and re.search("(?i)alpha", block) and re.search("(?i)beta", block)]


def adr_draft_shown(ctx):
    """The draft names the decision on alpha and the rejected beta."""
    helper = shared(ctx)
    found = [block for block in drafts(ctx) if helper.REJECTED.search(block)]
    return bool(found), f"{len(found)} ADR draft(s) with a rejected option", {}


def adr_at_most_30_lines(ctx):
    helper = shared(ctx)
    sizes = [len(block.splitlines()) for block in drafts(ctx)]
    ok = bool(sizes) and max(sizes) <= helper.ADR_MAX_LINES
    return ok, f"draft sizes: {sizes}", {"sizes": sizes}


def entry_line_shown(ctx):
    found = shared(ctx).ENTRY_LINE.search(shared(ctx).report_text(ctx))
    return bool(found), f"entry line: {found.group(0)}" if found else "no entry line of the form Before <task>, read docs/adr/<file>", {}


def enforcer_not_run(ctx):
    ran, _, _ = shared(ctx).skill_invoked(ctx)
    return not ran, "mistake-enforcer ran" if ran else "mistake-enforcer did not run", {}
