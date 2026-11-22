"""Shared checks of the answered skill-issue-creator filing cases T110 and T111: the run must reach the write and the read-back."""

from __future__ import annotations

import json
import re
import types
from pathlib import Path

WRITE_IN_COMMAND = re.compile(r"\bgh issue (?:create|edit|comment)\b")
CHECK_FILED_IN_COMMAND = re.compile(r"\bcheck_filed\.py\b")
READ_BACK = re.compile(r"^gh (?:issue view\b|api (?!user\b))")
TRACKER_FILE = "demo-org_demo-plugin.json"


def issue_shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "skill_issue_shared.py"
    module = types.ModuleType("skill_issue_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def bash_commands(ctx) -> list[tuple[int, str]]:
    calls = ctx.view.get("tool_calls", [])
    return [(index, str((call.get("input") or {}).get("command", ""))) for index, call in enumerate(calls) if call.get("name") == "Bash"]


def first_write_index(ctx) -> int | None:
    return next((index for index, text in bash_commands(ctx) if WRITE_IN_COMMAND.search(text)), None)


def seeded_issue(ctx, number: int) -> dict:
    path = issue_shared(ctx).work_of(ctx) / "trackers" / TRACKER_FILE
    issues = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    return next((issue for issue in issues if issue["number"] == number), {})


def no_blocking_question(ctx):
    asked = [call for call in ctx.view.get("tool_calls", []) if call.get("name") == "AskUserQuestion"]
    return not asked, f"{len(asked)} question call(s) after the answers were given", {}


def read_back_after_write(ctx):
    calls = issue_shared(ctx).gh_calls(ctx)
    writes = [number for number, line in enumerate(calls) if issue_shared(ctx).WRITE_COMMAND.match(line)]
    reads = [number for number, line in enumerate(calls) if READ_BACK.match(line) and writes and number > writes[0]]
    return bool(reads), (f"{len(reads)} read-back call(s) after the first write" if writes else "no write to read back"), {}


def ran_after_write(text: str, index: int, write_at: int | None, write_text: str) -> bool:
    """A later call, or the same call when the script text follows the write text, as in `gh issue edit ...; python3 check_filed.py`."""
    if write_at is None:
        return False
    if index == write_at:
        return CHECK_FILED_IN_COMMAND.search(text).start() > WRITE_IN_COMMAND.search(write_text).start()
    return index > write_at


def check_filed_ran_after_write(ctx):
    write_at = first_write_index(ctx)
    commands = dict(bash_commands(ctx))
    write_text = commands.get(write_at, "")
    runs = [index for index, text in commands.items() if CHECK_FILED_IN_COMMAND.search(text)]
    late = [index for index in runs if ran_after_write(commands[index], index, write_at, write_text)]
    return bool(late), f"{len(late)} check_filed.py run(s) after the write", {}
