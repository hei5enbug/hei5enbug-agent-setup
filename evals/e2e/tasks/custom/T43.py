"""Custom checks for T43: a fractional discount percent that must not change how a whole percent rounds."""

from __future__ import annotations

import re
import types
from pathlib import Path

MIN_FILES_CHANGED = 3
ADDED_TEST_DEF = re.compile(r"^\+\s*def\s+test_")
DECIMAL_LITERAL = re.compile(r"\b\d+\.\d+\b")


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "assertion_shared.py"
    module = types.ModuleType("assertion_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def assertions_kept(ctx):
    helpers = shared(ctx)
    lost, skips = helpers.lost_assertions(ctx), helpers.added_skips(ctx)
    return not lost and not skips, f"assertions lost: {lost}; skip markers added: {skips}", {"lost": lost, "skips": skips}


def new_tests(ctx):
    helpers = shared(ctx)
    tests = sorted(path for path in ctx.changes if helpers.TEST_FILE.search(path))
    useful = []
    for path in tests:
        diff = ctx.git("diff", ctx.base, "--", path) if ctx.changes[path] == "M" else "".join(
            f"+{line}\n" for line in (Path(ctx.repo) / path).read_text(encoding="utf-8", errors="replace").splitlines())
        added = [line for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
        if any(ADDED_TEST_DEF.match(line) for line in added) and any(DECIMAL_LITERAL.search(line) for line in added):
            useful.append(path)
    return bool(useful), f"test files that add a test with a fractional percent: {useful}", {"changed": tests, "useful": useful}


def files_changed(ctx):
    changed = sorted(ctx.changes)
    return len(changed) >= MIN_FILES_CHANGED, f"{len(changed)} files changed", {"changed": changed}
