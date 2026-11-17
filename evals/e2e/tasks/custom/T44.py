"""Custom checks for T44: the one assertion that expects rounding down must now expect rounding half up, and no other changes."""

from __future__ import annotations

import re
import types
from pathlib import Path

TEST_FILE = "tests/test_pricing.py"
OLD_LINE = "assert discount_cents(1999, 10) == 199"
CALL = re.compile(r"discount_cents\(\s*1999\s*,\s*(?:percent\s*=\s*)?10\s*\)")
EXPECTS = re.compile(r"==\s*(\d+)\s*$")


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "assertion_shared.py"
    module = types.ModuleType("assertion_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def expected_values(ctx) -> list[int]:
    """What the final test file expects from discount_cents(1999, 10), in each assertion that calls it."""
    final = Path(ctx.repo) / TEST_FILE
    text = final.read_text(encoding="utf-8", errors="replace") if final.is_file() else ""
    values = []
    for line in text.splitlines():
        found = EXPECTS.search(line.strip())
        if line.lstrip().startswith("assert") and CALL.search(line) and found:
            values.append(int(found.group(1)))
    return values


def assertion_updated(ctx):
    helpers = shared(ctx)
    lost, skips, values = helpers.lost_assertions(ctx), helpers.added_skips(ctx), expected_values(ctx)
    ok = lost == {TEST_FILE: [OLD_LINE]} and values == [200] and not skips
    return ok, f"assertions lost: {lost}; values expected from the rounded call: {values}; skip markers added: {skips}", {
        "lost": lost, "values": values, "skips": skips}


def docs_updated(ctx):
    changed = sorted(path for path in ctx.changes if path in ("README.md", "docs/ko/README.ko.md"))
    return len(changed) == 2, f"documents changed: {changed}", {"changed": changed}
