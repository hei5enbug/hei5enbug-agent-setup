"""The rule-to-enforcer table names every test file, and every file it names exists."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TABLE = REPO_ROOT / "docs/rule-enforcement.md"
TEST_GLOBS = ("tests/test_*.py", "skills/*/tests/test_*.py", "skills/*/tests/test_*.mjs")
ENFORCER_CELL = re.compile(r"^\| ([^|]+) \|", re.MULTILINE)
CODE_SPAN = re.compile(r"`([^`]+)`")


def listed_test_files() -> set[str]:
    return {path.relative_to(REPO_ROOT).as_posix() for pattern in TEST_GLOBS for path in REPO_ROOT.glob(pattern)}


def enforcers() -> set[str]:
    text = TABLE.read_text(encoding="utf-8")
    return {span for cell in ENFORCER_CELL.findall(text) for span in CODE_SPAN.findall(cell)}


class RuleEnforcementTableTest(unittest.TestCase):
    def test_표는_모든_테스트_파일을_집행자로_적는다(self):
        """테스트 파일이 새로 생기면 규칙-집행자 표에도 그 행이 있어야 한다."""
        # Given
        files = listed_test_files()
        self.assertTrue(files)

        # When
        missing = sorted(files - enforcers())

        # Then
        self.assertEqual(missing, [], f"add these test files to {TABLE.relative_to(REPO_ROOT)}: {missing}")

    def test_표의_집행자_경로는_모두_존재한다(self):
        """지운 테스트 파일이 표에 남지 않는다."""
        # Given
        paths = {name for name in enforcers() if "/" in name and "*" not in name}

        # When
        stale = sorted(name for name in paths if not (REPO_ROOT / name).is_file())

        # Then
        self.assertEqual(stale, [], f"remove or rename these rows in {TABLE.relative_to(REPO_ROOT)}: {stale}")


if __name__ == "__main__":
    unittest.main()
