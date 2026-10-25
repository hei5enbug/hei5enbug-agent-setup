"""Helpers shared by the reference solution scripts. A reference turns a materialized fixture into a correct run."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def replace(repo: str | Path, relative: str, old: str, new: str) -> None:
    path = Path(repo) / relative
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{relative}: expected exactly one match for {old[:60]!r}, found {text.count(old)}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def write(repo: str | Path, relative: str, text: str) -> None:
    path = Path(repo) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def append(repo: str | Path, relative: str, text: str) -> None:
    path = Path(repo) / relative
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def commit(repo: str | Path, message: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "Demo Dev", "GIT_AUTHOR_EMAIL": "dev@example.com",
           "GIT_COMMITTER_NAME": "Demo Dev", "GIT_COMMITTER_EMAIL": "dev@example.com",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    for command in (["git", "add", "-A"], ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                                            "commit", "-q", "-m", message]):
        subprocess.run(command, cwd=repo, env=env, check=True, capture_output=True)
