"""Reference run for T79: start a Claude Code session in demo-kit's workspace with its model and effort, and hand it the issue."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def orca(*arguments: str) -> dict:
    completed = subprocess.run(["orca", *arguments, "--json"], capture_output=True, text=True, check=True)
    return json.loads(completed.stdout)["result"]


def main(repo_argument: str) -> None:
    repo = Path(repo_argument).resolve()
    os.environ["PATH"] = f"{repo.parent / 'fake-bin'}{os.pathsep}{os.environ['PATH']}"
    os.environ["FAKE_ORCA_STATE"] = str(repo.parent / "orca-state" / "state.json")
    workspace = next(item["id"] for item in orca("worktree", "list")["worktrees"] if item["displayName"] == "demo-kit")
    created = orca("terminal", "create", "--worktree", f"id:{workspace}", "--command",
                   "claude --model claude-opus-5-5 --effort high")
    handle = created["terminal"]["handle"]
    orca("terminal", "wait", "--terminal", handle, "--for", "tui-idle", "--timeout-ms", "60000")
    orca("terminal", "send", "--terminal", handle, "--text", "Run skill-issue-creator for one issue about release-notes.", "--enter")


if __name__ == "__main__":
    main(sys.argv[1])
