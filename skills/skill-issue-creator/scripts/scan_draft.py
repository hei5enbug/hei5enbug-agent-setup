#!/usr/bin/env python3
"""Scan an issue draft read from stdin for values that must not be published.

Usage: scan_draft.py [--plugin-root <folder>] [--value <text>]... < draft

Prints one JSON object and never prints a matched private word. Exit 0 when clean, 1 on matches,
3 when the scanner cannot be loaded or a private word list cannot be used, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
SCANNER_DIR = PLUGIN_ROOT / ".githooks"
FINDING = re.compile(r"^draft:(\d+): (.+)$")
SESSION_VALUE = "session-value"
EXIT_CODES = {"clean": 0, "matches": 1, "unavailable": 3}


def parse(argv: list[str]) -> tuple[list[str], tuple[Path, ...]]:
    parser = argparse.ArgumentParser(prog="scan_draft.py", description="Scan a draft from stdin.")
    parser.add_argument("--value", action="append", default=[], help="a value found in the session to reject")
    parser.add_argument("--plugin-root", type=Path, help="the root of the plugin that owns the tracker")
    args = parser.parse_args(argv)
    if any(not value.strip() for value in args.value):
        parser.error("--value must not be empty")
    if args.plugin_root is not None and not args.plugin_root.is_dir():
        parser.error("--plugin-root must name an existing folder")
    return args.value, () if args.plugin_root is None else (args.plugin_root.resolve(),)


def result(status: str, findings: list[dict], lists: int, problems: list[str]) -> dict:
    return {"status": status, "findings": findings, "private_word_lists": lists, "problems": problems}


def session_value_pattern(value: str) -> re.Pattern[str]:
    """Match a session value as a whole word; a symbol at either end also matches next to more characters."""
    body = r"\s+".join(re.escape(part) for part in value.split())
    head = "(?<!\\w)" if value.strip()[0].isalnum() else ""
    tail = "(?!\\w)" if value.strip()[-1].isalnum() else ""
    return re.compile(rf"{head}{body}{tail}", re.IGNORECASE)


def scan(draft: str, values: list[str], owners: tuple[Path, ...] = ()) -> dict:
    sys.path.insert(0, str(SCANNER_DIR))
    try:
        import boundary_plugins
        import public_boundary
    except ImportError as error:
        return result("unavailable", [], 0, [f"the scanner could not be loaded ({type(error).__name__})"])
    environ = dict(os.environ)
    roots = boundary_plugins.installed_roots(environ, (PLUGIN_ROOT, *owners))
    sources = boundary_plugins.word_sources(roots, environ, PLUGIN_ROOT)
    found = []
    for text in public_boundary.scan_text("draft", draft, words=sources.words):
        match = FINDING.match(text)
        found.append({"line": int(match.group(1)), "kind": match.group(2)})
    for index, value in enumerate(values):
        pattern = session_value_pattern(value)
        for number, line in enumerate(draft.splitlines(), start=1):
            if pattern.search(line):
                found.append({"line": number, "kind": SESSION_VALUE, "value": index})
    found.sort(key=lambda item: (item["line"], item["kind"], item.get("value", -1)))
    problems = [*sources.problems, *sources.notes]
    status = "matches" if found else "unavailable" if problems else "clean"
    return result(status, found, sources.lists, problems)


def main(argv: list[str]) -> int:
    values, owners = parse(argv)
    draft = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    outcome = scan(draft, values, owners)
    print(json.dumps(outcome))
    return EXIT_CODES[outcome["status"]]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
