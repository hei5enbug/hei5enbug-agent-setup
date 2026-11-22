#!/usr/bin/env python3
"""Check the exact Markdown format rules of a design document.

Usage:
  check_format.py <file> [--template]

Violations, each a real breach of a rule:
  long_line          a prose line over 120 characters, outside table rows, fenced code, indented code, and lines
                     that hold a URL or an inline code span
  heading_level      an ATX heading deeper than level 3
  line_count         more than 500 lines; not checked with --template, for a supplied template or generated contract
  trailing_space     a space or tab at the end of a line outside fenced code
  blank_line         no blank line before or after a heading, a table, or a fenced code block, or none before a
                     list; a line that follows a list item directly and starts no heading, table, or code block
                     continues that item, so no blank line after a list is reported except before such a block
Candidates, left to the model to judge and never violations:
  long_korean_heading   a heading that holds Hangul and has more than 30 characters

Prints one JSON object. Exit 0 when no violation is found, even with candidates, 1 when any violation is found, 2 on
a usage error or an unreadable file. Given an existing folder instead of a file, as skill packaging runs every
`scripts/check_*.py` detector, it checks nothing and exits 0. Front matter and indented code blocks that no list
holds are skipped. Setext headings and HTML blocks are not examined.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

MAX_PROSE_CHARACTERS = 120
MAX_HEADING_LEVEL = 3
MAX_LINES = 500
MAX_KOREAN_HEADING_CHARACTERS = 30
FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
HEADING = re.compile(r"^ {0,3}(#{1,6})(?:\s+(.*?))?\s*$")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d{1,9}[.)])(?:\s|$)")
URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S")
INLINE_CODE = re.compile(r"(`+)(?!`).+?(?<!`)\1(?!`)")
HANGUL = re.compile(r"[가-힣]")
INDENTED_CODE = re.compile(r"^(?: {4,}|\t)")


def finding(rule: str, line: int, detail: str) -> dict[str, Any]:
    return {"rule": rule, "line": line, "detail": detail}


def is_blank(line: str) -> bool:
    return not line.strip()


def front_matter_end(lines: list[str]) -> int:
    """The index after a leading `---` front matter block, or 0 when there is none."""
    if not lines or lines[0].strip() != "---":
        return 0
    for index in range(1, len(lines)):
        if lines[index].strip() in ("---", "..."):
            return index + 1
    return 0


def classify(lines: list[str]) -> list[str]:
    """One kind per line: front, blank, fence_open, code, fence_close, heading, table, item_start, item, text,
    indented_code. An item_start opens a list, and an item belongs to a list that is already open."""
    kinds = ["text"] * len(lines)
    front = front_matter_end(lines)
    fence: tuple[str, int] | None = None
    in_list = False
    for index, line in enumerate(lines):
        if index < front:
            kinds[index] = "front"
        elif fence is not None:
            kinds[index], fence = fence_line(line, fence)
        elif (opening := fence_opening(line)) is not None:
            kinds[index], fence = "fence_open", opening
        elif is_blank(line):
            kinds[index] = "blank"
        elif LIST_ITEM.match(line) and not (INDENTED_CODE.match(line) and not in_list):
            kinds[index], in_list = ("item" if in_list else "item_start"), True
        elif HEADING.match(line):
            kinds[index], in_list = "heading", False
        elif line.strip().startswith("|"):
            kinds[index] = "table"
        elif INDENTED_CODE.match(line) and not in_list and kinds[index - 1] in ("blank", "indented_code"):
            kinds[index] = "indented_code"
        elif in_list and not line.startswith((" ", "\t")) and index > 0 and kinds[index - 1] == "blank":
            in_list = False
    return kinds


def fence_opening(line: str) -> tuple[str, int] | None:
    match = FENCE.match(line)
    if not match or (match.group(1)[0] == "`" and "`" in match.group(2)):
        return None
    return match.group(1)[0], len(match.group(1))


def fence_line(line: str, fence: tuple[str, int]) -> tuple[str, tuple[str, int] | None]:
    match = FENCE.match(line)
    closes = bool(match) and match.group(1)[0] == fence[0] and len(match.group(1)) >= fence[1] \
        and not match.group(2).strip()
    return ("fence_close", None) if closes else ("code", fence)


def long_lines(lines: list[str], kinds: list[str]) -> list[dict[str, Any]]:
    found = []
    for number, (line, kind) in enumerate(zip(lines, kinds), start=1):
        if kind in ("text", "item", "item_start") and len(line) > MAX_PROSE_CHARACTERS and not URL.search(line) \
                and not INLINE_CODE.search(line):
            found.append(finding("long_line", number, f"{len(line)} characters, more than {MAX_PROSE_CHARACTERS}"))
    return found


def headings(lines: list[str], kinds: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    violations, candidates = [], []
    for number, (line, kind) in enumerate(zip(lines, kinds), start=1):
        match = HEADING.match(line) if kind == "heading" else None
        if not match:
            continue
        level, text = len(match.group(1)), re.sub(r"\s+#+$", "", match.group(2) or "").strip()
        if level > MAX_HEADING_LEVEL:
            violations.append(finding("heading_level", number, f"heading level {level}, more than {MAX_HEADING_LEVEL}"))
        if HANGUL.search(text) and len(text) > MAX_KOREAN_HEADING_CHARACTERS:
            candidates.append(finding("long_korean_heading", number,
                                      f"{len(text)} characters, more than {MAX_KOREAN_HEADING_CHARACTERS}"))
    return violations, candidates


def trailing_spaces(lines: list[str], kinds: list[str]) -> list[dict[str, Any]]:
    return [finding("trailing_space", number, "trailing whitespace")
            for number, (line, kind) in enumerate(zip(lines, kinds), start=1)
            if kind not in ("code", "front") and line != line.rstrip(" \t")]


def blank_lines(kinds: list[str]) -> list[dict[str, Any]]:
    """A block start needs a blank line before it and a block end needs one after it, as the rules say."""
    found = []
    for index, kind in enumerate(kinds):
        previous = kinds[index - 1] if index else "blank"
        following = kinds[index + 1] if index + 1 < len(kinds) else "blank"
        number = index + 1
        needs_before = kind in ("heading", "fence_open", "item_start") or (kind == "table" and previous != "table")
        needs_after = kind in ("heading", "fence_close") or (kind == "table" and following != "table")
        name = {"fence_open": "code block", "fence_close": "code block", "item_start": "list"}.get(kind, kind)
        if needs_before and previous not in ("blank", "front"):
            found.append(finding("blank_line", number, f"no blank line before the {name}"))
        if needs_after and following != "blank":
            found.append(finding("blank_line", number, f"no blank line after the {name}"))
    return found


def check(text: str, template: bool) -> dict[str, Any]:
    lines = text.splitlines()
    kinds = classify(lines)
    heading_violations, candidates = headings(lines, kinds)
    violations = [*long_lines(lines, kinds), *heading_violations, *trailing_spaces(lines, kinds),
                  *blank_lines(kinds)]
    if not template and len(lines) > MAX_LINES:
        violations.append(finding("line_count", len(lines), f"{len(lines)} lines, more than {MAX_LINES}"))
    violations.sort(key=lambda item: (item["line"], item["rule"], item["detail"]))
    return {"status": "fail" if violations else "pass", "lines": len(lines), "violations": violations,
            "candidates": candidates}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="check_format.py", description="Check a design document's exact format rules.")
    parser.add_argument("path")
    parser.add_argument("--template", action="store_true", help="the document is a supplied template or generated contract")
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return 2 if error.code else 0
    path = Path(args.path)
    if path.is_dir():
        print(json.dumps({"status": "pass", "lines": 0, "violations": [], "candidates": []}))
        return 0
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        print(f"check_format.py: cannot read {path}: {type(error).__name__}", file=sys.stderr)
        return 2
    outcome = check(text, args.template)
    print(json.dumps(outcome, ensure_ascii=False))
    return 1 if outcome["violations"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
