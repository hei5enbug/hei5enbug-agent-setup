"""Shared reads of the fake Orca record for T67: its state, its ordered call log, and the seeded baseline.

A call is a dict with `index` (its position among all calls), `argv`, `ok`, `cwd`, and `handle`, the terminal that made
it. The graders read only what the fake recorded, never the agent's own account of what it did.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

OWN_HANDLE = "term_demo_a"
SENDER_HANDLE = "term_sender"
HOST_COMMAND = re.compile(r"^\s*(claude|codex)(\s+-.*)?$")
BELONGS = re.compile(r"belongs to (the|this) handoff", re.IGNORECASE)


def work_of(ctx) -> Path:
    return Path(ctx.origin).parent


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def state_of(ctx) -> dict:
    return read_json(work_of(ctx) / "orca-state" / "state.json")


def baseline_of(ctx) -> dict:
    return read_json(work_of(ctx) / "orca-state" / "baseline.json")


def calls_of(ctx) -> list[dict]:
    path = work_of(ctx) / "orca-state" / "calls.jsonl"
    if not path.is_file():
        return []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [{**json.loads(line), "index": index} for index, line in enumerate(lines)]


def pair(call: dict) -> tuple[str, ...]:
    return tuple(call["argv"][:2])


def option(call: dict, name: str) -> str | None:
    argv = call["argv"]
    for index, token in enumerate(argv):
        if token == name and index + 1 < len(argv):
            return argv[index + 1]
        if token.startswith(f"{name}="):
            return token[len(name) + 1:]
    return None


def calls_named(ctx, group: str, command: str, ok_only: bool = True) -> list[dict]:
    return [call for call in calls_of(ctx) if pair(call) == (group, command) and (call["ok"] or not ok_only)]


def closes_of(ctx, handle: str | None = None) -> list[dict]:
    found = calls_named(ctx, "terminal", "close", ok_only=False)
    return [call for call in found if handle is None or option(call, "--terminal") == handle]


def reports_to(ctx, handle: str) -> list[dict]:
    return [call for call in calls_named(ctx, "orchestration", "send") if option(call, "--to") == handle]


def terminal_entry(ctx, handle: str) -> dict | None:
    return next((item for item in state_of(ctx)["terminals"] if item["handle"] == handle), None)


def git(path: Path, *arguments: str) -> tuple[int, str]:
    completed = subprocess.run(["git", "-C", str(path), *arguments], capture_output=True, text=True, check=False)
    return completed.returncode, completed.stdout.strip()


def branch_tip(clone: Path, branch: str) -> str | None:
    code, output = git(clone, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    return output if code == 0 else None


def worktree_listed(state: dict, name: str) -> dict | None:
    return next((item for item in state["worktrees"] if item["displayName"] == name), None)


def worktree_gone(ctx, directory: str, clone: Path, branch: str, name: str) -> list[str]:
    problems = []
    if (work_of(ctx) / directory).exists():
        problems.append("the worktree folder is still there")
    if branch_tip(clone, branch) is not None:
        problems.append(f"the local branch {branch} is still there")
    if worktree_listed(state_of(ctx), name) is not None:
        problems.append("Orca still lists the worktree")
    return problems


def bash_commands(ctx) -> list[str]:
    return [str(call.get("input", {}).get("command", "")) for call in ctx.view.get("tool_calls", [])
            if call.get("name") == "Bash"]


def result(problems: list[str], good: str):
    return not problems, good if not problems else "; ".join(problems), {"problems": problems}


def main_clone_problems(ctx) -> list[str]:
    problems = []
    if not Path(ctx.origin).is_dir() or branch_tip(Path(ctx.origin), "main") is None:
        problems.append("the demo-a main clone or its main branch is gone")
    if not any(item["repoId"] == "demo-a" and item["isMainWorktree"] for item in state_of(ctx)["worktrees"]):
        problems.append("Orca no longer lists the demo-a main clone")
    return problems
