"""Helpers of the T130 to T132 reference solutions: run the scripted review the way the agent would, and fix findings."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from patch_tools import write


def run_review(repo: str, scenario: str) -> str:
    state = Path(repo).parent / "review-state"
    env = {**os.environ, "REVIEW_STATE_DIR": str(state), "REVIEW_SCENARIO": scenario, "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, "-B", "tools/review.py"], cwd=repo, env=env, capture_output=True, text=True)
    return done.stdout


def drop_quotes(repo: str, output: str) -> None:
    path = Path(repo) / "docs/guide.md"
    text = path.read_text(encoding="utf-8")
    for line in output.splitlines():
        if '"' in line:
            quote = line.split('"')[1]
            text = text.replace(quote + "\n", "")
    write(repo, "docs/guide.md", text)
