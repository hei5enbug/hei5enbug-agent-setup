"""Shared by the custom checks of T65 and T66: find a stage or list item that a text names by its number alone.

A number counts as named when the stage's title stands right after it or right before it, with only separators or
the word step, stage, or phase between them.
"""

from __future__ import annotations

import re
from pathlib import Path

NUMBER = re.compile(r"(?<![\w.])\d+(?!\w)")
AFTER_GAP = r"[\s:：.)\-–—(\[`\"']*"
BEFORE_GAP = r"[\s,:(\[]*(?:steps?|stages?|phases?|items?|no\.?|#)?\s*$"
QUANTITY_UNIT = re.compile(r"\s+(?:levels?|items?)\b", re.IGNORECASE)


def read(ctx, relative):
    path = Path(ctx.repo) / relative
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None


def title_pattern(title):
    return rf"(?<![A-Za-z]){re.escape(title)}(?![A-Za-z])"


def has_title(text, title):
    return re.search(title_pattern(title), text, re.IGNORECASE) is not None


def title_positions(text, title):
    return [match.start() for match in re.finditer(title_pattern(title), text, re.IGNORECASE)]


def beside_title(text, match, title):
    after = re.match(AFTER_GAP + title_pattern(title), text[match.end():], re.IGNORECASE)
    before = re.search(title_pattern(title) + BEFORE_GAP, text[:match.start()], re.IGNORECASE)
    return after is not None or before is not None


def is_quantity(text, match):
    return QUANTITY_UNIT.match(text, match.end()) is not None


def numbers_without_title(text, titles, title_of=None):
    """Return the numbers in `titles` that are neither a quantity nor beside their own title.

    `title_of(text, match)` may choose the title for one number, such as a division's title when the word Phase
    stands before it; the default is the title of that number in `titles`.
    """
    chosen = title_of or (lambda _text, match: titles.get(int(match.group(0))))
    found = []
    for match in NUMBER.finditer(text):
        if int(match.group(0)) not in titles or is_quantity(text, match):
            continue
        title = chosen(text, match)
        if title is None or not beside_title(text, match, title):
            found.append(text[max(0, match.start() - 12):match.end() + 16].strip())
    return found
