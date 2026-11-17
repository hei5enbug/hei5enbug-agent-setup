"""Shared by the custom checks of T29 to T31: find stages, phases, and divisions that a text names by number alone."""

from __future__ import annotations

import re
from pathlib import Path

WINDOW = 60
REFERENCE_WORDS = r"(?:steps?|stages?|phases?|divisions?|parts?|sections?)"
DIVISION_WORDS = r"(?:phases?|divisions?|stages?|parts?|sections?)"
LEAD = r"(?<![A-Za-z])"
NUMBERS = r"\d+(?:\s*(?:to|through|and|–|-|,)\s*\d+)*"
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def text_of(ctx, relative: str) -> str | None:
    path = Path(ctx.repo) / relative
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None


def title_pattern(title: str) -> str:
    return r"(?<![A-Za-z])" + r"\s+".join(re.escape(word) for word in title.split()) + r"(?![A-Za-z])"


def has_title(text: str, title: str) -> bool:
    return re.search(title_pattern(title), text, re.IGNORECASE) is not None


def missing_in_order(text: str, titles: list[str]) -> list[str]:
    """The titles that do not appear after the title before them, so a missing or moved title is listed."""
    position, missing = 0, []
    for title in titles:
        found = re.compile(title_pattern(title), re.IGNORECASE).search(text, position)
        if found is None:
            missing.append(title)
        else:
            position = found.end()
    return missing


def references(text: str, words: str = REFERENCE_WORDS) -> list[tuple[str, list[int], str]]:
    """Each keyword-led number reference, such as `step 0` or `steps 3 to 8`, with its numbers and nearby text."""
    found = []
    for match in re.finditer(rf"{LEAD}{words}\s+({NUMBERS})", text, re.IGNORECASE):
        nearby = text[max(0, match.start() - WINDOW):match.end() + WINDOW]
        found.append((match.group(0), [int(number) for number in re.findall(r"\d+", match.group(1))], nearby))
    return found


def number_alone(text: str, titles: dict[int, str]) -> list[str]:
    """References whose numbers have no title of the same stage beside them."""
    return [reference for reference, numbers, nearby in references(text)
            if any(number not in titles or not has_title(nearby, titles[number]) for number in numbers)]


def title_numbers(text: str, titles: dict[int, str]) -> list[tuple[int, int]]:
    """Pairs of the number written beside a title and the title's own number, in either order."""
    alternatives = "|".join(title_pattern(title) for title in sorted(titles.values(), key=len, reverse=True))
    by_title = {" ".join(title.lower().split()): number for number, title in titles.items()}
    pairs = []
    for match in re.finditer(rf"(?<![\w.])(\d+)\s*[.:)\-–—]*\s*\(?\s*(?:item\s+)?({alternatives})", text, re.IGNORECASE):
        pairs.append((int(match.group(1)), by_title[" ".join(match.group(2).lower().split())]))
    for match in re.finditer(rf"({alternatives})\s*[(\-–—:,]*\s*(?:{REFERENCE_WORDS}|item)\s+(\d+)", text, re.IGNORECASE):
        pairs.append((int(match.group(2)), by_title[" ".join(match.group(1).lower().split())]))
    return pairs


def wrong_numbers(text: str, titles: dict[int, str]) -> list[str]:
    return [f"{written} beside the title of stage {actual}" for written, actual in title_numbers(text, titles)
            if written != actual]


def numbers_near(text: str, noun: str) -> tuple[set[int], set[int]]:
    """The numbers written right before the noun, and the numbers within a short distance of it."""
    values = lambda raw: NUMBER_WORDS[raw.lower()] if raw.lower() in NUMBER_WORDS else int(raw)
    token = rf"\d+|{'|'.join(NUMBER_WORDS)}"
    before = {values(m.group(1)) for m in re.finditer(rf"(?<![\w.])({token})(?![\w.])\s+(?:{noun})", text, re.IGNORECASE)}
    near = set()
    for match in re.finditer(noun, text, re.IGNORECASE):
        nearby = text[max(0, match.start() - 30):match.end() + 30]
        near |= {values(m.group(1)) for m in re.finditer(rf"(?<![\w.])({token})(?![\w.])", nearby, re.IGNORECASE)}
    return before, near
