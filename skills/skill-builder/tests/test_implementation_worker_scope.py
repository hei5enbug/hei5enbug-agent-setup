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
            ["Evaluation workspace", "Trial execution"],
        )
        self.assertEqual(
            rows["Promote a trial artifact into the actual skill"],
            ["Repository or working tree that holds the skill", "Implementation"],
        )
        self.assertEqual(
            rows["Trial execution and other non-review work, such as research or optimization"],
            ["Evaluation workspace or inline result", "Non-review participant"],
        )
        self.assertEqual(
            rows["Review persona, grading, comparison, or analysis"],
            ["Evaluation workspace or inline result", "Read-only review"],
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
        keeps_evaluation = "Evaluation participants use the model adapter below." in section

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

    def test_시험_및_비검토_참여자는_호스트별_상위_모델을_쓴다(self):
        """Codex는 gpt-6.1-sol과 xhigh, Claude Code는 claude-opus-5-5와 high를 시험 및 비검토 작업에 쓴다."""
        # Given
        section = adapter_section()

        # When
        rows = table_rows(section)

        # Then
        self.assertEqual(rows["Codex"][:2], ["`gpt-6.1-sol`", "`xhigh`"])
        self.assertEqual(rows["Claude Code"][:2], ["`claude-opus-5-5`", "`high`"])
        self.assertIn("Other hosts", rows)
        for copied in ("gpt-6-luna", "claude-sonnet-5-5", "latest production", "implementation-execution.md"):
            self.assertNotIn(copied, section)

    def test_검토_역할은_교차_계열_후_같은_계열_reviewer로_대체한다(self):
        """검토 역할은 다른 모델 계열을 먼저 쓰고 CLI에 문제가 있으면 reviewer 대체 경로와 메인 검토를 한 번 쓴다."""
        # Given
        section = " ".join(adapter_section().split())

        # When
        routes = table_rows(adapter_section())

        # Then
        self.assertIn("review persona, grader, comparator, or analyzer", section.lower())
        self.assertIn("Codex", routes)
        self.assertIn("claude -p", routes["Codex"][2])
        self.assertIn("reviewer", routes["Codex"][2])
        self.assertIn("codex exec", routes["Claude Code"][2])
        self.assertIn("reviewer", routes["Claude Code"][2])
        self.assertIn("reviews the same material once", section)
        self.assertIn("Do not run another review round.", section)
        self.assertIn("Do not send a review role to `scout`", section)

    def test_스킬_본문은_작업자_시작_전에_어댑터_섹션을_읽게_한다(self):
        """SKILL.md는 작업자와 runner를 시작하기 전에 같은 어댑터 섹션만 읽게 한다."""
        # Given
        skill = " ".join(SKILL.read_text(encoding="utf-8").split())

        # When
        pointer = 'Before launching any worker or model runner, read only "Evaluation model adapters"'

        # Then
        self.assertIn(pointer, skill)

    def test_Skill_Builder_참여자와_검토_계약이_일반_라우팅보다_우선한다(self):
        """Skill Builder 참여자와 검토자는 어댑터의 모델 표를 따르고 메인 세션이 최종 판단을 맡는다."""
        # Given
        section = " ".join(adapter_section().split())

        # When
        precedence = "The Skill Builder review and participant contract takes precedence over generic host skill-worker routing"
        verified_runner = "A runner invocation alone does not verify its effective settings."

        # Then
        self.assertIn("Evaluation participants use the model adapter below.", section)
        self.assertIn(precedence, section)
        self.assertIn(verified_runner, section)
        self.assertIn("target-skill metadata", section)
        self.assertIn("Do not send a review role to `scout`", section)

    def test_승인된_비교만_격리된_평가에서_고정_설정_하나를_바꾼다(self):
        """일반 비교는 모델과 사고 강도를 고정하고 승인된 한 설정 비교만 임시 평가 공간에서 허용한다."""
        # Given
        routing = " ".join(MODEL_ROUTING.read_text(encoding="utf-8").split())
        methods = " ".join(EXECUTION_METHODS.read_text(encoding="utf-8").split())

        # When
        ordinary = "Keep model and effort fixed on both sides of an ordinary method comparison."
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
