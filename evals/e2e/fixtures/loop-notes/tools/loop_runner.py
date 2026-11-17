#!/usr/bin/env python3
"""A reviewer runner that raises seeded removable findings by a fixed script and logs every call.

LOOP_STUB_MODE chooses the script: `sequence` raises the first seeded sentence still in the draft; `split` lets an
odd call look at the first and third seeded sentences and an even call at the second, as two reviewers with different
attention would; `stale` raises the first seeded sentence, then once a sentence of the draft that no run changed.
LOOP_STUB_LOG names the call log, one JSON line per call, and numbers the calls without a race.
"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

SEEDED = {
    "m": ["This change follows the report that zero-total customers made the nightly export slow.",
          "The export module was refactored as part of this work.", "The change is small and easy to review."],
    "n": ["This work started from the request to stop over-refunds."],
    "o": ["This change follows the report that statement totals were off by a cent.",
          "The statement module was cleaned up along the way.", "The change is small and easy to review."],
}
TOPICS = {"m": "Invoices with a zero total", "n": "A refund over the original charge", "o": "The statement export now rounds"}
STALE = "A refund equal to the charge is still accepted."
SPLIT_ORDER = {1: (0, 2), 0: (1,)}
DRAFT = re.compile(r"## Draft\n\n(`{3,})\n(.*?)\n\1", re.DOTALL)


def claim_call(log: str) -> int:
    number = 1
    while True:
        try:
            os.close(os.open(f"{log}.{number}", os.O_CREAT | os.O_EXCL))
            return number
        except FileExistsError:
            number += 1


def first_present(draft: str, sentences: list[str], positions: tuple[int, ...]) -> str | None:
    return next((sentences[index] for index in positions if sentences[index] in draft), None)


def choose(mode: str, draft: str, number: int, log: str) -> str | None:
    sentences = next((SEEDED[key] for key, topic in TOPICS.items() if topic in draft), [])
    if not sentences:
        return None
    if mode == "split":
        return first_present(draft, sentences, SPLIT_ORDER[number % 2])
    found = first_present(draft, sentences, tuple(range(len(sentences))))
    if found or mode != "stale":
        return found
    marker = Path(f"{log}.stale")
    if STALE in draft and not marker.exists():
        marker.write_text("1", encoding="utf-8")
        return STALE
    return None


def main() -> int:
    argv = sys.argv[1:]
    value = lambda flag: argv[argv.index(flag) + 1]  # noqa: E731
    assignment = Path(value("--assignment")).read_text(encoding="utf-8")
    match = DRAFT.search(assignment)
    draft = match.group(2) if match else ""
    log = os.environ.get("LOOP_STUB_LOG", "stub-calls.log")
    number = claim_call(log)
    quote = choose(os.environ.get("LOOP_STUB_MODE", "sequence"), draft, number, log)
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"call": number, "sha": hashlib.sha256(assignment.encode("utf-8")).hexdigest()[:12],
                                 "quote": quote}) + "\n")
    findings = [{"type": "removable", "quote": quote, "reason": "the sentence adds no fact the reader needs"}] if quote else []
    Path(value("--result")).write_text("```json\n" + json.dumps({"findings": findings}) + "\n```\n", encoding="utf-8")
    print(json.dumps({"verified": True, "exit": 0}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
