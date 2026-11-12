"""Build the fake Orca and Git state for T21 beside the notes-cli repository, which plays demo-a's main clone.

Everything lives in the run's work folder, the parent of `repo`: bare origins, the demo-b and demo-c clones, four linked
worktrees, a fake `orca` on `fake-bin/`, and `orca-state/` with the state file, the call log, and the baseline.
"""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ISSUE_LINK = "https://example.com/browse/ABC-123"
FOLDER_ID = "folder-abc-123"


def git(path: Path, *arguments: str) -> str:
    completed = subprocess.run(["git", "-C", str(path), *arguments], capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(arguments)} failed in {path}: {completed.stderr.strip()}")
    return completed.stdout.strip()


def with_origin(clone: Path, origin: Path) -> None:
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    git(clone, "remote", "add", "origin", str(origin))
    git(clone, "push", "-q", "-u", "origin", "main")


def make_clone(work: Path, name: str) -> Path:
    clone = work / name
    clone.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(clone)], check=True)
    (clone / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    git(clone, "add", "-A")
    git(clone, "commit", "-q", "-m", "Initial commit")
    with_origin(clone, work / f"{name}-origin.git")
    return clone


def add_worktree(clone: Path, path: Path, branch: str, push_all: bool) -> None:
    git(clone, "worktree", "add", "-q", "-b", branch, str(path), "main")
    (path / "work.txt").write_text(f"{branch} part one\n", encoding="utf-8")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", f"Add {branch} part one")
    git(path, "push", "-q", "-u", "origin", branch)
    if not push_all:
        (path / "work.txt").write_text(f"{branch} part one\n{branch} part two\n", encoding="utf-8")
        git(path, "commit", "-q", "-a", "-m", f"Add {branch} part two")


def record(repo_id: str, path: Path, branch: str, name: str, main: bool, status: str | None, parent: str | None,
           references: list[str] | None = None) -> dict:
    return {
        "id": f"{repo_id}::{path}", "repoId": repo_id, "path": str(path), "kind": "git", "isMainWorktree": main,
        "branch": f"refs/heads/{branch}", "displayName": name, "displayNameMode": "automatic" if main else "manual",
        "workspaceStatus": status, "comment": "", "parentWorktreeId": parent, "references": references or [],
    }


def main(repo_argument: str) -> None:
    repo = Path(repo_argument).resolve()
    work = repo.parent
    with_origin(repo, work / "demo-a-origin.git")
    clone_b, clone_c = make_clone(work, "demo-b"), make_clone(work, "demo-c")
    docs, login = work / "demo-a-docs-cleanup", work / "demo-a-login-spike"
    api, export = work / "demo-b-abc-123-api", work / "demo-c-invoice-export"
    add_worktree(repo, docs, "docs-cleanup", push_all=True)
    add_worktree(repo, login, "login-spike", push_all=False)
    add_worktree(clone_b, api, "abc-123-api", push_all=True)
    add_worktree(clone_c, export, "invoice-export", push_all=True)

    main_a = record("demo-a", repo, "main", "demo-a", True, None, None)
    main_b = record("demo-b", clone_b, "main", "demo-b", True, None, None)
    main_c = record("demo-c", clone_c, "main", "demo-c", True, None, None)
    folder = {
        "id": FOLDER_ID, "repoId": None, "path": None, "kind": "folder", "isMainWorktree": False, "branch": "",
        "displayName": "ABC-123 demo", "displayNameMode": "manual", "workspaceStatus": "in-progress", "comment": "",
        "parentWorktreeId": None, "references": [ISSUE_LINK],
    }
    worktrees = [
        main_a, main_b, main_c, folder,
        record("demo-a", docs, "docs-cleanup", "docs cleanup", False, "in-review", main_a["id"]),
        record("demo-a", login, "login-spike", "login spike", False, "in-progress", main_a["id"]),
        record("demo-b", api, "abc-123-api", "ABC-123 api", False, "in-review", FOLDER_ID, [ISSUE_LINK]),
        record("demo-c", export, "invoice-export", "invoice export", False, "in-progress", main_c["id"]),
    ]
    repos = [{"id": item["repoId"], "name": item["displayName"], "path": item["path"]}
             for item in (main_a, main_b, main_c)]
    terminals = [{"handle": "term_demo_a", "worktreeId": main_a["id"], "title": "zsh"}]

    state_dir = work / "orca-state"
    state_dir.mkdir()
    (state_dir / "state.json").write_text(json.dumps(
        {"repos": repos, "worktrees": worktrees, "terminals": terminals}, indent=2), encoding="utf-8")
    baseline = {
        item["id"]: {"head": git(Path(item["path"]), "rev-parse", "HEAD") if item["kind"] == "git" else None,
                     "record": item}
        for item in worktrees
    }
    (state_dir / "baseline.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")

    binary = work / "fake-bin"
    binary.mkdir()
    program = binary / "orca"
    shutil.copy(Path(__file__).with_name("fake_orca.py"), program)
    program.chmod(program.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


if __name__ == "__main__":
    main(sys.argv[1])
