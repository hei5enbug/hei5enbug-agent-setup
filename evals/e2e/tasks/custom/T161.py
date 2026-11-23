"""Custom checks for T161: a review of a Korean design document names which reference the skill read and whether its format script ran."""

from __future__ import annotations

import types
from pathlib import Path

SKILL = "technical-design-writer"
TRANSLATIONESE = "translationese.md"
PATTERNS = "patterns.md"
FORMAT_SCRIPT = "check_format.py"


def skill_invoked(ctx):
    path = Path(ctx.tasks_root) / "custom" / "skill_use_shared.py"
    module = types.ModuleType("skill_use_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module.skill_invoked(ctx, SKILL)


def read_paths(ctx) -> list[str]:
    return [str((call.get("input") or {}).get("file_path", "")) for call in ctx.view.get("tool_calls", [])
            if call.get("name") == "Read"]


def read_translationese(ctx):
    hits = [path for path in read_paths(ctx) if path.endswith(TRANSLATIONESE)]
    return bool(hits), f"{len(hits)} read(s) of {TRANSLATIONESE}", {}


def patterns_not_read(ctx):
    hits = [path for path in read_paths(ctx) if path.endswith(PATTERNS)]
    return not hits, f"{len(hits)} read(s) of {PATTERNS}", {}


def format_script_ran(ctx):
    runs = [call for call in ctx.view.get("tool_calls", []) if call.get("name") == "Bash"
            and FORMAT_SCRIPT in str((call.get("input") or {}).get("command", ""))]
    return bool(runs), f"{len(runs)} run(s) of {FORMAT_SCRIPT}", {}
