"""Split a Markdown instruction file into headings, bullets, and paragraphs, and cut named parts out of it.

A bullet is a line that starts with `- ` at column 0 plus its continuation lines. A paragraph is a run of other
non-blank lines that is not a heading. A section is a heading plus everything up to the next heading of the same or
a higher level. Matching a part by its first words ignores line breaks and repeated spaces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

BULLET = re.compile(r"^(?:[-*]|\d+\.) ")
HEADING = re.compile(r"^(#{1,6}) +(\S.*?) *$")
KIND_HEADING, KIND_BULLET, KIND_PARAGRAPH = "heading", "bullet", "paragraph"


class PartError(ValueError):
    pass


@dataclass(frozen=True)
class Part:
    kind: str
    first: int
    stop: int
    text: str
    level: int = 0
    lines_text: str = ""

    @property
    def size(self) -> int:
        """UTF-8 bytes of the part's lines with their line breaks."""
        return len(self.lines_text.encode("utf-8")) + 1


def normalize(text: str) -> str:
    return " ".join(text.split())


def parse_parts(text: str) -> list[Part]:
    """Every heading, bullet, and paragraph of `text` in order; `first` and `stop` are line indexes."""
    lines = text.split("\n")
    parts: list[Part] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        heading = HEADING.match(line)
        if heading:
            parts.append(Part(KIND_HEADING, index, index + 1, normalize(heading.group(2)), len(heading.group(1)), line))
            index += 1
            continue
        kind = KIND_BULLET if BULLET.match(line) else KIND_PARAGRAPH
        stop = index + 1
        while stop < len(lines) and lines[stop].strip() and not HEADING.match(lines[stop]) and not BULLET.match(lines[stop]):
            stop += 1
        block = lines[index:stop]
        body = normalize(" ".join(block))
        if kind == KIND_BULLET:
            body = BULLET.sub("", body, count=1)
        parts.append(Part(kind, index, stop, body, 0, "\n".join(block)))
        index = stop
    return parts


def units(parts: Sequence[Part]) -> list[Part]:
    return [part for part in parts if part.kind != KIND_HEADING]


def section_stop(parts: Sequence[Part], heading: Part, line_count: int) -> int:
    """The line index where the section of `heading` ends."""
    for part in parts:
        if part.kind == KIND_HEADING and part.first > heading.first and part.level <= heading.level:
            return part.first
    return line_count


def section_units(parts: Sequence[Part], heading: Part, line_count: int) -> list[Part]:
    stop = section_stop(parts, heading, line_count)
    return [part for part in units(parts) if heading.first < part.first < stop]


def starts_with(part: Part, start: str) -> bool:
    return part.kind != KIND_HEADING and part.text.startswith(normalize(start))


def span_of(text: str, start: str | None = None, heading: str | None = None, label: str = "text") -> tuple[int, int]:
    """The line span `[first, stop)` of the one part a selector names: a bullet or paragraph by its first words, or a
    whole section by its heading line. A selector that matches nothing or more than one part raises PartError."""
    if (start is None) == (heading is None):
        raise PartError(f"{label}: a selector needs exactly one of 'start' and 'heading'")
    parts = parse_parts(text)
    line_count = len(text.split("\n"))
    if start is not None:
        found = [part for part in parts if starts_with(part, start)]
        words = start
    else:
        wanted = normalize(heading)
        found = [part for part in parts if part.kind == KIND_HEADING
                 and wanted in (part.text, f"{'#' * part.level} {part.text}")]
        words = heading
    if len(found) != 1:
        raise PartError(f"{label}: {'matches nothing' if not found else f'matches {len(found)} parts'}: {words!r}")
    part = found[0]
    if heading is not None:
        return part.first, section_stop(parts, part, line_count)
    return part.first, part.stop


def cut_spans(text: str, spans: Sequence[tuple[int, int]]) -> str:
    """`text` without the given line spans, keeping at most one blank line between what is left."""
    ordered = sorted(spans)
    for (_, stop), (first, _) in zip(ordered, ordered[1:]):
        if first < stop:
            raise PartError("two selectors name overlapping parts")
    drop = {line for first, stop in ordered for line in range(first, stop)}
    kept: list[str] = []
    for number, line in enumerate(text.split("\n")):
        if number in drop:
            continue
        if not line.strip() and (not kept or not kept[-1].strip()):
            continue
        kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept) + "\n"
