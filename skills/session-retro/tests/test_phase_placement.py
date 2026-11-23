#!/usr/bin/env python3
"""SKILL.md가 세션 목록 단계를 메인 세션에 두고, 목록 스크립트가 실패하면 작업자 없이 실행 전체를 멈추라고 하는지 검사한다."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"


def placement() -> dict[str, str]:
    text = SKILL.read_text(encoding="utf-8")
    table = text.split("## Execution placement", 1)[1].split("\n## ", 1)[0]
    return {phase.strip(): owner.strip() for phase, owner in re.findall(r"^\|\s*(\d[^|]*?)\s*\|\s*([^|]+?)\s*\|$", table, re.M)}


def phase_two() -> str:
    return SKILL.read_text(encoding="utf-8").split("### 2. List the sessions", 1)[1].split("\n### 3.", 1)[0]


class PhasePlacementTest(unittest.TestCase):
    def test_세션_목록은_메인_세션이_맡고_근거_수집만_investigation이_맡는다(self) -> None:
        """2단계는 main, 3단계는 investigation, 1단계와 4단계 이후는 main이다."""
        # Given / When
        owners = placement()
        # Then
        self.assertEqual(
            {"1. Fix the target": "main", "2. List the sessions": "main", "3. Gather evidence": "`investigation`",
             "4. Verify against the sources": "main", "5–7. Improvement table, decision questions, and any requested plan": "main"},
            owners,
        )

    def test_2단계는_작업자에게_스크립트_호출을_넘기라고_하지_않는다(self) -> None:
        """2단계 본문에 작업자나 investigation에 맡긴다는 말이 없고 메인 세션 실행을 명시한다."""
        # Given / When
        text = phase_two()
        # Then
        self.assertIn("in the main session", text)
        self.assertNotRegex(text, r"investigation|give .* to .* worker|hand .* to .* worker")

    def test_스크립트가_1이나_2로_끝나면_3단계_전에_멈추고_작업자를_시작하지_않는다(self) -> None:
        """종료 코드 1과 2는 종료 코드와 메시지를 보고하고 3단계 전에 전체를 멈추며 재시도 작업자를 시작하지 않는다."""
        # Given / When
        text = " ".join(phase_two().split())
        # Then
        for part in ("exits with 1 or 2", "report the exit code and its message", "stop the whole run before step 3",
                     "start no worker to retry"):
            self.assertIn(part, text)


if __name__ == "__main__":
    unittest.main()
