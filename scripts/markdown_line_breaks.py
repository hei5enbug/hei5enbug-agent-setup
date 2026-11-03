#!/usr/bin/env python3
"""Report Markdown line-break findings that change how a line-preserving converter publishes a file.

Usage:
    markdown_line_breaks.py [--max-chars N] FILE

Findings, each with its line number, kind, and line text:

    soft-break      a line the same paragraph, list item, or block quotation continues on the next line,
                    without a marked line break
    trailing-break  the last line of a paragraph, list item, or block quotation ends in a line break
    long-line       a prose line that holds more than one sentence and is longer than N characters (default 120;
                    0 turns the check off), counted without a trailing <br>, link destinations, and bare http or
                    https addresses; a single sentence is never reported, since it cannot be split

A marked line break is a trailing <br>, <br/>, or <br />, a backslash, or two spaces. Fenced code and diagram
blocks, front matter, tables with or without outer pipes, headings, HTML block lines, and blank lines are ignored.

A JSON report goes to standard output. Exit codes: 0 no finding, 1 findings, 2 usage or read error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_MAX_CHARS = 120
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
HEADING = re.compile(r"^\s{0,3}#{1,6}(\s|$)")
SETEXT_UNDERLINE = re.compile(r"^\s{0,3}(=+|-+)\s*$")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
QUOTE = re.compile(r"^\s*>")
TRAILING_BR = re.compile(r"<br\s*/?>\s*$", re.IGNORECASE)
LINK_DESTINATION = re.compile(r"\]\([^)]*\)")
BARE_URL = re.compile(r"https?://\S+")
SENTENCE_BREAK = re.compile(r"[.!?][\"')\]]*\s+(?![a-z])\S")
DELIMITER_ROW = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$|^\s*\|\s*:?-+:?\s*\|\s*$")


def is_front_matter_end(line: str) -> bool:
    return line.strip() in {"---", "..."}


def has_marked_break(line: str) -> bool:
    return bool(TRAILING_BR.search(line)) or line.endswith("\\") or line.endswith("  ")


def prose_text(line: str) -> str:
    text = TRAILING_BR.sub("", line.strip())
    return BARE_URL.sub("", LINK_DESTINATION.sub("]", text))


def is_long(line: str, max_chars: int) -> bool:
    text = prose_text(line)
    return len(text) > max_chars and bool(SENTENCE_BREAK.search(text))


def finding(number: int, kind: str, line: str) -> dict:
    return {"line": number, "kind": kind, "text": line.rstrip()}


def block_findings(block: list) -> list:
    results = [finding(n, "soft-break", text) for n, text in block[:-1] if not has_marked_break(text)]
    number, last = block[-1]
    if TRAILING_BR.search(last):
        results.append(finding(number, "trailing-break", last))
    return results


def length_findings(block: list, max_chars: int) -> list:
    if max_chars <= 0:
        return []
    return [finding(n, "long-line", text) for n, text in block if is_long(text, max_chars)]


def starts_ignored_block(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith(("|", "<")) or bool(HEADING.match(line))


def body_start(lines: list) -> int:
    if not lines or lines[0].strip() != "---":
        return 0
    ends = [i for i, line in enumerate(lines[1:], 1) if is_front_matter_end(line)]
    return ends[0] + 1 if ends else 0


def table_lines(lines: list, start: int) -> frozenset:
    """Return the indexes of every table: a header row with a pipe, its delimiter row, and the rows up to a blank line."""
    indexes: set = set()
    for index in range(start + 1, len(lines)):
        if index in indexes or "|" not in lines[index - 1] or not DELIMITER_ROW.match(lines[index]):
            continue
        end = index + 1
        while end < len(lines) and lines[end].strip() and not FENCE.match(lines[end]):
            end += 1
        indexes.update(range(index - 1, end))
    return frozenset(indexes)


def closes_fence(line: str, fence: str) -> bool:
    marker = FENCE.match(line)
    return bool(marker) and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence)


def continues_block(block: list, line: str) -> bool:
    if LIST_ITEM.match(line):
        return False
    return not block or bool(QUOTE.match(line)) == bool(QUOTE.match(block[-1][1]))


def prose_blocks(lines: list, start: int):
    """Yield each paragraph, list item, or block quotation as a list of (line number, text)."""
    block, fence, tables = [], None, table_lines(lines, start)
    for index in range(start, len(lines)):
        line = lines[index]
        marker = FENCE.match(line)
        if fence is not None:
            fence = None if closes_fence(line, fence) else fence
            continue
        if SETEXT_UNDERLINE.match(line):
            block = []
            continue
        ends_block = marker or not line.strip() or starts_ignored_block(line) or index in tables
        if (ends_block or not continues_block(block, line)) and block:
            yield block
            block = []
        if marker:
            fence = marker.group(1)
        elif not ends_block:
            block.append((index + 1, line))
    if block:
        yield block


def check(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list:
    """Return the findings of one Markdown text, ordered by line number."""
    lines = text.splitlines()
    results = []
    for block in prose_blocks(lines, body_start(lines)):
        results.extend(block_findings(block))
        results.extend(length_findings(block, max_chars))
    return sorted(results, key=lambda item: item["line"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Report Markdown line-break findings.")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS, help="longest prose line; 0 turns the check off")
    parser.add_argument("file", help="Markdown file to check")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        text = Path(args.file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        print(f"error: cannot read {args.file}: {error}", file=sys.stderr)
        return 2
    findings = check(text, args.max_chars)
    print(json.dumps({"findings": findings}, ensure_ascii=False, indent=2))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
