"""Unit tests for the T37 evaluation task: its hidden checks, its reference solution, and its seeded handoff items."""

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

SEEDED = {"T02": 3, "T05": 1, "T37": 3}
HIDDEN_CHECKS = {"hidden-exit-code", "hidden-empty-output", "hidden-old-file", "hidden-import"}


def make_view(delegations: tuple[dict[str, Any], ...] = ()) -> dict[str, Any]:
    return {"final_answer": "done", "assistant_texts": [], "tool_calls": [], "delegations": list(delegations),
            "approvals": [], "permission_denials": []}


def apply_reference(repo: Path) -> None:
    script = TASKS_ROOT / "reference" / "T37" / "apply.py"
    env = {**os.environ, "PYTHONPATH": str(TASKS_ROOT / "reference"), "PYTHONDONTWRITEBYTECODE": "1"}
    subprocess.run([sys.executable, "-B", str(script), str(repo)], cwd=repo, env=env, check=True, capture_output=True, text=True)


class T37TaskTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.task = json.loads((TASKS_ROOT / "T37.json").read_text(encoding="utf-8"))
        self.repo = self.root / "repo"
        self.base = graders.materialize_fixture(self.task, FIXTURES_ROOT, TASKS_ROOT, self.repo)

    def grade(self, view: dict[str, Any] | None = None) -> dict[str, Any]:
        return graders.grade_run(self.task, self.repo, self.base, view or make_view(), TASKS_ROOT, self.root / "work")

    def outcome(self, result: dict[str, Any]) -> dict[str, bool]:
        return {check["id"]: check["passed"] for check in result["checks"]}

    def edit_reference_cli(self, old: str, new: str) -> None:
        path = self.repo / "notes_cli" / "cli.py"
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.count(old), 1)
        path.write_text(text.replace(old, new), encoding="utf-8")

    def test_정의는_프롬프트_숨은_테스트_참조_해법과_사용자_지정_검사를_모두_갖는다(self):
        """T37은 프롬프트, 픽스처, 숨은 테스트, 참조 해법, 사용자 지정 검사 함수가 실제로 있고 검사 종류가 유효하다."""
        # given / when
        custom = (TASKS_ROOT / "custom" / "T37.py").read_text(encoding="utf-8")
        missing = [name for name, found in {
            "prompt": (TASKS_ROOT / self.task["prompt_file"]).is_file(),
            "fixture": (FIXTURES_ROOT / self.task["fixture"]).is_dir(),
            "hidden": (TASKS_ROOT / self.task["hidden_tests"]["source"]).is_dir(),
            "reference": (TASKS_ROOT / "reference" / "T37" / "apply.py").is_file(),
        }.items() if not found]
        unknown = [check["kind"] for check in self.task["checks"] if check["kind"] not in graders.CHECKS]
        functions = [check["function"] for check in self.task["checks"] if check["kind"] == "custom"]

        # then
        self.assertEqual((missing, unknown), ([], []))
        self.assertTrue(all(f"def {name}(" in custom for name in functions))

    def test_수정하지_않은_저장소는_숨은_검사_넷에서_실패하고_기존_테스트는_통과한다(self):
        """아무것도 하지 않으면 네 숨은 검사가 실패하고 regressions는 통과한다."""
        # given / when
        result = self.grade()

        # then
        outcome = self.outcome(result)
        self.assertFalse(result["success"])
        self.assertEqual({name for name in HIDDEN_CHECKS if not outcome[name]}, HIDDEN_CHECKS)
        self.assertTrue(outcome["regressions"])

    def test_참조_해법은_필수_검사를_모두_통과하고_세_개_이상의_파일을_바꾼다(self):
        """참조 해법은 success이고 정확도 1.0이며 바뀐 파일이 세 개 이상이다."""
        # given
        apply_reference(self.repo)

        # when
        result = self.grade()

        # then
        failed = [(check["id"], check["detail"]) for check in result["checks"] if not check["passed"]]
        self.assertEqual(failed, [])
        self.assertTrue(result["success"])
        self.assertEqual(result["correctness"], 1.0)

    def test_없는_입력_파일에서_종료_코드를_3이_아니게_두면_종료_코드_검사가_실패한다(self):
        """실패 조건을 무시해 종료 코드를 1로 하면 hidden-exit-code가 실패하고 나머지 숨은 검사는 통과한다."""
        # given
        apply_reference(self.repo)
        self.edit_reference_cli("EXIT_IMPORT_SOURCE_MISSING = 3", "EXIT_IMPORT_SOURCE_MISSING = 1")

        # when
        outcome = self.outcome(self.grade())

        # then
        self.assertEqual({name for name in HIDDEN_CHECKS if not outcome[name]}, {"hidden-exit-code"})

    def test_없는_입력_파일에서_오류를_출력하면_빈_출력_검사가_실패한다(self):
        """종료 코드는 3이어도 stderr에 이유를 찍으면 hidden-empty-output만 실패한다."""
        # given
        apply_reference(self.repo)
        self.edit_reference_cli("    except ImportSourceMissing:\n        return",
                                "    except ImportSourceMissing as exc:\n        print(f\"error: {exc}\", file=err)\n        return")

        # when
        outcome = self.outcome(self.grade())

        # then
        self.assertEqual({name for name in HIDDEN_CHECKS if not outcome[name]}, {"hidden-empty-output"})

    def test_이전_버전이_쓴_리스트_파일을_못_읽으면_옛_파일_검사가_실패한다(self):
        """저장 파일을 새 형식만 읽게 하면 hidden-old-file만 실패한다."""
        # given
        apply_reference(self.repo)
        path = self.repo / "notes_cli" / "storage.py"
        text = path.read_text(encoding="utf-8")
        old = "    if isinstance(raw, dict):\n        raw = raw.get(\"memos\", [])\n"
        self.assertEqual(text.count(old), 1)
        path.write_text(text.replace(old, "    raw = raw[\"memos\"]\n"), encoding="utf-8")

        # when
        outcome = self.outcome(self.grade())

        # then
        self.assertEqual({name for name in HIDDEN_CHECKS if not outcome[name]}, {"hidden-old-file", "hidden-import"})

    def test_시드_항목은_식별자_분야_표식_매핑_검사를_갖고_매핑_검사는_실제로_있다(self):
        """T02, T05, T37의 시드 항목은 분야와 표식과 존재하는 검사 ID를 갖는다."""
        for task_id, count in SEEDED.items():
            with self.subTest(task_id):
                # given
                task = json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))
                checks = {check["id"] for check in task["checks"]}

                # when
                items = task["constraints"]

                # then
                self.assertEqual(len(items), count)
                self.assertTrue(all(item["field"] in ("constraints", "failure") and item["keywords"] and item["check_ids"]
                                    and set(item["check_ids"]) <= checks for item in items))
                self.assertTrue(set(task["handoff"]["pass_checks"]) <= checks)

    def test_T37의_실패_조건과_호환_결정은_프롬프트에만_있고_각각_다른_분야다(self):
        """exit code 3과 빈 출력은 failure, 이전 파일 호환은 constraints이며 어느 것도 저장소 문서에는 없다."""
        # given
        fields = {item["id"]: item["field"] for item in self.task["constraints"]}
        fixture_text = "\n".join(path.read_text(encoding="utf-8", errors="replace")
                                 for path in (FIXTURES_ROOT / "notes-cli").rglob("*") if path.is_file())

        # then
        self.assertEqual(fields, {"missing-input-exit-code": "failure", "missing-input-silent": "failure",
                                  "old-file-compat": "constraints"})
        self.assertNotIn("code 3", fixture_text)
        self.assertNotIn("legacy", fixture_text.lower())

    def test_위임_프롬프트가_exit_code_3을_말하면_종료_코드_항목은_누락이_아니다(self):
        """기존 인계 손실 평가에서 'exit code 3'이 있는 위임은 누락이 아니고 없는 위임은 누락이다."""
        # given
        kept = {"kind": "agent", "type": "demo", "class": "implementation", "prompt": "On a missing file exit code 3", "exit": None,
                "tool_use_id": "w1", "order": 0}
        lost = {**kept, "prompt": "add memo import", "tool_use_id": "w2"}

        # when
        result = graders.evaluate_constraints(self.task, make_view((kept, lost)), [
            {"id": "hidden-exit-code", "passed": False}])

        # then
        by_id = {item["id"]: item for item in result}
        self.assertEqual(by_id["missing-input-exit-code"]["missing_in"], ["w2"])
        self.assertEqual(by_id["missing-input-exit-code"]["traced_failures"], ["hidden-exit-code"])


if __name__ == "__main__":
    unittest.main()
