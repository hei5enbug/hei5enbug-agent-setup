#!/usr/bin/env python3
"""Move the usage-limit handling of issue 111 from instructions/shared-text.md into the result of scripts/text_review.py of a checkout, or show what it would change."""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

MARKER = "USAGE_LIMIT_NEXT"
NEXT = (
    "Treat the review as skipped: post without asking and without another reviewer, never a Claude one when you are "
    "Claude, and say, in one line of the report and nowhere else in it, that the independent text review did not run "
    "because the reviewer's usage limit was reached. For a final report, put that line in the draft and run "
    "`text_review.py check --kind final-report` on it. Once it happened in the session, you may skip the reviewer for "
    "the session's other texts and treat each the same way."
)
RULE_PARAGRAPH = """- Exit 4, with `reason` `usage_limit`, means the reviewer's usage limit is reached. Treat the review as skipped: post
  without asking and without another reviewer, never a Claude one when you are Claude, and say, in one line of the
  report and nowhere else in it, that the independent text review did not run because the reviewer's usage limit was
  reached. For a final report, put that line in the draft and run `text_review.py check --kind final-report` on it.
  Once it happened in the session, you may skip the reviewer for the session's other texts and treat each the same
  way.
"""
RULE_LINE = "- Exit 4 means the reviewer's usage limit is reached. Follow the result's `next`.\n"
SCRIPT_EDITS = (
    ('REASON_USAGE_LIMIT = "usage_limit"\n', 'REASON_USAGE_LIMIT = "usage_limit"\nUSAGE_LIMIT_NEXT = {next!r}\n'),
    ('{"reason": REASON_USAGE_LIMIT} if limited else {}', '{{"reason": REASON_USAGE_LIMIT, "next": USAGE_LIMIT_NEXT}} if limited else {{}}'),
)
TEXT_EDITS = ((RULE_PARAGRAPH, RULE_LINE),)
TARGETS = (("scripts/text_review.py", SCRIPT_EDITS), ("instructions/shared-text.md", TEXT_EDITS))


class AnchorError(Exception):
    pass


def patched(source: str, edits) -> str:
    """The source with the candidate applied; a source whose anchors are already replaced comes back unchanged."""
    for anchor, replacement in edits:
        replacement = replacement.format(next=NEXT) if "{next!r}" in replacement else replacement.replace("{{", "{").replace("}}", "}")
        if replacement in source:
            continue
        if source.count(anchor) != 1:
            raise AnchorError(f"anchor found {source.count(anchor)} times, expected once: {anchor!r}")
        source = source.replace(anchor, replacement)
    return source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", help="root of a checkout that holds scripts/text_review.py and instructions/shared-text.md")
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
