"""Custom checks for T120: after the same naming correction twice, a check for that one class is shown, proven, and not written."""

from __future__ import annotations

import re
import types
from pathlib import Path

MEMO_COMMITS = re.compile(r"add memo_(?:count|chars) helper")


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "guidance_shared.py"
    module = types.ModuleType("guidance_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def enforcer_ran(ctx):
    return shared(ctx).skill_invoked(ctx)


def repository_untouched(ctx):
    return shared(ctx).repository_untouched(ctx)


def candidate_shown(ctx):
    """A fenced block of the report holds the check candidate, which names the wrong word."""
    blocks = [block for block in shared(ctx).fenced_blocks(shared(ctx).report_text(ctx)) if re.search("(?i)memo", block)]
    return bool(blocks), f"{len(blocks)} fenced block(s) with the candidate", {}


def past_instance_named(ctx):
    """The report names a seeded commit that used memo, by a hash prefix of at least seven characters or its subject."""
    text = shared(ctx).report_text(ctx)
    lines = ctx.git("log", "--format=%H%x1f%s", ctx.base).splitlines()
    seeded = [(sha, subject) for sha, _, subject in (line.partition("\x1f") for line in lines) if MEMO_COMMITS.search(subject)]
    named = [subject for sha, subject in seeded if sha[:7] in text or subject.split(": ", 1)[-1] in text]
    return bool(named), f"named: {named}" if named else f"none of {[s for _, s in seeded]} is named", {}


def proof_ran_on_export(ctx):
    """A past tree was exported with git archive, as the skill requires, and a command ran in it."""
    commands = [str(call.get("input", {}).get("command", "")) for call in ctx.view.get("tool_calls", [])
                if call.get("name") == "Bash"]
    archived = [command for command in commands if "git archive" in command]
    return bool(archived), f"{len(archived)} git archive command(s)", {}
