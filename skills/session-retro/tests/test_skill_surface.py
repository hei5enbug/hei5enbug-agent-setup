#!/usr/bin/env python3
"""SKILL.md가 조건부 압축 절차를 참조 파일로 넘기고, 참조 파일이 압축 계약을 담는지 검사한다."""

from __future__ import annotations

import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL = SKILL_DIR / "SKILL.md"
REFERENCE = SKILL_DIR / "references" / "condensing.md"
ENTRY_LINE = "When they exceed 1 MB, read `references/condensing.md` before giving them to a worker."
CONTRACT_PARTS = (
    "python3 scripts/condense_records.py",
    "L<original line number> <kind> <text>",
    "exits with 0 on success, 2 for an invalid",
    "opens an original only to check a quote.",
)


class CondensingReferenceTest(unittest.TestCase):
    def test_skill_keeps_the_size_check_and_one_entry_line_only(self) -> None:
        """SKILL.md는 크기 확인과 참조 진입 한 줄만 두고 압축 명령과 출력 계약은 두지 않는다."""
        # Given
        text = SKILL.read_text(encoding="utf-8")
        # When
        has_entry = ENTRY_LINE in " ".join(text.split())
        # Then
        self.assertTrue(has_entry)
        self.assertIn("Add up the sizes of the files of each session or group.", text)
        for part in CONTRACT_PARTS:
            self.assertNotIn(part, text)

    def test_reference_holds_the_condensing_contract(self) -> None:
        """references/condensing.md가 명령, 줄 형식, 종료 코드, 인용 절차를 담는다."""
        # Given
        text = REFERENCE.read_text(encoding="utf-8")
        # When
        flat = " ".join(text.split())
        # Then
        for part in CONTRACT_PARTS:
            self.assertIn(part, flat)


if __name__ == "__main__":
    unittest.main()
