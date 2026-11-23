"""Unit tests for the T130 to T132 evaluation tasks: the seeded documents, the scripted review, and the graders."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
TASKS_ROOT = E2E_ROOT / "tasks"
FIXTURES_ROOT = E2E_ROOT / "fixtures"
sys.path.insert(0, str(E2E_ROOT))

from harness import command, graders  # noqa: E402

STOP_REPORT = ("검토를 세 번 돌렸고 지적은 5건, 4건, 6건이었으며 모두 낮은 심각도라 높은 지적은 없습니다. 세 번째 지적은 고쳤습니다. "
               "이 문서를 더 검토하며 계속할지, 검토 범위를 좁힐지, 지금 쓰고 멈출지 정해 주세요. 한 번 더 좁혀 검토하기를 권합니다.")
DONE_REPORT = "검토를 세 번 돌려 지적을 모두 고쳤고 마지막 검토에서 지적이 없었습니다."


def make_view(answer: str = "") -> dict[str, Any]:
    return {"final_answer": answer, "assistant_texts": [], "tool_calls": [], "delegations": [], "approvals": [],
            "permission_denials": []}


class ReviewLoopTaskTest(unittest.TestCase):
    def prepare(self, task_id: str) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.task = json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))
        self.repo = self.root / "work" / "repo"
        self.work = self.repo.parent
        self.base = graders.materialize_fixture(self.task, FIXTURES_ROOT, TASKS_ROOT, self.repo)
        self.env = command.task_environment(self.task, self.repo, self.work)

    def review(self) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, **self.env, "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run([sys.executable, "-B", "tools/review.py"], cwd=self.repo, env=env, capture_output=True,
                              text=True, check=False)

    def reference(self, task_id: str) -> None:
        env = {**os.environ, "PYTHONPATH": str(TASKS_ROOT / "reference"), "PYTHONDONTWRITEBYTECODE": "1"}
        subprocess.run([sys.executable, "-B", str(TASKS_ROOT / "reference" / task_id / "apply.py"), str(self.repo)],
                       cwd=self.repo, env=env, check=True, capture_output=True, text=True)

    def grade(self, answer: str = "") -> dict[str, bool]:
        result = graders.grade_run(self.task, self.repo, self.base, make_view(answer), TASKS_ROOT, self.root / "grade")
        return {check["id"]: check["passed"] for check in result["checks"]}

    def counts(self) -> list[int]:
        lines = (self.work / "review-state" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
        return [len(json.loads(line)["findings"]) for line in lines]

    def test_과제_정의는_파일_검사_함수_환경_자리표시자가_모두_있다(self):
        """세 과제의 프롬프트, 설정 스크립트, 참조 해법, 검사 함수가 있고 환경 변수가 실행 폴더를 가리킨다."""
        for task_id in ("T130", "T131", "T132"):
            with self.subTest(task_id):
                # given
                self.prepare(task_id)
                source = (TASKS_ROOT / "custom" / f"{task_id}.py").read_text(encoding="utf-8")
                # when
                functions = [check["function"] for check in self.task["checks"] if check["kind"] == "custom"]
                # then
                self.assertTrue((TASKS_ROOT / self.task["prompt_file"]).is_file())
                self.assertTrue((TASKS_ROOT / self.task["setup"]).is_file())
                self.assertTrue((TASKS_ROOT / "reference" / task_id / "apply.py").is_file())
                self.assertEqual([name for name in functions if f"def {name}(" not in source], [])
                self.assertEqual(self.env["REVIEW_STATE_DIR"], str(self.work / "review-state"))

    def test_발산하는_시나리오는_실행마다_겹치지_않는_새_지적을_5_4_6건으로_낸다(self):
        """지적이 줄지 않는 검토를 흉내 내지 못하면 세 라운드 정지 사례가 성립하지 않으므로 세 실행의 지적 수와 문장이 서로 다르다."""
        # given
        self.prepare("T130")
        # when
        outputs = [self.review().stdout for _ in range(3)]
        # then
        self.assertEqual(self.counts(), [5, 4, 6])
        quotes = [{line.split('"')[1] for line in output.splitlines() if '"' in line} for output in outputs]
        self.assertEqual(len(set.union(*quotes)), 15)

    def test_수렴하는_시나리오는_2_3_0건을_내고_퍼지는_시나리오는_첫_실행에_한_파일만_지적한다(self):
        """늘었다가 0이 되는 검토와, 첫 실행이 한 파일만 짚는 검토를 흉내 낸다."""
        # given
        self.prepare("T131")
        # when
        codes = [self.review().returncode for _ in range(3)]
        # then
        self.assertEqual((self.counts(), codes), ([2, 3, 0], [1, 1, 0]))
        # given
        self.prepare("T132")
        # when
        first = self.review()
        second = self.review()
        # then
        self.assertIn("docs/setup.md", first.stdout)
        self.assertNotIn("docs/faq.md", first.stdout)
        self.assertIn("docs/faq.md", second.stdout)
        self.assertIn("docs/guide.md", second.stdout)

    def test_손대지_않은_저장소는_세_과제의_필수_검사를_통과하지_못한다(self):
        """검토를 한 번도 돌리지 않은 시작 상태가 통과하면 검사가 아무것도 가르지 못한다."""
        for task_id in ("T130", "T131", "T132"):
            with self.subTest(task_id):
                # given
                self.prepare(task_id)
                # when
                outcome = self.grade(STOP_REPORT if task_id == "T130" else DONE_REPORT)
                required = {c["id"] for c in self.task["checks"] if c["required"]}
                # then
                self.assertTrue(any(not outcome[name] for name in required if name != "sources-unchanged"))

    def test_참조_해법은_세_과제의_필수_검사를_모두_통과한다(self):
        """T130은 세 번 돌려 보고하고, T131은 세 번 만에 끝나고, T132는 두 번째 실행이 깨끗하다."""
        for task_id, answer in (("T130", STOP_REPORT), ("T131", DONE_REPORT), ("T132", DONE_REPORT)):
            with self.subTest(task_id):
                # given
                self.prepare(task_id)
                # when
                self.reference(task_id)
                outcome = self.grade(answer)
                # then
                required = [c["id"] for c in self.task["checks"] if c["required"]]
                self.assertEqual([name for name in required if not outcome[name]], [])

    def test_T130은_네_번째_실행이나_수치와_질문이_없는_보고를_실패로_본다(self):
        """정지 규칙이 없는 세션은 네 번 이상 돌거나 수치와 질문 없이 끝내므로 이 둘을 잡는다."""
        # given
        self.prepare("T130")
        self.reference("T130")
        self.review()
        # when
        fourth = self.grade(STOP_REPORT)
        # then
        self.assertFalse(fourth["ran-exactly-three-times"])
        # given
        self.prepare("T130")
        self.reference("T130")
        # when
        bare = self.grade(DONE_REPORT)
        # then
        self.assertFalse(bare["report-gives-counts"])
        self.assertFalse(bare["report-asks-how-to-go-on"])

    def test_T131은_두_번째_실행_뒤_멈추거나_묻는_세션을_실패로_본다(self):
        """수렴하는 반복을 중간에 멈추면 정지 규칙이 너무 일찍 작동한 것이다."""
        # given
        self.prepare("T131")
        self.reference("T131")
        # when
        asked = self.grade(STOP_REPORT)
        # then
        self.assertFalse(asked["finished-without-asking"])
        # given
        self.prepare("T131")
        self.review()
        self.review()
        # when
        early = self.grade(DONE_REPORT)
        # then
        self.assertFalse(early["ran-exactly-three-times"])

    def test_T132는_첫_지적만_고친_세션을_두_번째_실행의_지적으로_실패시킨다(self):
        """고친 문장 목록에만 갇힌 수정은 다른 두 문서를 남겨 두 번째 실행이 그 파일을 짚는다."""
        # given
        self.prepare("T132")
        self.review()
        setup = self.repo / "docs/setup.md"
        setup.write_text(setup.read_text(encoding="utf-8").replace("is 5.", "is 3."), encoding="utf-8")
        self.review()
        # when
        outcome = self.grade(DONE_REPORT)
        # then
        self.assertFalse(outcome["second-run-clean"])
        self.assertFalse(outcome["all-files-state-the-decision"])


if __name__ == "__main__":
    unittest.main()
