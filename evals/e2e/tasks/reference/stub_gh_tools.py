"""Run the stub gh of a skill-issue-creator task the way an agent would, for reference and broken-input scripts."""

import os
import subprocess
from pathlib import Path

REPO = "demo-org/demo-plugin"
BODY = """## Summary
The weekly overview prints empty team sections as a heading followed by `(none)`.

## Observations
- Three of five sections were empty in one report.

## Gap in current rules
Step 3 of `skills/weekly-report/SKILL.md` prints every heading.

## Proposal
1. Under the condition that a team section has no items, leave it out of the overview.

## Acceptance criteria
1. A page with an empty section produces an overview with no heading for it.

## Evidence
- Related: #7.
"""


def gh(repo_folder: str, *arguments: str, stdin: str = "") -> subprocess.CompletedProcess:
    work = Path(repo_folder).resolve().parent
    env = {**os.environ, "FAKE_GH_LOG": str(work / "gh.log"), "FAKE_GH_STATE": str(work / "gh-state")}
    return subprocess.run([str(work / "fake-bin" / "gh"), *arguments], input=stdin, text=True, capture_output=True,
                          env=env, check=True)


def search(repo_folder: str) -> None:
    gh(repo_folder, "issue", "list", "--repo", REPO, "--state", "all", "--search", "empty sections", "--json",
       "number,title,url,state,labels,author", "--limit", "20")


def create(repo_folder: str, body: str = BODY) -> None:
    gh(repo_folder, "issue", "create", "--repo", REPO, "--title", "weekly-report: leave out empty sections", "--label",
       "enhancement", "--body-file", "-", stdin=body)
