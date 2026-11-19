"""Shared by the setup scripts of the commit-demo tasks: write files, make history, leave the seeded state."""

from __future__ import annotations

import subprocess
from pathlib import Path

SECRET_LINE = "DEMO_TOKEN=demo-4471-local-only"
STAGED_DEMO = 'def greet(name):\n    cleaned = (name or "").strip()\n    return "hello " + (cleaned or "there")\n'
README_WIP = "\n## Usage\n\nCall `greet(name)`; usage notes are still a draft.\n"


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args], cwd=root,
                   check=True, capture_output=True)


def add_history(root: Path, subjects: tuple[str, ...]) -> None:
    """One small commit per subject, so the subjects are the whole style evidence of the repository."""
    for number, subject in enumerate(subjects, 1):
        log = root / "docs" / "changes.txt"
        previous = log.read_text(encoding="utf-8") if log.exists() else ""
        write(root, "docs/changes.txt", previous + f"{number}. {subject}\n")
        git(root, "add", "--", "docs/changes.txt")
        git(root, "commit", "-q", "-m", subject)
