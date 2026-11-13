"""Custom checks for T22: the first draft lists each step's times and says a marker file replaced the mode check."""

from __future__ import annotations

import re
from pathlib import Path

OUT = "out/comment-draft.txt"
STEP_TIMES = (("42", "18"), ("55", "31"), ("27", "12"))
MARKER = re.compile(r"표식|마커|marker", re.IGNORECASE)


def read(ctx):
    path = Path(ctx.repo) / OUT
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None


def sentences(text):
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def has_seconds(text, value):
    return re.search(rf"(?<![\d.]){value}\s*초", text) is not None


def step_times_listed(ctx):
    text = read(ctx)
    if text is None:
        return False, f"{OUT} is missing", {}
    missing = [value for pair in STEP_TIMES for value in pair if not has_seconds(text, value)]
    return not missing, "all six times are listed" if not missing else f"missing seconds: {missing}", {}


def marker_replaced_mode_check(ctx):
    text = read(ctx)
    if text is None:
        return False, f"{OUT} is missing", {}
    hit = [line for line in sentences(text) if "모드" in line and MARKER.search(line)]
    return bool(hit), "marker file replacing the mode check is stated" if hit else "no sentence names both the mode check and the marker file", {}
