"""Custom check for T54: how many delegated runs the session started for the eight questions."""

from __future__ import annotations

import re

AGENT_TOOLS = frozenset({"Agent", "Task", "spawn_agent"})
RUNNER = re.compile(r"role_runner\.py\s+(?!-)[\w-]+")
ASSIGNMENT = re.compile(r"--assignment(?:\s|=)")


def delegated_runs_counted(ctx):
    runs = 0
    for call in ctx.view.get("tool_calls", []):
        if call.get("name") in AGENT_TOOLS:
            runs += 1
        elif call.get("name") == "Bash":
            command = str(call.get("input", {}).get("command", ""))
            if RUNNER.search(command):
                runs += max(1, len(ASSIGNMENT.findall(command)))
    return True, f"{runs} delegated run(s)", {"runs": runs}
