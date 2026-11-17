"""Shared by the custom checks of T98 to T100: what the reviewer stub of loop-notes saw and what a run posted after its review loop."""

from __future__ import annotations

import json
import re
from pathlib import Path

SEEDED = {
    "m": ["This change follows the report that zero-total customers made the nightly export slow.",
          "The export module was refactored as part of this work.", "The change is small and easy to review."],
    "n": ["This work started from the request to stop over-refunds."],
    "o": ["This change follows the report that statement totals were off by a cent.",
          "The statement module was cleaned up along the way.", "The change is small and easy to review."],
}
KEPT = {
    "m": ["Invoices with a zero total are now skipped by the nightly export", "- Added a test that a zero-total customer produces no file.",
          "- Ran the export test module: 14 passed."],
    "n": ["A refund over the original charge is now rejected", "- Added a test that a refund over the charge is rejected.",
          "- Ran the refund test module: 6 passed."],
    "o": ["The statement export now rounds each line to cents", "- Added a test that a statement of three lines with fractions adds up to its printed lines.",
          "- Ran the statement test module: 9 passed."],
}
LATE = "A refund equal to the charge is still accepted."
REVIEW_RUN = re.compile(r"text_review\.py[\"']?(?:\s+-\S+)*\s+review\b")
SUBSTITUTE = re.compile(r"claude\s+-p\b|codex\s+exec\b")


def calls(ctx) -> list[dict]:
    path = Path(ctx.origin).parent / "stub-calls.log"
    if not path.is_file():
        return []
    found = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            found.append(json.loads(line))
        except ValueError:
            continue
    return sorted(found, key=lambda item: item.get("call", 0))


def runs(ctx) -> list[list[dict]]:
    """The calls grouped by the review run that made them: calls with one assignment belong to one run, in order of first call."""
    grouped: dict[str, list[dict]] = {}
    for item in calls(ctx):
        grouped.setdefault(str(item.get("sha")), []).append(item)
    return list(grouped.values())


def posted(ctx, name: str) -> str | None:
    path = Path(ctx.repo) / "posted" / name
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None


def letter(name: str) -> str:
    return name.removeprefix("pr-draft-demo-").removesuffix(".md")


def reviewed_text_posted(ctx, name: str) -> tuple[bool, str]:
    text = posted(ctx, name)
    if text is None:
        return False, f"{name} was not posted"
    key = letter(name)
    left = [sentence for sentence in SEEDED[key] if sentence in text]
    lost = [sentence for sentence in KEPT[key] if sentence not in text]
    problems = [f"seeded sentence still posted: {sentence}" for sentence in left] + [f"fact lost: {sentence}" for sentence in lost]
    return not problems, "; ".join(problems) if problems else "the posted text drops every flagged sentence and keeps its facts"


def last_review_clean(ctx) -> tuple[bool, str]:
    groups = runs(ctx)
    if not groups:
        return False, "the reviewer runner was never called"
    quotes = [item.get("quote") for item in groups[-1] if item.get("quote")]
    return not quotes, f"the last review run still raised {quotes}" if quotes else f"the last of {len(groups)} review runs raised nothing"


def question_asked(view: dict) -> bool:
    asked = any(call.get("name") == "AskUserQuestion" for call in view.get("tool_calls", []))
    lines = [line.strip() for line in str(view.get("final_answer", "")).splitlines() if line.strip()]
    return asked or bool(lines) and lines[-1].endswith(("?", "？"))


def main_review_runs(view: dict) -> list[str]:
    return [str(call.get("input", {}).get("command", ""))[:160] for call in view.get("tool_calls", [])
            if call.get("name") == "Bash" and call.get("source") == "main" and REVIEW_RUN.search(str(call.get("input", {}).get("command", "")))]


def language_workers(view: dict) -> list[dict]:
    return [item for item in view.get("delegations", []) if item.get("kind") == "role_runner" and item.get("type") == "language"]
