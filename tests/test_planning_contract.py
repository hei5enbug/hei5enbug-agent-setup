from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION = REPO_ROOT / "instructions/implementation-planning.md"
VALIDATION = REPO_ROOT / "instructions/independent-model-validation.md"
EXECUTION = REPO_ROOT / "instructions/implementation-execution.md"
COMMON = REPO_ROOT / "instructions/session/common.md"
DESIGN = REPO_ROOT / "skills/technical-design-writer/references/design-documents.md"
DESIGN_SKILL = REPO_ROOT / "skills/technical-design-writer/SKILL.md"


class PlanningContractTest(unittest.TestCase):
    def test_implementation_plan_has_six_ordered_stages(self):
        headings = re.findall(r"^## ([1-6])\. (.+)$", IMPLEMENTATION.read_text(), re.MULTILINE)
        self.assertEqual([number for number, _ in headings], list("123456"))
        self.assertEqual(len(headings), 6)

    def test_workflows_are_separate(self):
        implementation = IMPLEMENTATION.read_text()
        design = DESIGN.read_text()
        skill = DESIGN_SKILL.read_text()
        self.assertNotIn("Design document workflow", implementation)
        self.assertNotIn("Implementation planning", design)
        self.assertIn("Implementation planning", implementation)
        self.assertIn("Design document workflow", design)
        self.assertNotIn("## Workflow", skill)
        self.assertIn("references/design-documents.md", skill)

    def test_model_selection_has_one_canonical_source(self):
        validation = VALIDATION.read_text()
        mapping = (
            re.compile(r"\| GPT \| `claude-fable-[\d-]+` \| `xhigh` \|"),
            re.compile(r"\| Claude \| `gpt-[\d.]+-sol` \| `xhigh` \|"),
        )
        for row in mapping:
            self.assertRegex(validation, row)
        for path in (IMPLEMENTATION, DESIGN):
            text = path.read_text()
            self.assertIsNone(re.search(r"claude-fable-|gpt-[\d.]+-sol|Claude Fable|GPT Sol", text))

        signatures = (
            "exactly one reviewer from the other model family",
            "This is one validation pass, not a debate",
        )
        for root in (REPO_ROOT / "instructions", REPO_ROOT / "skills"):
            for path in root.rglob("*.md"):
                if path.name.endswith(".ko.md") or path == VALIDATION:
                    continue
                with self.subTest(path=path.relative_to(REPO_ROOT)):
                    text = path.read_text()
                    for signature in signatures:
                        self.assertNotIn(signature, text)
                    for row in mapping:
                        self.assertIsNone(row.search(text))

    def test_validation_is_one_pass_and_read_only(self):
        validation = VALIDATION.read_text()
        self.assertIn("exactly one reviewer", validation)
        self.assertIn("read-only session", validation)
        self.assertIn("not a debate", validation)
        self.assertIn("do not substitute", validation)

    def test_validation_runs_only_after_a_user_confirmation_gate(self):
        validation = VALIDATION.read_text()
        self.assertIn("## Confirmation gate", validation)
        self.assertIn("only when the user approves it", validation)
        self.assertIn("Ask for every deliverable", validation)
        self.assertIn("write nothing about the skipped review inside it", validation)
        self.assertLess(
            validation.index("## Confirmation gate"),
            validation.index("## Reviewer selection"),
        )

        for path in (IMPLEMENTATION, DESIGN):
            text = path.read_text()
            with self.subTest(path=path.relative_to(REPO_ROOT)):
                self.assertIn("confirmation gate", text)
                self.assertNotIn("Confirmation gate", text)
                self.assertNotIn("only when the user approves it", text)


    def test_계획_실행_단위는_공통_할당_항목을_참조한다(self):
        """요청한 구현 계획의 실행 단위는 공통 할당 항목과 호스트 모델 정책을 참조로만 싣는다."""
        # Given
        implementation = IMPLEMENTATION.read_text()

        # When
        slicing = implementation.split("## 3. Execution slicing", 1)[1].split("## 4.", 1)[0]
        template = implementation.split("## Output template", 1)[1]

        # Then
        self.assertIn("[implementation execution](implementation-execution.md)", slicing)
        self.assertIn("one main or worker owner", slicing)
        self.assertIn("which the host's agent rules pin, instead of copying a model ID", slicing)
        self.assertIn("Allowed and protected paths", template)
        self.assertIn("Shared resources and parallel condition", template)
        self.assertIn("Worker model and effort:", template)
        for pinned in ("gpt-", "claude-", "Luna", "Sonnet"):
            self.assertNotIn(pinned, implementation)

    def test_자동_작업_준비는_정식_계획_절차와_독립_검증을_실행하지_않는다(self):
        """구현 전 자동 작업 준비는 6단계 계획 절차나 독립 검증을 불러오지 않는다."""
        # Given
        execution = EXECUTION.read_text()

        # When
        links = re.findall(r"\]\(([^)]+)\)", execution)

        # Then
        self.assertIn("This preparation is not a requested implementation plan.", execution)
        self.assertIn("no six-stage", execution)
        self.assertIn("no independent validation", execution)
        self.assertNotIn("independent-model-validation.md", links)
        self.assertNotIn("implementation-planning.md", links)
        self.assertIsNone(re.search(r"^## [1-6]\. ", execution, re.MULTILINE))

    def test_공통_규칙은_요청한_계획에만_계획_규칙을_읽게_한다(self):
        """공통 규칙은 사용자가 요청한 계획에만 계획 규칙을 읽게 하고 작업 준비를 계획 요청으로 보지 않는다."""
        # Given
        common = " ".join(COMMON.read_text().split())

        # When
        routes_requested_plans = "Before creating or revising an implementation plan the user requested, read" in common
        excludes_preparation = "Task preparation under the implementation execution rules is not such a request." in common

        # Then
        self.assertTrue(routes_requested_plans)
        self.assertTrue(excludes_preparation)
        self.assertIn("[implementation execution rules](../implementation-execution.md)", common)

    def test_할당받은_worker는_계획_검토_하위_에이전트를_시작하지_않는다(self):
        """할당받은 worker 섹션은 재귀 계획, 하위 에이전트, 계획 검토를 금지하고 반환 항목을 정한다."""
        # Given
        execution = EXECUTION.read_text()

        # When
        worker_section = " ".join(execution.split("## Assigned workers", 1)[1].split())

        # Then
        self.assertIn("never acts as a coordinator", worker_section)
        self.assertIn("Never prepare a plan", worker_section)
        self.assertIn("request plan review or independent validation", worker_section)
        self.assertIn("start another agent", worker_section)
        self.assertIn("preserve changes made by other workers", worker_section)
        self.assertIn("Return the changed paths, check results, and remaining blockers.", worker_section)
        self.assertEqual(execution.count("## Assigned workers"), 1)
        self.assertTrue(execution.rstrip().endswith("remaining blockers."))


    def test_의존_작업은_선행_작업_승인_뒤에만_따로_할당한다(self):
        """작업과 그 선행 작업은 한 할당에 넣지 않고, 파일만 공유하는 작업만 한 worker에 순서대로 맡길 수 있다."""
        # Given
        execution = EXECUTION.read_text()

        # When
        scheduling = " ".join(execution.split("## Scheduling", 1)[1].split("\n## ", 1)[0].split())

        # Then
        self.assertIn("A task becomes ready only after its prerequisites pass the coordinator's acceptance check", scheduling)
        self.assertIn("Acceptance requires the task's assigned verification to pass.", scheduling)
        self.assertIn("Never put a task and its prerequisite in one assignment.", scheduling)
        self.assertIn("Tasks that only share files may go to one worker in sequence.", scheduling)


    def test_할당된_검사_실패는_원인과_무관하게_실패로_보고_의존_작업을_보류한다(self):
        """할당된 검사가 실패하면 원인이 작업 밖에 있어도 실패로 보고 의존 작업을 보류한다."""
        # Given
        execution = EXECUTION.read_text()

        # When
        failure = " ".join(execution.split("## Failure and recovery", 1)[1].split("\n## ", 1)[0].split())

        # Then
        self.assertIn("hold dependent tasks and preserve completed work", failure)
        self.assertIn("A failed assigned check is a failure even when its cause lies outside the task.", failure)


    def test_위임한_작업은_수정한_모든_턴의_호스트_기록을_확인한_뒤에만_승인한다(self):
        """위임한 작업은 수정한 모든 턴의 호스트 기록이 선택한 모델과 사고 강도를 보여 줄 때만 승인한다."""
        # Given
        execution = EXECUTION.read_text()

        # When
        review = " ".join(execution.split("## Review and integration", 1)[1].split("\n## ", 1)[0].split())

        # Then
        self.assertIn(
            "Accept delegated work only when the host record shows the selected model and effort for every turn that edited it.",
            review,
        )

    def test_범위_밖_추적_파일_변경은_사용자_승인을_먼저_받는다(self):
        """요청이나 합의한 계획 밖의 추적 파일을 바꾸는 작업은 할당 전에 사용자 승인을 받는다."""
        # Given
        execution = EXECUTION.read_text()

        # When
        preparation = " ".join(execution.split("## Task preparation", 1)[1].split("\n## ", 1)[0].split())

        # Then
        self.assertIn(
            "At any point, ask the user before assigning a change to a tracked file outside the request or the "
            "accepted plan, such as a shared file that no task may edit.",
            preparation,
        )
        self.assertIn("Wait for the answer, and make no such change without approval.", preparation)

    def test_작업_준비_표는_이미_할당받은_worker를_worker_섹션으로_보낸다(self):
        """작업 준비 표는 이미 할당받은 worker에게 worker 섹션을 따르고 다른 계획 절차를 시작하지 말라고 안내한다."""
        # Given
        execution = EXECUTION.read_text()

        # When
        rows = [line for line in execution.splitlines() if line.startswith("| Existing assigned worker |")]

        # Then
        self.assertEqual(len(rows), 1)
        self.assertIn('Follow "Assigned workers" below.', rows[0])
        self.assertIn("never start another planning workflow", rows[0])


if __name__ == "__main__":
    unittest.main()
