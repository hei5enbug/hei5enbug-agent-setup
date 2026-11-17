#!/usr/bin/env python3
"""Add the stage-number-alone advisory of issue 88 to scripts/text_review.py of a checkout, or show what it would change."""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

SNIPPET = Path(__file__).with_name("snippet.py")
MARKER = "def stage_number_alone("
EXPLANATION = '''    "stage-number-alone": (
        "Each line below may name a stage, phase, or division of a procedure or plan by a number with no title "
        "beside it. Report it as ambiguous when the number stands alone, such as \\"step 0\\" or \\"steps 3 to 8\\". "
        "Never report a number that states a quantity or a value, such as a depth limit, a count, or a version, or "
        "one that has its stage's title beside it.\\n"
    ),
'''
EDITS = (
    ("def links_of(line: str)", "{snippet}def links_of(line: str)"),
    ("    advisories = unchanged_only(lines)\n", "    advisories = unchanged_only(lines) + stage_number_alone(lines)\n"),
    ('such as the commands run or the tests added.\\n"\n    ),\n}\n',
     'such as the commands run or the tests added.\\n"\n    ),\n{explanation}}}\n'),
)


class AnchorError(Exception):
    pass


def patched(source: str) -> str:
    """The source with the candidate applied; a source that already holds it comes back unchanged."""
    if MARKER in source:
        return source
    values = {"snippet": SNIPPET.read_text(encoding="utf-8"), "explanation": EXPLANATION}
    for anchor, replacement in EDITS:
        if source.count(anchor) != 1:
            raise AnchorError(f"anchor found {source.count(anchor)} times, expected once: {anchor!r}")
        source = source.replace(anchor, replacement.format(**values))
    return source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", help="root of a checkout that holds scripts/text_review.py")
    parser.add_argument("--dry-run", action="store_true", help="print the diff and write nothing")
    args = parser.parse_args(argv)
    target = Path(args.checkout) / "scripts" / "text_review.py"
    try:
        before = target.read_text(encoding="utf-8")
        after = patched(before)
    except (OSError, AnchorError) as error:
        print(f"apply failed: {error}", file=sys.stderr)
        return 2
    if after == before:
        print("already applied" if MARKER in before else "nothing to change")
        return 0
    if args.dry_run:
        sys.stdout.writelines(difflib.unified_diff(before.splitlines(True), after.splitlines(True), "a/scripts/text_review.py",
                                                   "b/scripts/text_review.py"))
        return 0
    target.write_text(after, encoding="utf-8")
    print(f"applied to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
