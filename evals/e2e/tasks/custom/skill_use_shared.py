"""Shared by custom checks that ask whether a skill ran: a Skill tool call, or a shell command that reads its SKILL.md."""

from __future__ import annotations

import re

READERS = re.compile(r"(?:^|[;&|(\s])(?:cat|sed|rg|grep|head|tail|nl|less|more|awk|bat)\s")


def shell_reads_skill(command: str, skill: str) -> bool:
    """A reading command names `<skill>/SKILL.md`; a file listing that only matches the file name does not count."""
    return f"{skill}/SKILL.md" in command and bool(READERS.search(command))


def skill_invoked(ctx, skill: str):
    calls = ctx.view.get("tool_calls", [])
    tool = [call for call in calls if call.get("name") == "Skill"
            and str((call.get("input") or {}).get("skill", "")).endswith(skill)]
    shell = [call for call in calls if call.get("name") == "Bash"
             and shell_reads_skill(str((call.get("input") or {}).get("command", "")), skill)]
    return bool(tool or shell), f"{len(tool)} call(s) of the {skill} skill, {len(shell)} shell read(s) of its SKILL.md", {}
