"""The two new text review cases: a draft with one planted defect, reviewed by `scripts/text_review.py review` with the
candidate model. A case passes when one finding names the planted defect and no finding falls outside it."""

from __future__ import annotations

import json
import re
from pathlib import Path

RULES = (
    "Say what changed and why in a few plain sentences. Name nothing the sources do not show. "
    "A reader must be able to act on the text without asking again.\n"
)

CASES = {
    "TR1": {
        "kind": "pr-description",
        "draft": (
            "Add a CSV export to the inventory report. The export writes the columns sku, name, and quantity, one row per item, and "
            "quotes a name that contains a comma. It also fixes the stale cache after an import. Four new tests cover the header, "
            "an empty report, a quoted name, and the row order, and all of them pass.\n"
        ),
        "source": (
            "Change summary\n- New function `export_csv(report)` in inventory/export.py: header row sku,name,quantity, then one row per item.\n"
            "- A name that contains a comma is quoted.\n- Four new tests in tests/test_export.py (header, empty report, quoted name, row order); all pass.\n"
            "- No other file changed.\n"
        ),
        "planted": {"problem": r"cache|stale|import", "type": ("removable", "ambiguous")},
    },
    "TR2": {
        "kind": "final-report",
        "draft": (
            "I fixed the 500 on /export when the filter is empty. The handler now treats an empty filter as no filter and returns "
            "every row. I added a test for it, and all tests pass.\n"
        ),
        "source": (
            "User request: Fix the 500 on /export when the filter is empty, and tell me if anything is left undone.\n\n"
            "Work log\n- Cause: build_query() joined an empty filter list into an invalid WHERE clause. Fixed in api/export.py.\n"
            "- Added tests/test_export_empty.py; the full suite passes (31 tests).\n"
            "- Checked /export?format=xlsx with an empty filter: it still returns 500 because of a different error in api/xlsx.py. "
            "I did not change it; it is outside this request.\n"
        ),
        "planted": {"problem": r"xlsx", "type": ("missing", "ambiguous")},
    },
}


def seed(case_id: str, out: Path) -> dict[str, Path]:
    case = CASES[case_id]
    out.mkdir(parents=True, exist_ok=True)
    paths = {"draft": out / "draft.txt", "rules": out / "rules.txt", "source": out / "source.txt"}
    paths["draft"].write_text(case["draft"], encoding="utf-8")
    paths["rules"].write_text(RULES, encoding="utf-8")
    paths["source"].write_text(case["source"], encoding="utf-8")
    return paths


def command(case_id: str, paths: dict[str, Path], script: Path, model: str) -> list[str]:
    import sys

    return [sys.executable, str(script), "review", "--kind", CASES[case_id]["kind"], "--draft", str(paths["draft"]), "--rules",
            str(paths["rules"]), "--source", str(paths["source"]), "--model", model, "--reviews", "1"]


def parse_output(stdout: str) -> dict:
    line = next((line for line in reversed(stdout.strip().splitlines()) if line.strip().startswith("{")), "")
    return json.loads(line) if line else {}


def failures(case_id: str, output: dict) -> list[str]:
    """The reasons a review fails the case: no finding on the planted defect, a failed review, or a finding outside it."""
    planted = CASES[case_id]["planted"]
    pattern = re.compile(planted["problem"], re.IGNORECASE)
    if output.get("errors") or "findings" not in output:
        return [f"the review gave no verdict: {json.dumps(output)[:300]}"]
    found, outside = [], []
    for item in output["findings"]:
        text = f"{item.get('quote', '')} {item.get('reason', '')}"
        (found if pattern.search(text) else outside).append(item)
    reasons = []
    if not found:
        reasons.append("no finding names the planted defect")
    if outside:
        reasons.append(f"{len(outside)} finding(s) outside the planted defect: " + "; ".join(str(item.get("quote", ""))[:60] for item in outside))
    return reasons
