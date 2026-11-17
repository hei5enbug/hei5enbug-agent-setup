"""Helpers for the reference solutions of T104 to T106: run the seeded review script and fix what it flags."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SETUP = Path(__file__).resolve().parents[1] / "setup"
sys.path.insert(0, str(SETUP))

from repeated_review_common import guide_fixes  # noqa: E402


def run_review(repo: Path) -> list[dict]:
    subprocess.run([sys.executable, "-B", "tools/review.py"], cwd=repo, check=False, capture_output=True, text=True)
    log = (repo.parent / "review-state" / "log.jsonl").read_text(encoding="utf-8").splitlines()
    return json.loads(log[-1])["findings"]


def fix_guide(repo: Path, findings: list[dict]) -> None:
    fixes = guide_fixes()
    path = repo / "docs" / "guide.md"
    text = path.read_text(encoding="utf-8")
    for finding in findings:
        text = text.replace(finding["sentence"], fixes[finding["sentence"]])
    path.write_text(text, encoding="utf-8")


def fix_guide_rounds(repo: Path, rounds: int) -> None:
    for _ in range(rounds):
        fix_guide(repo, run_review(repo))
