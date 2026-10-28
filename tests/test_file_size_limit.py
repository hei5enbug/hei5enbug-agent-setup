"""Acceptance checks: Python files under scripts/ and skills/*/scripts/ stay within 800 lines."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LINE_LIMIT = 800


def python_files():
    roots = [REPO_ROOT / "scripts", *sorted((REPO_ROOT / "skills").glob("*/scripts"))]
    return sorted(path for root in roots for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def line_count(path):
    return len(path.read_text(encoding="utf-8").splitlines())


def test_스크립트_Python_파일은_800줄_이하이다():
    # given
    files = python_files()
    # when
    over = {path.relative_to(REPO_ROOT).as_posix(): line_count(path) for path in files}
    over = {name: count for name, count in over.items() if count > LINE_LIMIT}
    # then
    assert files
    assert over == {}, f"split these files into modules of at most {LINE_LIMIT} lines: {over}"
