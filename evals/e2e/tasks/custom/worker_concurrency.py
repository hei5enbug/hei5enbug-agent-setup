"""Shared by T55 and T56: which worker launches of a transcript ran at once, and which worktrees the session created."""

from __future__ import annotations

import re

AGENT_TOOLS = frozenset({"Agent", "Task", "spawn_agent"})
WORKER_NAMES = frozenset({"worker", "sonnet-worker", "implementation"})
RUNNER_START = re.compile(r"role_runner\.py\s+((?!-)[\w-]+)")
BACKGROUND_COMMAND = re.compile(r"(?m)(?<![&|>\d])&\s*(?:;|$)|\bxargs\s+(?:\S+\s+)*-P\s*\d|\bparallel\b")
WORKTREE_COMMAND = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?worktree\s+add\b|\borca\s+worktree\s+create\b")
WORKTREE_TOOLS = frozenset({"EnterWorktree"})


def bare(kind):
    return str(kind or "").rsplit(":", 1)[-1].lower()


def launches(view):
    """Every worker launch of the main session: an agent call of a worker type or a role runner start of a worker role.
    A command that starts several runners gives one launch each."""
    found = []
    for call in view.get("tool_calls", []):
        if call.get("source") != "main":
            continue
        tool_input = call.get("input") if isinstance(call.get("input"), dict) else {}
        if call.get("name") in AGENT_TOOLS:
            if bare(tool_input.get("subagent_type") or tool_input.get("agent_type")) in WORKER_NAMES:
                found.append({"id": call["id"], "command": ""})
        elif call.get("name") == "Bash":
            command = str(tool_input.get("command", ""))
            for role in RUNNER_START.findall(command):
                if role.lower() in WORKER_NAMES:
                    found.append({"id": call["id"], "command": command})
    return found


def span_of(view, call_id):
    spans = view.get("spans") or {}
    if call_id in spans:
        return spans[call_id]
    return spans.get(re.sub(r":\d+$", "", call_id))


def overlap(first, second):
    """Whether two spans share a stretch of the stream; a span with no return runs on to the end."""
    end_first = float("inf") if first["returned"] is None else first["returned"]
    end_second = float("inf") if second["returned"] is None else second["returned"]
    return first["began"] < end_second and second["began"] < end_first


def concurrent_launches(view):
    """Descriptions of the worker launches that ran at once: runners started together by one command, and launches whose
    spans overlap (parallel in one message, or one that runs in the background)."""
    found = []
    per_call = {}
    for launch in launches(view):
        per_call.setdefault(launch["id"], []).append(launch)
    for call_id, group in per_call.items():
        if len(group) > 1 and BACKGROUND_COMMAND.search(group[0]["command"]):
            found.append(f"{len(group)} workers started together by one command {call_id}")
    ids = list(per_call)
    for index, first in enumerate(ids):
        for second in ids[index + 1:]:
            span_first, span_second = span_of(view, first), span_of(view, second)
            if span_first and span_second and overlap(span_first, span_second):
                found.append(f"workers {first} and {second} ran at once")
    return found


def worktrees_created(view):
    """The calls that create a worktree: a Git or Orca command, the host's worktree tool, or an agent launched with its own
    worktree."""
    count = 0
    for call in view.get("tool_calls", []):
        tool_input = call.get("input") if isinstance(call.get("input"), dict) else {}
        if call.get("name") in WORKTREE_TOOLS or (call.get("name") in AGENT_TOOLS and tool_input.get("isolation") == "worktree"):
            count += 1
        elif call.get("name") == "Bash":
            count += len(WORKTREE_COMMAND.findall(str(tool_input.get("command", ""))))
    return count
