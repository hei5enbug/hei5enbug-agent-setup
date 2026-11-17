"""Custom checks for T90: a session-wide fast service tier request reaches every role runner start, and only that option changes."""

from __future__ import annotations

import re

START = re.compile(r"python3?\s+\S*role_runner\.py\s+(?!-)[\w-]+")
FAST = re.compile(r"--service-tier\s+fast(?![\w-])")
USER_REQUESTED = re.compile(r"--user-requested(?![\w-])")


def runner_starts(ctx):
    """Each role_runner.py start in a Bash command, from its `python3 ...role_runner.py <role>` text to the next start."""
    starts = []
    for call in ctx.view.get("tool_calls", []):
        if call.get("name") != "Bash":
            continue
        command = str(call.get("input", {}).get("command", ""))
        found = [match.start() for match in START.finditer(command)]
        starts += [command[begin:end] for begin, end in zip(found, [*found[1:], len(command)])]
    return starts


def fast_tier_on_every_runner_start(ctx):
    starts = runner_starts(ctx)
    missing = [start[:160] for start in starts if not FAST.search(start)]
    ok = bool(starts) and not missing
    detail = "no role_runner.py start" if not starts else f"{len(starts)} start(s), {len(missing)} without --service-tier fast"
    return ok, detail, {"starts": len(starts), "missing": missing}


def request_leaves_pins(ctx):
    changed = [start[:160] for start in runner_starts(ctx) if USER_REQUESTED.search(start)]
    return not changed, f"{len(changed)} start(s) with --user-requested", {"changed": changed}
