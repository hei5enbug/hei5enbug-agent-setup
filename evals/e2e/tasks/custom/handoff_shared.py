"""Shared by the custom checks of the handoff tasks T59 to T62: read the fake Orca's call log and state.

A call is one line of `orca-state/calls.jsonl`: its arguments without `--json`, the folder it ran in, the terminal
handle of the session that made it, and whether it succeeded. The hook that closes a never-used terminal at the
first prompt only reads and closes, so every call before the first other call is the hook's.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

HOOK_PAIRS = {("worktree", "current"), ("terminal", "list"), ("terminal", "read"), ("terminal", "close")}
HOST_COMMAND = re.compile(r"^(?:cd '[^']*' && )?(?:claude|codex)$")
BELONGS = re.compile(r"belongs to the handoff", re.IGNORECASE)
RESULT = re.compile(r"(?<!\d)20(?!\d)")


def work_of(ctx) -> Path:
    return Path(ctx.origin).parent


def state_of(ctx) -> dict:
    return json.loads((work_of(ctx) / "orca-state" / "state.json").read_text(encoding="utf-8"))


def baseline_of(ctx) -> dict:
    return json.loads((work_of(ctx) / "orca-state" / "baseline.json").read_text(encoding="utf-8"))


def calls_of(ctx) -> list[dict]:
    path = work_of(ctx) / "orca-state" / "calls.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def pair(call: dict) -> tuple[str, str]:
    words = [token for token in call["argv"] if not token.startswith("--")][:2]
    return (words + ["", ""])[0], (words + ["", ""])[1]


def option(call: dict, name: str) -> str | None:
    argv = call["argv"]
    for index, token in enumerate(argv):
        if token == name and index + 1 < len(argv):
            return argv[index + 1]
        if token.startswith(f"{name}="):
            return token[len(name) + 1:]
    return None


def succeeded(calls: list[dict], command: tuple[str, str], **options: str) -> list[tuple[int, dict]]:
    """The successful calls of `command` in order, each with its index, whose options equal the given values."""
    return [(index, call) for index, call in enumerate(calls)
            if call["ok"] and pair(call) == command and all(option(call, f"--{name.replace('_', '-')}") == value
                                                              for name, value in options.items())]


def terminal_handles(state: dict) -> set[str]:
    return {item["handle"] for item in state["terminals"]}


def listed(state: dict, name: str) -> dict | None:
    return next((item for item in state["worktrees"] if item["displayName"] == name), None)


def reports(state: dict, to: str) -> list[dict]:
    return [message for message in state.get("messages", []) if message.get("to") == to]


def touched(calls: list[dict], handle: str) -> list[str]:
    """Commands that sent input to or closed the terminal `handle`, as text."""
    return [" ".join(call["argv"]) for call in calls
            if pair(call) in {("terminal", "send"), ("terminal", "close")} and option(call, "--terminal") == handle]


def child_removal_problems(calls: list[dict], worktree_id: str, delegate: str) -> list[str]:
    """What breaks the rule that the sender removes a handoff child worktree after the delegate's terminal closed.

    The delegate closes its own terminal, then the sender, from a call of its own, removes the worktree. The delegate
    never removes the worktree it runs in, and nobody removes it before that terminal is closed.
    """
    closes = [index for index, _ in succeeded(calls, ("terminal", "close"), terminal=delegate)]
    removals = [(index, call) for index, call in succeeded(calls, ("worktree", "rm"))
                if option(call, "--worktree") == f"id:{worktree_id}"]
    problems = []
    if not removals:
        problems.append("the child worktree was never removed")
    if not closes:
        problems.append("the delegate's terminal was never closed")
    for index, call in removals:
        if call.get("handle") == delegate:
            problems.append("the delegate removed the worktree it runs in")
        elif closes and index < closes[0]:
            problems.append("the worktree was removed before the delegate's terminal was closed")
    return problems


def report_text(state: dict) -> str:
    return "\n".join(message.get("body", "") for message in reports(state, "term_sender"))


def worktree_gone(ctx, directory: str, branch: str, name: str) -> list[str]:
    work, problems = work_of(ctx), []
    if (work / directory).exists():
        problems.append("the worktree folder is still there")
    if listed(state_of(ctx), name) is not None:
        problems.append("Orca still lists the worktree")
    listing = subprocess.run(["git", "-C", str(ctx.origin), "branch", "--list", branch], capture_output=True,
                             text=True, check=False).stdout
    if listing.strip():
        problems.append(f"the local branch {branch} is still there")
    return problems


def main_clone_kept(ctx) -> list[str]:
    state, problems = state_of(ctx), []
    if not Path(ctx.origin).is_dir():
        problems.append("the demo-a main clone folder is gone")
    if not any(item["repoId"] == "demo-a" and item["isMainWorktree"] for item in state["worktrees"]):
        problems.append("Orca no longer lists the demo-a main clone")
    return problems


def verdict(problems: list[str], good: str):
    return not problems, good if not problems else "; ".join(problems), {"problems": problems}
