"""Custom checks for T39."""

from __future__ import annotations

import ast
import types
from pathlib import Path

CHANGED_INPUT = "Decimal('10.7')"
HALF_UP_RESULT = 11
OLD_ASSERTION = "assert round_cents(Decimal('10.7')) == 10"
OLD_TEST = "test_a_large_fraction_is_dropped_too"


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "existing_assertions.py"
    module = types.ModuleType("existing_assertions")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def expectations(ctx) -> list[object]:
    """What every assertion about the changed input expects, over the tests the agent left."""
    found: list[object] = []
    for path in sorted((Path(ctx.repo) / "tests").rglob("*.py")):
        if "hidden" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert) and CHANGED_INPUT in ast.unparse(node) and isinstance(node.test, ast.Compare):
                try:
                    found.append(ast.literal_eval(node.test.comparators[0]))
                except ValueError:
                    found.append(None)
    return found


def old_assertion_updated(ctx):
    found = expectations(ctx)
    ok = bool(found) and all(value == HALF_UP_RESULT for value in found)
    return ok, f"assertions about {CHANGED_INPUT} expect {found}", {"expected": found}


def other_assertions_kept(ctx):
    problems, data = shared(ctx).untouched_problems(ctx, allowed=[OLD_ASSERTION], allowed_tests=[OLD_TEST])
    return not problems, "; ".join(problems[:5]) or "no pre-existing assertion but the rounding one changed", data
