"""Custom checks for T02."""

from __future__ import annotations

import re
from pathlib import Path

MIN_FILES_CHANGED = 4
ADDED_TEST_DEF = re.compile(r"^\+\s*(?:async\s+)?def\s+test_")


def is_test(path: str) -> bool:
    return path.startswith("tests/") and path.endswith(".py")


def added_shipping_tests(diff: str) -> bool:
    """True when the diff adds a `def test_` whose added lines (the signature and the body written with it) mention shipping."""
    lines = diff.splitlines()
    for index, line in enumerate(lines):
        if ADDED_TEST_DEF.match(line):
            block = []
            for follower in lines[index:]:
                if not follower.startswith("+") or follower.startswith("+++"):
                    break
                block.append(follower)
            if "shipping" in "\n".join(block).lower():
                return True
    return False


def new_tests(ctx):
    added = sorted(path for path, status in ctx.changes.items() if status == "A" and is_test(path))
    useful = [
        path for path in added
        if "shipping" in (Path(ctx.repo) / path).read_text(encoding="utf-8", errors="replace").lower()
    ]
    modified = sorted(path for path, status in ctx.changes.items() if status == "M" and is_test(path))
    extended = [path for path in modified if added_shipping_tests(ctx.git("diff", ctx.base, "--", path))]
    return bool(useful or extended), f"test files mentioning shipping: {useful + extended}", {
        "added": added, "useful": useful, "modified": modified, "extended": extended}


def files_changed(ctx):
    changed = sorted(ctx.changes)
    return len(changed) >= MIN_FILES_CHANGED, f"{len(changed)} files changed", {"changed": changed}
