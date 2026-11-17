"""Custom checks for T66."""

from __future__ import annotations

from pathlib import Path

MIN_FILES, MAX_FILES = 3, 5


def is_test(path: str) -> bool:
    return path.startswith("tests/") and path.endswith(".py") and not path.startswith("tests/hidden/")


def new_tests(ctx):
    touched = sorted(path for path, status in ctx.changes.items() if status in ("A", "M") and is_test(path))
    useful = [path for path in touched if "transfer" in (Path(ctx.repo) / path).read_text(encoding="utf-8", errors="replace").lower()]
    return bool(useful), f"test files mentioning transfer: {useful}", {"touched": touched, "useful": useful}


def files_in_range(ctx):
    changed = sorted(ctx.changes)
    return MIN_FILES <= len(changed) <= MAX_FILES, f"{len(changed)} files changed; the task is built for {MIN_FILES} to {MAX_FILES}", {"changed": changed}
