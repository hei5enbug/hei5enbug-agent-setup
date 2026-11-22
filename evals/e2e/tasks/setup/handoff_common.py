"""Shared seeding for T31 to T34: a fake Orca with two repositories, child worktrees, and agent and shell terminals.

The notes-cli repository plays demo-a's main clone and `demo-b` is a second clone beside it, both with a bare origin.
The state file, the call log, and the baseline live in `orca-state/` in the run's work folder, the parent of `repo`.
All names are fictional.
"""

from __future__ import annotations

import json
import shutil
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from T21 import add_worktree, git, make_clone, record, with_origin  # noqa: E402

OWN_HANDLE = "term_demo_a"
SENDER_HANDLE = "term_sender"
SHELL_PROMPT = "% "


@dataclass(frozen=True)
class Child:
    """A child worktree of demo-a: pushed or with an unpushed commit, and clean or with an uncommitted change."""

    directory: str
    branch: str
    name: str
    pushed: bool = True
    dirty: bool = False
    status: str = "in-review"


@dataclass(frozen=True)
class Terminal:
    """A terminal in the workspace named `workspace`: an agent, or a shell with its history and typed input."""

    handle: str
    workspace: str
    agent: str | None = None
    history: tuple[str, ...] = ()
    typed: str = ""
    title: str = "zsh"

    def entry(self, worktree_id: str) -> dict:
        found: dict = {"handle": self.handle, "worktreeId": worktree_id, "title": self.title}
        if self.agent:
            return {**found, "agentIdentity": self.agent, "screen": ["❯ "]}
        prompt = f"{self.workspace} {SHELL_PROMPT}"
        return {**found, "prompt": prompt, "history": [prompt + command for command in self.history],
                "typed": self.typed, "process": None}


@dataclass
class Seed:
    children: tuple[Child, ...] = ()
    terminals: tuple[Terminal, ...] = field(default_factory=tuple)


def agent(handle: str, workspace: str) -> Terminal:
    return Terminal(handle, workspace, agent="claude", title="claude")


def build(repo_argument: str, seed: Seed) -> None:
    repo = Path(repo_argument).resolve()
    work = repo.parent
    with_origin(repo, work / "demo-a-origin.git")
    clone_b = make_clone(work, "demo-b")
    main_a = record("demo-a", repo, "main", "demo-a", True, None, None)
    main_b = record("demo-b", clone_b, "main", "demo-b", True, None, None)
    worktrees = [main_a, main_b]
    for child in seed.children:
        path = work / f"demo-a-{child.directory}"
        add_worktree(repo, path, child.branch, push_all=child.pushed)
        if child.dirty:
            (path / "work.txt").write_text(f"{child.branch} part one\nunsaved line\n", encoding="utf-8")
        worktrees.append(record("demo-a", path, child.branch, child.name, False, child.status, main_a["id"]))
    ids = {item["displayName"]: item["id"] for item in worktrees}
    terminals = [item.entry(ids[item.workspace]) for item in seed.terminals]
    repos = [{"id": item["repoId"], "name": item["displayName"], "path": item["path"]} for item in (main_a, main_b)]

    state_dir = work / "orca-state"
    state_dir.mkdir()
    state = {"repos": repos, "worktrees": worktrees, "terminals": terminals, "messages": []}
    (state_dir / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    baseline = {
        "worktrees": {item["id"]: {"head": git(Path(item["path"]), "rev-parse", "HEAD"), "record": item}
                      for item in worktrees},
        "terminals": {item["handle"]: item for item in terminals},
    }
    (state_dir / "baseline.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")

    binary = work / "fake-bin"
    binary.mkdir()
    program = binary / "orca"
    shutil.copy(Path(__file__).with_name("fake_orca.py"), program)
    program.chmod(program.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
