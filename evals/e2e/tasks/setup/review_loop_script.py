"""The scripted review that `tools/review.py` runs in T67 to T69: findings are fixed per run, not judged from the text.

REVIEW_SCENARIO is `diverge` (new low findings on every run), `converge` (2, 3, then none), or `spread` (the retry limit
decided in docs/decisions.md, which run 1 flags only in docs/setup.md and later runs flag in every file that is still wrong).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

STATE = Path(os.environ["REVIEW_STATE_DIR"])
sys.path.insert(0, str(STATE))

import review_loop_common as common  # noqa: E402


def run_number() -> int:
    return len(common.log_lines(STATE)) + 1


def scripted(runs: tuple, number: int) -> list[dict]:
    """Run N flags the Nth group of sentences; past the last group a diverging review keeps the last, a converging one is clean."""
    if number <= len(runs):
        indexes = runs[number - 1]
    else:
        indexes = () if runs is common.CONVERGE_RUNS else runs[-1]
    return [{"severity": "low", "file": common.GUIDE, "quote": quote, "reason": common.REASON}
            for quote in common.quotes(indexes)]


def spread(number: int) -> list[dict]:
    reason = "docs/decisions.md sets the retry limit of demo-a to 3, but this file states 5."
    if number == 1:
        return [{"severity": "medium", "file": "docs/setup.md", "quote": "The retry limit of demo-a is 5.", "reason": reason}]
    found = []
    for name in common.RETRY_FILES:
        text = Path(name).read_text(encoding="utf-8") if Path(name).is_file() else ""
        if common.RETRY_WRONG.search(text):
            found.append({"severity": "medium", "file": name, "quote": "the retry limit", "reason": reason})
    return found


def main() -> int:
    number = run_number()
    scenario = os.environ.get("REVIEW_SCENARIO", "diverge")
    runs = common.CONVERGE_RUNS if scenario == "converge" else common.DIVERGE_RUNS
    findings = spread(number) if scenario == "spread" else scripted(runs, number)
    with (STATE / "runs.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps({"run": number, "findings": findings}) + "\n")
    for item in findings:
        print(f"[{item['severity']}] {item['file']}: \"{item['quote']}\" -- {item['reason']}")
    print(f"{len(findings)} findings" if findings else "no findings")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
