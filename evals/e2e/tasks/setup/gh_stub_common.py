"""Shared helper of the skill-issue-creator setup scripts: a stateful stub `gh` and a seeded tracker beside the repo.

The stub is the evaluation `gh` that the skill ships under `skills/skill-issue-creator/evals/files/bin/gh`. It sits in
`fake-bin/` of the run's work folder, reads its seeded issues from `trackers/` beside that folder, and keeps the issues,
edits, and comments written during the run in `gh-state/`. Every call lands in `gh.log`.
"""

from __future__ import annotations

import json
import shutil
import stat
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
STUB = REPO_ROOT / "skills" / "skill-issue-creator" / "evals" / "files" / "bin" / "gh"
TRACKER_FILE = "demo-org_demo-plugin.json"
OTHER_OPEN = {
    "number": 15, "title": "monthly-report: print the page owner under each team heading",
    "url": "https://github.com/demo-org/demo-plugin/issues/15", "state": "OPEN", "labels": [{"name": "enhancement"}],
    "author": {"login": "other-dev"},
    "body": "## Summary\nThe monthly overview does not name the owner of each team section.\n\n## Proposal\n"
            "1. Under the condition that a section names an owner, print the owner under its heading.\n",
}
CLOSED = {
    "number": 7, "title": "weekly-report: keep the section order of the page", "url":
    "https://github.com/demo-org/demo-plugin/issues/7", "state": "CLOSED", "labels": [{"name": "bug"}],
    "author": {"login": "demo-user"},
    "body": "## Summary\nThe overview sorted the team sections by name.\n\n## Proposal\n"
            "1. Under the condition that the page lists sections in an order, keep that order.\n",
}


def install(work: Path, issues: list[dict]) -> None:
    binary = work / "fake-bin"
    binary.mkdir()
    program = binary / "gh"
    shutil.copy(STUB, program)
    program.chmod(program.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    trackers = work / "trackers"
    trackers.mkdir()
    (trackers / TRACKER_FILE).write_text(json.dumps(issues, indent=2) + "\n", encoding="utf-8")
    (work / "gh-state").mkdir()
