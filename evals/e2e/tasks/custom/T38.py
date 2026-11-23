"""Custom checks for T38."""

from __future__ import annotations

import re
import types
from pathlib import Path

MIN_FILES_CHANGED = 3
ADDED_TEST_DEF = re.compile(r"^\+\s*def\s+test_")
ZONE_C = re.compile(r"[\"']C[\"']")


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "existing_assertions.py"
    module = types.ModuleType("existing_assertions")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def existing_assertions_kept(ctx):
    problems, data = shared(ctx).untouched_problems(ctx)
    return not problems, "; ".join(problems[:5]) or "every pre-existing assertion, test, and skip state is unchanged", data


def new_tests(ctx):
    diff = ctx.git("diff", ctx.base, "--", "tests/test_rates.py")
    added = [line for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
    ok = any(ADDED_TEST_DEF.match(line) for line in added) and any(ZONE_C.search(line) for line in added)
    return ok, "tests/test_rates.py gained a zone C test" if ok else "tests/test_rates.py gained no zone C test", {}


def files_changed(ctx):
    changed = sorted(path for path in ctx.changes if not path.startswith("tests/hidden/"))
    return len(changed) >= MIN_FILES_CHANGED, f"{len(changed)} files changed", {"changed": changed}
