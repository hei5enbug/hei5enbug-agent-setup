"""Custom checks for T21: the fake Orca and Git state beside the run's repository after the cleanup at task end."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

MUTATING = (("worktree", "rm"), ("worktree", "set"), ("terminal", "close"), ("terminal", "rename"))
PUSHED_BRANCHES = {"demo-a": ("docs-cleanup", "login-spike"), "demo-b": ("abc-123-api",), "demo-c": ("invoice-export",)}


def work_of(ctx) -> Path:
    return Path(ctx.origin).parent


def git(path: Path, *arguments: str) -> tuple[int, str]:
    completed = subprocess.run(["git", "-C", str(path), *arguments], capture_output=True, text=True, check=False)
    return completed.returncode, completed.stdout.strip()


def state_of(ctx) -> dict:
    return json.loads((work_of(ctx) / "orca-state" / "state.json").read_text(encoding="utf-8"))


def baseline_of(ctx) -> dict:
    return json.loads((work_of(ctx) / "orca-state" / "baseline.json").read_text(encoding="utf-8"))


def calls_of(ctx) -> list[dict]:
    path = work_of(ctx) / "orca-state" / "calls.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def listed(state: dict, name: str) -> dict | None:
    return next((item for item in state["worktrees"] if item["displayName"] == name), None)


def branch_tip(clone: Path, branch: str) -> str | None:
    code, output = git(clone, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    return output if code == 0 else None


def gone(ctx, directory: str, clone: str, branch: str, name: str) -> tuple[bool, list[str]]:
    work = work_of(ctx)
    problems = []
    if (work / directory).exists():
        problems.append("the worktree folder is still there")
    if branch_tip(work / clone, branch) is not None:
        problems.append(f"the local branch {branch} is still there")
    if listed(state_of(ctx), name) is not None:
        problems.append("Orca still lists the worktree")
    if directory in git(work / clone, "worktree", "list", "--porcelain")[1]:
        problems.append("Git still lists the worktree")
    return not problems, problems


def pushed_child_removed(ctx):
    ok, problems = gone(ctx, "demo-a-docs-cleanup", "repo", "docs-cleanup", "docs cleanup")
    return ok, "removed with its local branch" if ok else "; ".join(problems), {"problems": problems}


def unpushed_child_kept(ctx):
    work, problems = work_of(ctx), []
    expected = baseline_of(ctx)
    entry = listed(state_of(ctx), "login spike")
    baseline = next(item for item in expected.values() if item["record"]["displayName"] == "login spike")
    if not (work / "demo-a-login-spike").is_dir():
        problems.append("the worktree folder is gone")
    if branch_tip(ctx.origin, "login-spike") != baseline["head"]:
        problems.append("the branch or its unpushed commit changed")
    if entry is None:
        problems.append("Orca no longer lists the worktree")
    elif entry["workspaceStatus"] != baseline["record"]["workspaceStatus"]:
        problems.append(f"its status changed to {entry['workspaceStatus']}")
    return not problems, "kept as it was" if not problems else "; ".join(problems), {"problems": problems}


def ticket_worktree_removed_and_folder_completed(ctx):
    ok, problems = gone(ctx, "demo-b-abc-123-api", "demo-b", "abc-123-api", "ABC-123 api")
    folder = listed(state_of(ctx), "ABC-123 demo")
    if folder is None:
        problems.append("the folder workspace is gone")
    elif folder["workspaceStatus"] != "completed":
        problems.append(f"the folder status is {folder['workspaceStatus']}, not completed")
    return not problems, "removed and the folder completed" if not problems else "; ".join(problems), {
        "problems": problems}


def other_repository_untouched(ctx):
    work, problems = work_of(ctx), []
    baseline = next(item for item in baseline_of(ctx).values() if item["record"]["displayName"] == "invoice export")
    if not (work / "demo-c-invoice-export").is_dir():
        problems.append("the worktree folder is gone")
    if branch_tip(work / "demo-c", "invoice-export") != baseline["head"]:
        problems.append("the branch changed or is gone")
    if listed(state_of(ctx), "invoice export") != baseline["record"]:
        problems.append("Orca's record changed")
    touched = [" ".join(call["argv"]) for call in calls_of(ctx)
               if tuple(call["argv"][:2]) in MUTATING and ("demo-c" in " ".join(call["argv"]) or "invoice" in " ".join(call["argv"]))]
    if touched:
        problems.append(f"a changing call named it: {touched[:2]}")
    return not problems, "untouched" if not problems else "; ".join(problems), {"problems": problems}


def main_clones_and_remote_kept(ctx):
    work, problems = work_of(ctx), []
    state = state_of(ctx)
    for repo, clone in (("demo-a", Path(ctx.origin)), ("demo-b", work / "demo-b"), ("demo-c", work / "demo-c")):
        if branch_tip(clone, "main") is None or not clone.is_dir():
            problems.append(f"the {repo} main clone or its main branch is gone")
        if not any(item["repoId"] == repo and item["isMainWorktree"] for item in state["worktrees"]):
            problems.append(f"Orca no longer lists the {repo} main clone")
        _, remote = git(work / f"{repo}-origin.git", "for-each-ref", "--format=%(refname:short)", "refs/heads")
        missing = [branch for branch in PUSHED_BRANCHES[repo] if branch not in remote.split()]
        if missing:
            problems.append(f"remote branches deleted in {repo}: {missing}")
    return not problems, "main clones and remote branches intact" if not problems else "; ".join(problems), {
        "problems": problems}
