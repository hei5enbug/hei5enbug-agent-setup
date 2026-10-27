"""Acceptance checks: Python files under scripts/ and skills/*/scripts/ stay within 800 lines."""
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LINE_LIMIT = 800
# Files that already exceed the limit, each capped at its line count when the limit was introduced. Lower a ceiling
# when a file shrinks and remove the entry once the file is within the limit; never raise one.
CEILINGS = {
    "scripts/approval_guard.py": 4573,
    "skills/orca-plugin-refresh/scripts/orca_plugin_refresh.py": 1761,
    "scripts/role_runner.py": 1071,
    "skills/tiki-taka/scripts/opponent_runner.py": 1011,
    "scripts/datagrip_guard.py": 992,
    "scripts/approval_state.py": 810,
}


def python_files():
    roots = [REPO_ROOT / "scripts", *sorted((REPO_ROOT / "skills").glob("*/scripts"))]
    return sorted(path for root in roots for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def line_count(path):
    return len(path.read_text(encoding="utf-8").splitlines())


def test_스크립트_Python_파일은_800줄_이하이고_예외_파일은_상한을_넘지_않는다():
    # given
    files = python_files()
    # when
    over = {path.relative_to(REPO_ROOT).as_posix(): line_count(path) for path in files}
    over = {name: count for name, count in over.items() if count > CEILINGS.get(name, LINE_LIMIT)}
    # then
    assert files
    assert over == {}, (
        f"split these files into modules of at most {LINE_LIMIT} lines instead of growing them "
        f"(a listed exception may not pass its ceiling): {over}"
    )


@pytest.mark.parametrize("name", sorted(CEILINGS))
def test_예외_목록은_아직_800줄을_넘는_기존_파일만_담는다(name):
    # given
    path = REPO_ROOT / name
    # when
    count = line_count(path) if path.is_file() else None
    # then
    assert count is not None, f"remove {name} from CEILINGS: the file no longer exists"
    assert count > LINE_LIMIT, f"remove {name} from CEILINGS: it is within {LINE_LIMIT} lines now"
