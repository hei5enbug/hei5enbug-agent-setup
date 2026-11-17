"""Custom checks for T57: one feature across three areas, and how many area coordinators the session started."""

from __future__ import annotations

import re

AGENT_TOOLS = frozenset({"Agent", "Task", "spawn_agent"})
COORDINATOR_COMMAND = re.compile(r"role_runner\.py\s+(?:(?:--[\w-]+(?:[ =]\S+)?\s+)*)area-coordinator\b")
COORDINATOR_NAME = "area-coordinator"
ADDED_TEST_DEF = re.compile(r"^\+\s*def\s+test_")


def coordinator_starts(view):
    """The tool calls of a view that start an area coordinator: a role runner command, an agent launch of that type, or a
    role runner status line that names the role in a tool result."""
    found = []
    for call in view.get("tool_calls", []):
        tool_input = call.get("input", {}) if isinstance(call.get("input"), dict) else {}
        if call.get("name") in AGENT_TOOLS:
            kind = str(tool_input.get("subagent_type") or tool_input.get("agent_type") or "")
            if COORDINATOR_NAME in kind:
                found.append(call)
        elif call.get("name") == "Bash" and COORDINATOR_COMMAND.search(str(tool_input.get("command", ""))):
            found.append(call)
        elif f'"role": "{COORDINATOR_NAME}"' in str(call.get("result_text", "")):
            found.append(call)
    return found


def area_coordinators_started(ctx):
    started = coordinator_starts(ctx.view)
    return True, f"{len(started)} area coordinator start(s)", {"starts": len(started)}


def tests_added(ctx):
    diff = ctx.git("diff", ctx.base, "--", "tests")
    added = [path for path, status in ctx.changes.items() if status == "A" and path.startswith("tests/")]
    count = len(ADDED_TEST_DEF.findall(diff)) + sum(
        len(re.findall(r"^\s*def test_", (ctx.repo / path).read_text(encoding="utf-8", errors="replace"), re.MULTILINE))
        for path in added
    )
    return count >= 9, f"{count} test function(s) added", {"added_tests": count}
