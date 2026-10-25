"""Custom checks for T02."""

from __future__ import annotations

from pathlib import Path

MIN_FILES_CHANGED = 4


def is_test(path: str) -> bool:
    return path.startswith("tests/") and path.endswith(".py")


def new_tests(ctx):
    added = sorted(path for path, status in ctx.changes.items() if status == "A" and is_test(path))
    useful = [
        path for path in added
        if "shipping" in (Path(ctx.repo) / path).read_text(encoding="utf-8", errors="replace").lower()
    ]
    return bool(useful), f"new test files mentioning shipping: {useful}", {"added": added, "useful": useful}


def files_changed(ctx):
    changed = sorted(ctx.changes)
    return len(changed) >= MIN_FILES_CHANGED, f"{len(changed)} files changed", {"changed": changed}
