"""Unit tests for the skill review cases T154 and T155 of the end-to-end evaluation.

Offline proof: the unmodified fixture fails, the reference result passes only when a review route ran, and a wrong
grading or comparison fails the check that names it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from test_e2e_eval_forcing_tasks import FIXTURES_ROOT, TASKS_ROOT, ForcingTaskCase, graders, view_with

REVIEW = {"kind": "role_runner", "type": "reviewer", "class": "review", "prompt": "", "exit": 0, "tool_use_id": "r1",
          "order": 0, "is_error": False, "completed": True}
FAILED_REVIEW = {**REVIEW, "exit": 3, "completed": False}
GRADING = "release-notes-workspace/iteration-1/changelog-basic/with_skill/grading.json"
COMPARISON = "release-notes-workspace/blind-1/comparison.json"


class SkillReviewTaskTest(ForcingTaskCase):
    def graded(self, task_id: str, view: dict[str, Any], edit: tuple[str, Any] | None = None) -> set[str]:
        """The failed required checks of the reference result, with one JSON file replaced by `edit` when given."""
        self.count += 1
        task = graders.load_task(TASKS_ROOT, task_id)
        repo = self.root / f"repo-{self.count}"
        base = graders.materialize_fixture(task, FIXTURES_ROOT, TASKS_ROOT, repo)
        env = {**os.environ, "PYTHONPATH": str(TASKS_ROOT / "reference"), "PYTHONDONTWRITEBYTECODE": "1"}
        subprocess.run([sys.executable, "-B", str(TASKS_ROOT / "reference" / task_id / "apply.py"), str(repo)], cwd=repo,
                       env=env, check=True, capture_output=True, text=True)
        if edit is not None:
            (repo / edit[0]).write_text(json.dumps(edit[1]), encoding="utf-8")
        work = self.root / f"work-{self.count}"
        shutil.copytree(repo, work / "repo", symlinks=True)
        ctx = graders.GradeContext(task=task, repo=work / "repo", base=base, view=view, tasks_root=TASKS_ROOT, work=work,
                                   origin=repo)
        ctx.snapshot_git_facts()
        return self.failed_required({spec["id"]: graders.run_check(ctx, spec) for spec in task["checks"]})

    def test_두_과제는_수정하지_않은_저장소에서_결과_파일과_검토_경로_검사에_실패한다(self):
        """grading.json이나 comparison.json이 없고 검토 경로 실행이 없으면 필수 검사가 실패한다."""
        self.assertEqual(self.failed_required(self.results("T154", False, view_with())),
                         {"grading-saved", "marks-only-the-missed-expectation", "evidence-quotes-the-output", "review-route-ran"})
        self.assertEqual(self.failed_required(self.results("T155", False, view_with())),
                         {"comparison-saved", "prefers-the-compliant-output", "names-the-broken-rule", "review-route-ran"})

    def test_두_과제의_참조_결과는_검토_경로_실행이_있을_때만_모든_필수_검사를_통과한다(self):
        """검토 경로가 끝난 기록이 있으면 통과하고, 없거나 실패한 검토(종료 코드 3)면 검토 경로 검사만 실패한다."""
        for task_id in ("T154", "T155"):
            with self.subTest(task_id):
                self.assertEqual(self.graded(task_id, view_with(REVIEW)), set())
                self.assertEqual(self.graded(task_id, view_with()), {"review-route-ran"})
                self.assertEqual(self.graded(task_id, view_with(FAILED_REVIEW)), {"review-route-ran"})

    def test_T154는_다른_기대_항목을_실패로_표시하거나_근거가_출력을_인용하지_않으면_실패한다(self):
        """세 항목이 모두 통과이거나 첫 항목이 실패이면 실패한 항목 검사에서, 근거에 출력 인용이 없으면 인용 검사에서 실패한다."""
        def expectation(passed: bool, evidence: str) -> dict[str, Any]:
            return {"text": "x", "passed": passed, "evidence": evidence}
        quote = "ends with 'No upgrade steps.'"
        allpass = {"expectations": [expectation(True, quote)] * 3}
        wrong = {"expectations": [expectation(False, quote), expectation(True, quote), expectation(True, quote)]}
        bare = {"expectations": [expectation(True, quote), expectation(True, quote), expectation(False, "it is missing")]}
        self.assertEqual(self.graded("T154", view_with(REVIEW), (GRADING, allpass)), {"marks-only-the-missed-expectation"})
        self.assertIn("marks-only-the-missed-expectation", self.graded("T154", view_with(REVIEW), (GRADING, wrong)))
        self.assertEqual(self.graded("T154", view_with(REVIEW), (GRADING, bare)), {"evidence-quotes-the-output"})

    def test_T155는_위반한_출력을_고르거나_깨진_규칙을_말하지_않으면_실패한다(self):
        """승자가 A이면 승자 검사에서, 추론이 글머리표 한도를 말하지 않으면 규칙 검사에서 실패한다."""
        picked_a = {"winner": "A", "reasoning": "Output A at most 5 bullets."}
        no_rule = {"winner": "B", "reasoning": "Output B reads better."}
        self.assertEqual(self.graded("T155", view_with(REVIEW), (COMPARISON, picked_a)), {"prefers-the-compliant-output"})
        self.assertEqual(self.graded("T155", view_with(REVIEW), (COMPARISON, no_rule)), {"names-the-broken-rule"})
