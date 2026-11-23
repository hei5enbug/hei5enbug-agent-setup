"""Seed the stub gh for T181: an open issue written by the current account already covers the weekly-report gap."""

from __future__ import annotations

import sys
from pathlib import Path

from gh_stub_common import CLOSED, OTHER_OPEN, install

COVERING = {
    "number": 12, "title": "weekly-report: leave out team sections that have no items",
    "url": "https://github.com/demo-org/demo-plugin/issues/12", "state": "OPEN", "labels": [{"name": "enhancement"}],
    "author": {"login": "demo-user"},
    "body": "## Summary\nThe weekly overview prints empty team sections as a heading followed by `(none)`.\n\n"
            "## Observations\n- Three of five sections were empty in one report, and the reader had to scroll past "
            "them.\n\n## Gap in current rules\nStep 3 of `skills/weekly-report/SKILL.md` says to print every section "
            "heading and write `(none)` under an empty one.\n\n## Proposal\n1. Under the condition that a team section "
            "has no items, leave that section out of the overview, heading included.\n\n## Acceptance criteria\n"
            "1. A page with an empty section produces an overview that has no heading for it.\n\n## Evidence\n"
            "- Related: #7 (closed, section order).\n",
}

install(Path(sys.argv[1]).resolve().parent, [CLOSED, COVERING, OTHER_OPEN])
