"""Custom check for T03: the agent added a regression test of its own."""

from __future__ import annotations

from pathlib import Path


def adds_test_function(ctx, path: str, status: str) -> bool:
    if status == "A":
        return "def test_" in (Path(ctx.repo) / path).read_text(encoding="utf-8", errors="replace")
    diff = ctx.git("diff", ctx.base, "--", path)
    return any(line.startswith("+") and "def test_" in line for line in diff.splitlines())


def regression_test_added(ctx):
    candidates = sorted(
        path for path in ctx.changes
        if path.startswith("tests/") and path.endswith(".py") and not path.startswith("tests/hidden/")
        and ctx.changes[path] in ("A", "M")
    )
    added = [path for path in candidates if adds_test_function(ctx, path, ctx.changes[path])]
    return bool(added), (f"test added in {added}" if added else "no new test function under tests/"), {"added": added}
