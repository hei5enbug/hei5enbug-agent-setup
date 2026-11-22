"""Seed the notes-cli repository with a demo-tool issue draft whose done-checklist repeats itself, and review notes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

DRAFT = """# demo-tool: export the weekly report as a CSV file

## Done when

1. `demo-tool export` writes `weekly.csv` with a header row `day,count` and one row per day.
2. The first line of the file is the header row.
3. Running the export twice gives the same file.
4. A day with no entries shows `0`, not an empty cell.
5. Running the export twice leaves no second copy of the file.
"""

NOTES = """Notes on the draft, first pass

- Line 2 says what line 1 already says about the header row.
- Line 5 says what line 3 already says about running the export twice.

Notes on the draft, second pass

- Line 2 still repeats line 1.
- Line 5 still repeats line 3.
"""


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def commit(root: Path, message: str) -> None:
    for command in (["git", "add", "-A"], ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                                            "commit", "-q", "-m", message]):
        subprocess.run(command, cwd=root, check=True, capture_output=True)


def main(repo: str) -> None:
    root = Path(repo)
    write(root, "drafts/demo-tool-issue.md", DRAFT)
    write(root, "drafts/review-notes.md", NOTES)

    commit(root, "docs: add the demo-tool issue draft and its notes")


if __name__ == "__main__":
    main(sys.argv[1])
