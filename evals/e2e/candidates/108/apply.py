#!/usr/bin/env python3
"""Remove the final-report length threshold of issue 108 from a checkout, on both hosts, or show what it would change."""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

SENTENCE = """question. A final report under 400 characters, after trimming, needs no review and no `text_review.py` run at all; one
of 400 characters or more needs this review. Never count a check you record about your own draft as this review.
"""
WITHOUT_SENTENCE = """question. Never count a check you record about your own draft as this review.
"""
GATE = "MINIMUM_REPORT_CHARACTERS = 400\n"
NO_GATE = "MINIMUM_REPORT_CHARACTERS = 0\n"
TARGETS = (
    ("instructions/shared-text.md", ((SENTENCE, WITHOUT_SENTENCE),)),
    ("scripts/final_report_hook.py", ((GATE, NO_GATE),)),
)


class AnchorError(Exception):
    pass


def patched(source: str, edits) -> str:
    """The source with the candidate applied; a source whose anchors are already replaced comes back unchanged."""
    for anchor, replacement in edits:
        if replacement in source and anchor not in source:
            continue
        if source.count(anchor) != 1:
            raise AnchorError(f"anchor found {source.count(anchor)} times, expected once: {anchor!r}")
        source = source.replace(anchor, replacement)
    return source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", help="root of a checkout that holds the threshold of issue 108 in its text rules and its Stop hook")
    parser.add_argument("--dry-run", action="store_true", help="print the diffs and write nothing")
    args = parser.parse_args(argv)
    changes = []
    try:
        for relative, edits in TARGETS:
            target = Path(args.checkout) / relative
            before = target.read_text(encoding="utf-8")
            changes.append((relative, target, before, patched(before, edits)))
    except (OSError, AnchorError) as error:
        print(f"apply failed: {error}", file=sys.stderr)
        return 2
    changed = [item for item in changes if item[2] != item[3]]
    if not changed:
        print("already applied")
        return 0
    for relative, target, before, after in changed:
        if args.dry_run:
            sys.stdout.writelines(difflib.unified_diff(before.splitlines(True), after.splitlines(True), f"a/{relative}", f"b/{relative}"))
        else:
            target.write_text(after, encoding="utf-8")
            print(f"applied to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
