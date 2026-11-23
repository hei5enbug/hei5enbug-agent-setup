"""Custom checks for T37."""

from __future__ import annotations

from pathlib import Path

MIN_FILES_CHANGED = 3


def is_agent_test(path: str) -> bool:
    return path.startswith("tests/") and path.endswith(".py") and not path.startswith("tests/hidden/")


def adds_import_test(diff: str) -> bool:
    return any(line.startswith("+") and "def test_" in line and "import" in line.lower() for line in diff.splitlines())


def new_tests(ctx):
    added = sorted(path for path, status in ctx.changes.items() if status == "A" and is_agent_test(path))
    useful = [path for path in added if "import" in (Path(ctx.repo) / path).read_text(encoding="utf-8", errors="replace").lower()]
    modified = sorted(path for path, status in ctx.changes.items() if status == "M" and is_agent_test(path)
                      and adds_import_test(ctx.git("diff", ctx.base, "--", path)))
    return bool(useful or modified), f"test files mentioning import: {useful + modified}", {
        "added": added, "useful": useful, "modified": modified}


def files_changed(ctx):
    changed = sorted(path for path in ctx.changes if not path.startswith("tests/hidden/"))
    return len(changed) >= MIN_FILES_CHANGED, f"{len(changed)} files changed", {"changed": changed}
