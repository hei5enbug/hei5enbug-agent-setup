import json
import os
import subprocess
import sys
from pathlib import Path

from patch_tools import replace

repo = Path(sys.argv[1])
replace(str(repo), "config/settings.toml", "page_size = 20", "page_size = 50")

work = repo.parent
env = {**os.environ, "FAKE_ORCA_STATE": str(work / "orca-state" / "state.json")}
state = json.loads((work / "orca-state" / "state.json").read_text(encoding="utf-8"))
ids = {item["displayName"]: item["id"] for item in state["worktrees"]}


def orca(*arguments: str) -> None:
    subprocess.run([str(work / "fake-bin" / "orca"), *arguments, "--json"], cwd=repo, env=env, check=True,
                   capture_output=True, text=True)


for name in ("docs cleanup", "ABC-123 api"):
    orca("worktree", "rm", "--worktree", f"id:{ids[name]}", "--delete-branch")
orca("worktree", "set", "--worktree", f"id:{ids['ABC-123 demo']}", "--workspace-status", "completed")
