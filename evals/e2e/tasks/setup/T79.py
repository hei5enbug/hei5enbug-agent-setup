"""History and rules that require a bracketed ticket key in every subject, then one unstaged src/demo.py change."""

from __future__ import annotations

import sys
from pathlib import Path

from commit_common import STAGED_DEMO, add_history, git, write

RULES = """# Repository rules

- Python 3.11 or newer, standard library only.
- Run `python3 -m pytest -q` before reporting a change as done. Do not edit existing tests to make a change pass.

## Commits

- Commit message format: `<type>: [ABC-123] <description>`. The bracketed ticket key is required in every subject.
- Use the types feat, fix, refactor, docs, test, and chore. Keep the subject at most 72 characters.
"""

HISTORY = (
    "feat: [ABC-101] add greeting helper",
    "fix: [ABC-102] handle empty input",
    "docs: [ABC-103] describe usage",
    "test: [ABC-104] cover boundary names",
    "refactor: [ABC-105] simplify string building",
    "fix: [ABC-106] trim whitespace-only names",
)


def main(repo: str) -> None:
    root = Path(repo)
    write(root, "AGENTS.md", RULES)
    git(root, "add", "--", "AGENTS.md")
    git(root, "commit", "-q", "-m", "chore: [ABC-100] document the commit format")
    add_history(root, HISTORY)
    write(root, "src/demo.py", STAGED_DEMO)


if __name__ == "__main__":
    main(sys.argv[1])
