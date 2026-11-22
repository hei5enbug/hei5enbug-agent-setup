#!/usr/bin/env python3
"""Count how many seeded defects one `text_review.py review` run reports, for the loop-shape candidate (d) of issue 102.

`cases/draft-defects.txt` holds three defects of different types against `cases/work-item.txt`: a repeated sentence
(removable), "after it runs" that can mean the cleanup or the export (ambiguous), and the missing rollback (missing).
`cases/draft-clean.txt` holds none. A run passes on the defects draft when its findings cover all three, and on the clean
draft when it returns none. All data is fictional.

  python3 evals/text-review-recall/recall.py --script <text_review.py> --runs 5 --out <folder> [--dry-run]
  python3 evals/text-review-recall/recall.py --score <folder>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

CASES = Path(__file__).resolve().parent / "cases"
KIND = "ticket-comment"
DEFECTS = (("removable", "finishes within 20 minutes"), ("ambiguous", "cleanup"), ("missing", "roll"))
DRAFTS = ("defects", "clean")


def covered(findings: list[dict]) -> list[str]:
    """The seeded defects that the findings report: a finding of the defect's type that names its keyword."""
    return [kind for kind, word in DEFECTS
            if any(item.get("type") == kind and word in f"{item.get('quote', '')} {item.get('reason', '')}".lower()
                   for item in findings)]


def passes(draft: str, findings: list[dict]) -> bool:
    return len(covered(findings)) == len(DEFECTS) if draft == "defects" else not findings


def command(script: Path, draft: str) -> list[str]:
    return [sys.executable, str(script), "review", "--kind", KIND, "--draft", str(CASES / f"draft-{draft}.txt"),
            "--source", str(CASES / "work-item.txt")]


def run_all(script: Path, runs: int, out: Path, dry_run: bool) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for draft in DRAFTS:
        for number in range(1, runs + 1):
            line = command(script, draft)
            if dry_run:
                print(" ".join(line))
                continue
            done = subprocess.run(line, capture_output=True, text=True, check=False)
            (out / f"{draft}-{number}.json").write_text(
                json.dumps({"exit": done.returncode, "stdout": done.stdout.strip().splitlines()[-1:] or [""]}), encoding="utf-8")


def score(out: Path) -> dict[str, list[tuple[int, int]]]:
    """Per draft, one (defects found, passed) pair per run; a run whose output is not a review result counts as failed."""
    table: dict[str, list[tuple[int, int]]] = {draft: [] for draft in DRAFTS}
    for draft in DRAFTS:
        for path in sorted(out.glob(f"{draft}-*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            try:
                findings = json.loads(record["stdout"][0])["findings"]
            except (ValueError, KeyError, IndexError, TypeError):
                table[draft].append((0, 0))
                continue
            table[draft].append((len(covered(findings)), int(passes(draft, findings))))
    return table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--script", type=Path)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--score", type=Path)
    args = parser.parse_args(argv)
    if args.score:
        for draft, rows in score(args.score).items():
            print(f"{draft}: passed {sum(p for _, p in rows)} of {len(rows)}; defects found per run {[d for d, _ in rows]}")
        return 0
    if not (args.script and args.out):
        parser.error("--script and --out are required unless --score is given")
    run_all(args.script, args.runs, args.out, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
