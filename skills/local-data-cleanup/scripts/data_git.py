"""Read-only Git work tree status for the git check."""

from __future__ import annotations

import os
import shutil
import subprocess

GIT_TIMEOUT = 120
STATUS_ARGS = ["status", "--porcelain=v1", "--untracked-files=normal"]


class GitProbe:
    def __init__(self) -> None:
        self.available = shutil.which("git") is not None
        self.cache: dict[tuple[str, str], str | None] = {}

    def run_status(self, directory: str, limit: str | None) -> str | None:
        """Return None when clean, otherwise a short reason."""
        command = ["git", "-C", directory, *STATUS_ARGS] + (["--", limit] if limit else [])
        environment = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"}
        try:
            done = subprocess.run(
                command, capture_output=True, text=True, errors="replace", env=environment, timeout=GIT_TIMEOUT
            )
        except (OSError, subprocess.SubprocessError) as error:
            return f"git status failed: {error}"
        if done.returncode != 0:
            return "git status failed: " + (done.stderr.strip().splitlines() or ["unknown error"])[0]
        if done.stdout.strip():
            return "uncommitted changes or untracked files that are not ignored"
        return None

    def status(self, directory: str, limit: str | None = None) -> str | None:
        key = (directory, limit or "")
        if key not in self.cache:
            self.cache[key] = self.run_status(directory, limit)
        return self.cache[key]


def enclosing_worktree(path: str) -> str | None:
    """Return the nearest ancestor folder that holds a .git entry."""
    parent = os.path.dirname(path)
    while True:
        if os.path.lexists(os.path.join(parent, ".git")):
            return parent
        next_parent = os.path.dirname(parent)
        if next_parent == parent:
            return None
        parent = next_parent
