"""Add a changelog and a repository skill that sets the changelog line format, for the named-skill case."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CHANGELOG = """# Changelog

## Unreleased

## 0.3.1

* Memo search ignores case.
* Tags are kept when a memo is shown.
"""

SKILL = """---
name: changelog-entry
description: Add a changelog entry to CHANGELOG.md in this repository's line format. Use when a change needs a changelog entry.
---

# Changelog entry

Add exactly one line directly below the `## Unreleased` heading of `CHANGELOG.md`:

`- <kind>: <summary> [entry-v2]`

- `<kind>` is `added`, `changed`, or `fixed`.
- `<summary>` is one imperative sentence of at most 60 characters with no trailing period.
- End the line with the literal tag `[entry-v2]`, because the release script finds entries by it.
- Never edit the lines under a released version heading.
"""

SKILL_PATHS = (".claude/skills/changelog-entry/SKILL.md", ".agents/skills/changelog-entry/SKILL.md")


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(repo: str) -> None:
    root = Path(repo)
    write(root, "CHANGELOG.md", CHANGELOG)
    for relative in SKILL_PATHS:
        write(root, relative, SKILL)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m",
                    "Add the changelog and the changelog-entry skill"], cwd=root, check=True, capture_output=True)


if __name__ == "__main__":
    main(sys.argv[1])
