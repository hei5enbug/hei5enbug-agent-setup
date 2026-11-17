"""Unit tests for the worker-model case set: its task files, fixtures, hidden checks, and reference solutions."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
TASKS_ROOT = E2E_ROOT / "tasks"
FIXTURES_ROOT = E2E_ROOT / "fixtures"
sys.path.insert(0, str(E2E_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from harness import campaign, graders, worker_cases  # noqa: E402
from harness.config import HarnessConfig  # noqa: E402
from test_e2e_eval_graders import apply_reference, make_view  # noqa: E402

CASE_IDS = [f"T{number}" for number in range(68, 78)]
REQUIRED = {"hidden-tests", "regressions"}


class WorkerCaseTasksTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)

    def load(self, task_id: str) -> dict:
        return json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))

    def materialize(self, task_id: str) -> tuple[dict, Path, str]:
        task = self.load(task_id)
        repo = self.root / f"repo-{task_id}"
        base = graders.materialize_fixture(task, FIXTURES_ROOT, TASKS_ROOT, repo)
        return task, repo, base

    def grade(self, task: dict, repo: Path, base: str) -> dict:
        return graders.grade_run(task, repo, base, make_view("done"), TASKS_ROOT, self.root / f"work-{task['id']}")

    def test_사례는_열_개_이하이고_다섯_기준을_모두_담으며_숨은_검사를_선언한다(self):
        """worker_case 과제가 열 개 이하이고 모두 숨은 필수 검사와 파일을 갖추며 다섯 기준을 하나 이상씩 담는다."""
        # given
        cases = worker_cases.load_cases(TASKS_ROOT)

        # when
        problems = worker_cases.case_problems(cases)

        # then
        self.assertEqual(problems, [])
        self.assertEqual(sorted(cases), CASE_IDS)
        for task_id in cases:
            with self.subTest(task_id):
                task = self.load(task_id)
                required = {check["id"] for check in task["checks"] if check["required"]}
                self.assertEqual(required, REQUIRED)
                self.assertTrue((TASKS_ROOT / task["prompt_file"]).is_file())
                self.assertTrue((FIXTURES_ROOT / task["fixture"]).is_dir())
                self.assertTrue(list((TASKS_ROOT / task["hidden_tests"]["source"]).glob("test_*.py")))
                self.assertTrue((TASKS_ROOT / "reference" / task_id / "apply.py").is_file())

    def test_수정하지_않은_저장소는_숨은_검사에서_실패하고_기존_테스트는_통과한다(self):
        """아무것도 하지 않으면 hidden-tests가 실패하고 regressions는 통과해 사례가 기존 동작 위에서 시작한다."""
        for task_id in CASE_IDS:
            with self.subTest(task_id):
                # given
                task, repo, base = self.materialize(task_id)

                # when
                result = self.grade(task, repo, base)

                # then
                outcome = {check["id"]: check["passed"] for check in result["checks"]}
                self.assertEqual(outcome, {"hidden-tests": False, "regressions": True})
                self.assertFalse(result["success"])

    def test_참조_해법은_숨은_검사와_기존_테스트를_모두_통과한다(self):
        """참조 해법을 적용하면 모든 필수 검사가 통과해 숨은 검사가 해법을 막지 않는다."""
        for task_id in CASE_IDS:
            with self.subTest(task_id):
                # given
                task, repo, base = self.materialize(task_id)
                apply_reference(task_id, repo)

                # when
                result = self.grade(task, repo, base)

                # then
                failed = [(check["id"], check["detail"]) for check in result["checks"] if not check["passed"]]
                self.assertEqual(failed, [])
                self.assertTrue(result["success"])

    def test_기본_캠페인은_사례를_고르지_않고_이름을_주면_실행_계획에_들어간다(self):
        """--tasks 없이 고른 과제 목록에는 worker_case가 없고, 기존 골든 과제는 그대로 남는다."""
        # given
        cfg = HarnessConfig(run_root=self.root / "runs", tasks_root=TASKS_ROOT)

        # when
        discovered = campaign.discover_tasks(cfg)

        # then
        self.assertTrue(set(CASE_IDS).isdisjoint(discovered))
        self.assertIn("T21", discovered)
        self.assertIn("T01", discovered)

    def test_측정_변종은_같은_조건에서_모델만_다르고_작업자_역할로_시작한다(self):
        """두 변종은 같은 플러그인 ref와 env를 쓰고 Claude 모델만 다르며 세션을 할당된 worker로 시작한다."""
        # given
        variants = {name: json.loads((E2E_ROOT / "variants" / f"{name}.json").read_text(encoding="utf-8"))
                    for name in ("worker-sonnet", "worker-opus")}

        # when
        models = {name: variant["models"]["claude"] for name, variant in variants.items()}

        # then
        self.assertEqual(models, {"worker-sonnet": "claude-sonnet-5-5", "worker-opus": "claude-opus-5-5"})
        first, second = variants.values()
        self.assertEqual((first["ref"], first["env"], first["settings"], first["extra_args"]),
                         (second["ref"], second["env"], second["settings"], second["extra_args"]))
        self.assertEqual(first["env"]["HEI5ENBUG_ASSIGNED_ROLE"], "worker")


if __name__ == "__main__":
    unittest.main()
