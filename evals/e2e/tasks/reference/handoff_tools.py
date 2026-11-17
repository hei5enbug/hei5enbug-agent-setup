"""Run the fake `orca` as the session under test would, for the reference solutions of the handoff tasks."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def orca(repo: str | Path, *arguments: str, handle: str = "term_demo_a") -> dict:
    work = Path(repo).parent
    env = {**os.environ, "FAKE_ORCA_STATE": str(work / "orca-state" / "state.json"), "ORCA_TERMINAL_HANDLE": handle}
    done = subprocess.run([str(work / "fake-bin" / "orca"), *arguments, "--json"], cwd=repo, env=env, check=True,
                          capture_output=True, text=True)
    return json.loads(done.stdout)


def worktree_id(repo: str | Path, name: str) -> str:
    state = json.loads((Path(repo).parent / "orca-state" / "state.json").read_text(encoding="utf-8"))
    return next(item["id"] for item in state["worktrees"] if item["displayName"] == name)


def report(repo: str | Path, body: str) -> None:
    orca(repo, "orchestration", "send", "--to", "term_sender", "--from", "term_demo_a", "--subject", "Report",
         "--body", body, "--type", "status")
