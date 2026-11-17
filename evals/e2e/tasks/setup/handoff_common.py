"""Build the fake Orca and Git state shared by the handoff tasks T59 to T62, beside the notes-cli repository.

The repository plays demo-a's main clone and the session under test runs in it as terminal `term_demo_a`. Everything
lives in the run's work folder, the parent of `repo`: bare origins, the demo-b clone, optional child worktrees of
demo-a, a fake `orca` on `fake-bin/`, and `orca-state/` with the state file, the call log, and the baseline.
"""

from __future__ import annotations

import json
import shutil
import stat
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from T21 import add_worktree, git, make_clone, record, with_origin  # noqa: E402

OWN_HANDLE = "term_demo_a"
SENDER_HANDLE = "term_sender"
PROMPT_LINE = "user@host demo %"


def agent_terminal(handle: str, worktree_id: str, title: str = "claude") -> dict:
    return {"handle": handle, "worktreeId": worktree_id, "title": title, "agentIdentity": "claude"}


def shell_terminal(handle: str, worktree_id: str, screen: list[str], stream: list[str] | None = None) -> dict:
    return {"handle": handle, "worktreeId": worktree_id, "title": "zsh", "screen": screen,
            "stream": screen if stream is None else stream}


def build(repo_argument: str, child: str | None = None, dirty_child: bool = False, extra_terminals=None) -> dict:
    """Seed the state. `child` is "docs-cleanup" or "login-spike", a pushed child worktree of demo-a; a dirty child
    also holds an uncommitted change. `extra_terminals` receives the demo-a and demo-b main records and returns
    terminal records to add."""
    repo = Path(repo_argument).resolve()
    work = repo.parent
    with_origin(repo, work / "demo-a-origin.git")
    clone_b = make_clone(work, "demo-b")
    main_a = record("demo-a", repo, "main", "demo-a", True, None, None)
    main_b = record("demo-b", clone_b, "main", "demo-b", True, None, None)
    worktrees = [main_a, main_b]
    if child:
        path = work / f"demo-a-{child}"
        add_worktree(repo, path, child, push_all=True)
        if dirty_child:
            (path / "work.txt").write_text(f"{child} part one\nuncommitted line\n", encoding="utf-8")
        worktrees.append(record("demo-a", path, child, child.replace("-", " "), False, "in-progress", main_a["id"]))
    terminals = [agent_terminal(OWN_HANDLE, main_a["id"]), agent_terminal(SENDER_HANDLE, main_b["id"])]
    terminals += extra_terminals(main_a, main_b) if extra_terminals else []
    repos = [{"id": item["repoId"], "name": item["displayName"], "path": item["path"]} for item in (main_a, main_b)]

    state_dir = work / "orca-state"
    state_dir.mkdir()
    (state_dir / "state.json").write_text(json.dumps(
        {"repos": repos, "worktrees": worktrees, "terminals": terminals}, indent=2), encoding="utf-8")
    baseline = {item["id"]: {"head": git(Path(item["path"]), "rev-parse", "HEAD"), "record": item}
                for item in worktrees}
    baseline["terminals"] = terminals
    (state_dir / "baseline.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")

    binary = work / "fake-bin"
    binary.mkdir()
    program = binary / "orca"
    shutil.copy(Path(__file__).with_name("fake_orca.py"), program)
    program.chmod(program.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return {"work": work, "main_a": main_a, "main_b": main_b}
