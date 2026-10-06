"""Scope of the evaluation model adapter versus implementation workers.

Skill Builder must keep its evaluation-model rules for evaluation participants while routing workers that
edit the actual skill to the host's implementation execution rules when those rules apply.
"""

from __future__ import annotations

import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SKILL = SKILL_ROOT / "SKILL.md"
EXECUTION_METHODS = SKILL_ROOT / "references/execution-methods.md"
MODEL_ROUTING = SKILL_ROOT.parents[1] / "instructions/model-routing.md"


def adapter_section() -> str:
    text = EXECUTION_METHODS.read_text(encoding="utf-8")
    return text.split("## Evaluation model adapters", 1)[1].split("\n## ", 1)[0]


def table_rows(section: str) -> dict[str, list[str]]:
    rows = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) >= 3 and not set(cells[0]) <= {"-"}:
            rows[cells[0]] = cells[1:]
    return rows


class ImplementationWorkerScopeTest(unittest.TestCase):
    def test_작업자를_목적과_출력_위치로_구현과_평가로_나눈다(self):
        """실제 스킬 수정과 반영은 구현, 일회성 시험 결과와 채점 작업은 평가로 분류한다."""
        # Given
        section = adapter_section()

        # When
        rows = table_rows(section)

        # Then
        self.assertEqual(
            rows["Draft or revise the actual skill under development"],
            ["Repository or working tree that holds the skill", "Implementation"],
        )
        self.assertEqual(
            rows["Produce disposable trial artifacts for grading"],
            ["Evaluation workspace", "Evaluation"],
        )
        self.assertEqual(
            rows["Promote a trial artifact into the actual skill"],
            ["Repository or working tree that holds the skill", "Implementation"],
        )
        self.assertEqual(
            rows["Research, grade, compare, analyze, or optimize"],
            ["Evaluation workspace or inline result", "Evaluation"],
        )

    def test_구현_규칙이_있으면_구현_작업자만_그_규칙을_따른다(self):
        """호스트 구현 실행 규칙이 있을 때 구현 작업자만 그 규칙을 따르고 평가 참가자는 기존 표를 쓴다."""
        # Given
        section = " ".join(adapter_section().split())

        # When
        routes_implementation = (
            "When the host session instructions include implementation execution rules, implementation workers "
            "follow those rules instead of the table below."
        ) in section
        keeps_evaluation = "Evaluation participants always use the table below." in section

        # Then
        self.assertTrue(routes_implementation)
        self.assertTrue(keeps_evaluation)

    def test_단독_사용에서는_기존_표가_모든_작업자에_적용된다(self):
        """구현 실행 규칙이 없는 단독 사용에서는 구현을 포함한 모든 작업자에 기존 표를 적용한다."""
        # Given
        section = " ".join(adapter_section().split())

        # When
        standalone = "Otherwise, as in standalone use, the table below governs every worker, including implementation."

        # Then
        self.assertIn(standalone, section)

    def test_평가_모델_표는_그대로_남고_구현_모델_표를_복사하지_않는다(self):
        """평가 모델 표의 호스트별 모델과 사고 강도는 유지하고 구현 worker 모델 정책은 복사하지 않는다."""
        # Given
        section = adapter_section()

        # When
        rows = table_rows(section)

        # Then
        self.assertEqual(rows["Codex"][:2], ["`gpt-6-luna`", "`xhigh`"])
        self.assertEqual(rows["Claude Code"][:2], ["`claude-sonnet-5-5`", "`high`"])
        self.assertIn("Other hosts", rows)
        for copied in ("GPT Luna", "Claude Sonnet", "latest production", "implementation-execution.md"):
            self.assertNotIn(copied, section)

    def test_스킬_본문은_작업자_시작_전에_어댑터_섹션을_읽게_한다(self):
        """SKILL.md는 작업자와 runner를 시작하기 전에 같은 어댑터 섹션만 읽게 한다."""
        # Given
        skill = " ".join(SKILL.read_text(encoding="utf-8").split())

        # When
        pointer = 'Before launching any worker or model runner, read only "Evaluation model adapters"'

        # Then
        self.assertIn(pointer, skill)

    def test_Skill_Builder_평가표가_일반_scout_라우팅보다_우선한다(self):
        """Skill Builder 평가자는 고정된 모델 표를 따르고 scout 설정 불일치는 검증 runner나 미지원 경로로 처리한다."""
        # Given
        section = " ".join(adapter_section().split())

        # When
        precedence = "The Skill Builder evaluation contract takes precedence over generic host skill-worker routing."
        verified_runner = "a Skill Builder-approved runner whose actual model and effort can be verified"

        # Then
        self.assertIn("Evaluation participants always use the table below.", section)
        self.assertIn(precedence, section)
        self.assertIn("Run a native role only when its effective settings match the table below.", section)
        self.assertIn(verified_runner, section)
        self.assertIn("follow the unavailable-capability path", section)
        self.assertIn("Do not route an evaluation participant to a lower-effort scout", section)
        self.assertNotIn("target-skill metadata", section)

    def test_승인된_비교만_격리된_평가에서_고정_설정_하나를_바꾼다(self):
        """일반 비교는 모델과 사고 강도를 고정하고 승인된 한 설정 비교만 임시 평가 공간에서 허용한다."""
        # Given
        routing = " ".join(MODEL_ROUTING.read_text(encoding="utf-8").split())
        methods = " ".join(EXECUTION_METHODS.read_text(encoding="utf-8").split())

        # When
        ordinary = "Keep the model and settings the same on both sides of an ordinary method comparison"
        exception = "Only a specifically approved model or effort experiment may vary its one frozen candidate setting"

        # Then
        self.assertIn(ordinary, methods)
        self.assertIn(exception, methods)
        self.assertIn("in the disposable evaluation workspace", methods)
        self.assertIn("It must not change production settings or promote trial output to the repository.", methods)
        self.assertIn("Ordinary method comparisons keep model and effort fixed on both sides.", routing)
        self.assertIn("A specifically approved model or effort comparison may vary only its one frozen candidate setting", routing)


if __name__ == "__main__":
    unittest.main()
