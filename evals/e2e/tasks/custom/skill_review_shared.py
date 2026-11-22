"""Shared helpers for the skill review cases T154 and T155: read the JSON a review role's result was saved as."""

import json
from pathlib import Path

WORKSPACE = "release-notes-workspace"
GRADING = f"{WORKSPACE}/iteration-1/changelog-basic/with_skill/grading.json"
COMPARISON = f"{WORKSPACE}/blind-1/comparison.json"


def read_json(ctx, relative):
    """The parsed file, or None when it is missing or not valid JSON."""
    try:
        return json.loads((Path(ctx.repo) / relative).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
