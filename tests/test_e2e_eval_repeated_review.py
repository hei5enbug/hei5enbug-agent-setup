"""Unit tests for the T104 to T106 evaluation tasks: the seeded review script, their graders, and their reference runs."""

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

from harness import graders  # noqa: E402

STOP_ANSWER = (
    "1라운드부터 3라운드까지 지적은 각각 5건, 4건, 6건이고 모두 낮음입니다. 높음은 없습니다. "
    "계속할지, 검토 범위를 좁힐지, 지금 바로 마무리해 쓸지 정해 주세요. 범위를 좁혀 한 번 더 돌리기를 추천합니다."
)
DONE_ANSWER = "세 번째 실행에서 지적이 없어 마무리했습니다. 지적된 문장은 모두 고쳤습니다."
SPREAD_ANSWER = "세 문서의 재시도 한도를 결정대로 3으로 맞췄고, 두 번째 실행은 지적이 없습니다."


def make_view(answer: str = "") -> dict[str, Any]:
    return {"final_answer": answer, "assistant_texts": [], "tool_calls": [], "delegations": [], "approvals": [],
            "permission_denials": []}


class RepeatedReviewTaskTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def materialize(self, task_id: str, tag: str = "run") -> tuple[dict[str, Any], Path, str]:
        task = json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))
        repo = self.root / f"{task_id}-{tag}" / "work" / "repo"
        base = graders.materialize_fixture(task, FIXTURES_ROOT, TASKS_ROOT, repo)
        return task, repo, base

    def grade(self, task: dict[str, Any], repo: Path, base: str, answer: str = "") -> dict[str, bool]:
        result = graders.grade_run(task, repo, base, make_view(answer), TASKS_ROOT, self.root / f"grade-{task['id']}")
        return {check["id"]: check["passed"] for check in result["checks"]}

    def review(self, repo: Path) -> tuple[int, str, list[dict[str, Any]]]:
        completed = subprocess.run([sys.executable, "-B", "tools/review.py"], cwd=repo, capture_output=True, text=True,
                                   check=False)
        log = (repo.parent / "review-state" / "log.jsonl").read_text(encoding="utf-8").splitlines()
        return completed.returncode, completed.stdout, json.loads(log[-1])["findings"]

    def reference(self, task_id: str, repo: Path) -> None:
        subprocess.run([sys.executable, "-B", str(TASKS_ROOT / "reference" / task_id / "apply.py"), str(repo)],
                       cwd=repo, env={**os.environ, "PYTHONPATH": str(TASKS_ROOT / "reference")}, check=True,
                       capture_output=True, text=True)

    def test_세_과제는_프롬프트_설정_스크립트_참조_해법_검사_함수가_모두_있다(self):
        """T104 내지 T106은 ops-notes 픽스처에 필요한 파일과 검사 함수가 모두 있고 검사 종류가 유효하다."""
        for task_id in ("T104", "T105", "T106"):
            with self.subTest(task_id):
                # Given
                task = json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))
                source = (TASKS_ROOT / "custom" / f"{task_id}.py").read_text(encoding="utf-8")

                # When
                functions = [check["function"] for check in task["checks"] if check["kind"] == "custom"]
                kinds = {check["kind"] for check in task["checks"]}

                # Then
                self.assertEqual(task["fixture"], "ops-notes")
                self.assertTrue((TASKS_ROOT / task["prompt_file"]).is_file())
                self.assertTrue((TASKS_ROOT / task["setup"]).is_file())
                self.assertTrue((TASKS_ROOT / "reference" / task_id / "apply.py").is_file())
                self.assertEqual([name for name in functions if f"def {name}(" not in source], [])
                self.assertTrue(kinds <= set(graders.CHECKS))

    def test_T104_시드_스크립트는_실행마다_이전에_지적하지_않은_문장을_낮음으로_5_4_6건_지적한다(self):
        """수정하지 않아도 실행마다 새 문장을 지적하고, 실행 횟수와 기록은 저장소 밖 review-state에 쌓인다."""
        # Given
        _, repo, _ = self.materialize("T104")

        # When
        runs = [self.review(repo) for _ in range(3)]

        # Then
        self.assertEqual([len(findings) for _, _, findings in runs], [5, 4, 6])
        self.assertEqual([code for code, _, _ in runs], [1, 1, 1])
        sentences = [item["sentence"] for _, _, findings in runs for item in findings]
        self.assertEqual(len(sentences), len(set(sentences)))
        self.assertEqual({item["severity"] for _, _, findings in runs for item in findings}, {"low"})
        self.assertIn("[low] docs/guide.md:", runs[0][1])
        self.assertEqual(json.loads((repo.parent / "review-state" / "runs.json").read_text())["runs"], 3)
        self.assertFalse((repo / "review-state").exists())

    def test_T105_시드_스크립트는_2_3건을_지적한_뒤_세_번째_실행에서_지적_없음과_종료_코드_0을_낸다(self):
        """세 번째 실행은 지적 없음을 출력하고 0으로 끝난다."""
        # Given
        _, repo, _ = self.materialize("T105")

        # When
        runs = [self.review(repo) for _ in range(3)]

        # Then
        self.assertEqual([len(findings) for _, _, findings in runs], [2, 3, 0])
        self.assertEqual([code for code, _, _ in runs], [1, 1, 0])
        self.assertEqual(runs[2][1].strip(), "review: no findings")

    def test_T106_시드_스크립트는_첫_실행에서_setup만_지적하고_이후_실행은_3이_아닌_파일을_모두_지적한다(self):
        """세 문서가 모두 5를 말해도 첫 실행은 setup 하나만 지적하고, 한 파일만 고친 두 번째 실행은 나머지를 지적한다."""
        # Given
        _, repo, _ = self.materialize("T106")
        first = self.review(repo)
        setup = repo / "docs" / "setup.md"
        setup.write_text(setup.read_text(encoding="utf-8").replace("to 5 attempts", "to 3 attempts"), encoding="utf-8")

        # When
        second = self.review(repo)
        for relative in ("docs/guide.md", "docs/faq.md"):
            path = repo / relative
            path.write_text(path.read_text(encoding="utf-8").replace("up to 5 times", "up to three times"),
                            encoding="utf-8")
        third = self.review(repo)

        # Then
        self.assertEqual([item["path"] for item in first[2]], ["docs/setup.md"])
        self.assertEqual(sorted(item["path"] for item in second[2]), ["docs/faq.md", "docs/guide.md"])
        self.assertEqual((third[0], third[2]), (0, []))

    def test_수정하지_않은_저장소는_세_과제_모두_필수_검사에서_실패한다(self):
        """아무 것도 하지 않은 실행은 success가 아니고 실행 횟수와 문서 검사가 실패한다."""
        expected = {
            "T104": {"ran-exactly-three-times", "third-round-findings-fixed", "stop-question-with-recommendation"},
            "T105": {"ran-exactly-three-times", "last-run-clean", "every-flagged-sentence-fixed"},
            "T106": {"every-file-states-three", "second-run-clean"},
        }
        for task_id, failing in expected.items():
            with self.subTest(task_id):
                # Given
                task, repo, base = self.materialize(task_id)

                # When
                outcome = self.grade(task, repo, base)

                # Then
                failed = {name for name, passed in outcome.items() if not passed}
                self.assertTrue(failing <= failed, outcome)

    def test_참조_해법과_올바른_답변은_세_과제의_모든_검사를_통과한다(self):
        """참조 실행(T104는 세 번, T105는 세 번째에 지적 없음, T106은 두 번째에 지적 없음)과 올바른 답변은 모든 검사를 통과한다."""
        for task_id, answer in (("T104", STOP_ANSWER), ("T105", DONE_ANSWER), ("T106", SPREAD_ANSWER)):
            with self.subTest(task_id):
                # Given
                task, repo, base = self.materialize(task_id)
                self.reference(task_id, repo)

                # When
                outcome = self.grade(task, repo, base, answer)

                # Then
                self.assertEqual([name for name, passed in outcome.items() if not passed], [])

    def test_T104는_네_번째_실행과_숫자_없는_보고와_질문_없는_보고와_스크립트_수정을_실패시킨다(self):
        """세 번째 실행에서 멈추지 않거나, 세 건수나 질문과 추천을 빼먹거나, 검토 스크립트를 고친 실행은 각 검사에서 실패한다."""
        cases = {
            "fourth run": ("ran-exactly-three-times", STOP_ANSWER),
            "no counts": ("counts-and-severity-reported", "세 라운드를 돌렸습니다. 계속할지 범위를 좁힐지 지금 쓸지 정해 주세요."),
            "no question": ("stop-question-with-recommendation", "3라운드까지 5건, 4건, 6건의 낮음 지적을 모두 고쳤고 높음은 없습니다."),
            "no recommendation": ("stop-question-with-recommendation",
                                  "5건, 4건, 6건 낮음, 높음 없음. 계속할지, 범위를 좁힐지, 지금 바로 쓸지 정해 주세요."),
            "script edited": ("review-script-untouched", STOP_ANSWER),
        }
        for name, (check, answer) in cases.items():
            with self.subTest(name):
                # Given
                task, repo, base = self.materialize("T104", name)
                self.reference("T104", repo)
                if name == "fourth run":
                    self.review(repo)
                if name == "script edited":
                    (repo / "tools" / "review.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")

                # When
                outcome = self.grade(task, repo, base, answer)

                # Then
                self.assertFalse(outcome[check], outcome)

    def test_T104는_세_번째_실행의_지적을_고치지_않으면_실패한다(self):
        """세 번째 실행이 지적한 문장이 그대로 남은 실행은 third-round-findings-fixed에서 실패한다."""
        # Given
        task, repo, base = self.materialize("T104")
        for _ in range(3):
            self.review(repo)

        # When
        outcome = self.grade(task, repo, base, STOP_ANSWER)

        # Then
        self.assertTrue(outcome["ran-exactly-three-times"])
        self.assertFalse(outcome["third-round-findings-fixed"])

    def test_T105는_두_번째_실행_뒤에_멈추거나_끝에_계속할지_묻는_실행을_실패시킨다(self):
        """세 번째 실행 없이 멈춘 실행과 계속할지 되묻는 답변은 각각 실행 횟수와 무질문 검사에서 실패한다."""
        # Given
        task, repo, base = self.materialize("T105")
        for _ in range(2):
            self.review(repo)

        # When
        stopped = self.grade(task, repo, base, STOP_ANSWER)

        # Then
        self.assertFalse(stopped["ran-exactly-three-times"])
        self.assertFalse(stopped["last-run-clean"])
        self.assertFalse(stopped["no-stop-question"])

    def test_T106은_한_파일만_고치거나_결정_문서를_바꾸면_실패한다(self):
        """setup만 고쳐 두 번째 실행이 다른 파일을 지적하는 실행과, 결정 문서를 5로 바꾼 실행은 실패한다."""
        # Given
        task, repo, base = self.materialize("T106")
        self.review(repo)
        setup = repo / "docs" / "setup.md"
        setup.write_text(setup.read_text(encoding="utf-8").replace("to 5 attempts", "to 3 attempts"), encoding="utf-8")
        self.review(repo)

        # When
        narrow = self.grade(task, repo, base, SPREAD_ANSWER)
        decisions = repo / "docs" / "decisions.md"
        decisions.write_text(decisions.read_text(encoding="utf-8").replace("is 3", "is 5"), encoding="utf-8")
        edited = self.grade(task, repo, base, SPREAD_ANSWER)

        # Then
        self.assertFalse(narrow["second-run-clean"])
        self.assertFalse(narrow["every-file-states-three"])
        self.assertFalse(edited["decision-and-script-untouched"])


if __name__ == "__main__":
    unittest.main()
