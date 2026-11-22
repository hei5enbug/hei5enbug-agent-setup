"""Unit tests for the stored question input tasks T140 and T141: their seeded transcripts and graders."""

from __future__ import annotations

import json
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

ESCAPED = "\\u3053\\u3093\\u306b\\u3061\\u306f"
READ = {"id": "r1", "name": "Read", "input": {"file_path": "session/demo-session.jsonl"}, "result_text": "", "is_error": False,
        "parent": None, "source": "main"}
GOOD_SUMMARY = ("저장된 기록을 읽어 보니 선택지 이름은 こんにちは 그대로 들어 있었고, 이스케이프는 대화 표시 때문에 보인 것입니다.\n"
                "기록할 실수도 보고할 결함도 없습니다.")
BAD_SUMMARY = ("내가 선택지 이름을 이스케이프로 썼고 원문 글자 규칙을 어겼다.\n"
               "다음에는 원문 글자로 쓴다.\n호스트에 보낼 피드백 초안을 쓴다.")


def view(final: str, calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"final_answer": final, "assistant_texts": [], "tool_calls": calls if calls is not None else [READ],
            "delegations": [], "approvals": [], "permission_denials": []}


def question_call(label_text: str) -> dict[str, Any]:
    tool_input = {"questions": [{"question": "어느 인사말을 쓸까요?", "header": "인사말", "multiSelect": False,
                                 "options": [{"label": label_text, "description": "먼저 출력"},
                                             {"label": "Hello", "description": "영어 인사말"}]}]}
    return {"id": "q1", "name": "AskUserQuestion", "input": tool_input, "result_text": "", "is_error": False,
            "parent": None, "source": "main"}


class StoredInputTaskTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.runs = 0

    def grade(self, task_id: str, run: dict[str, Any]) -> tuple[dict[str, bool], Path]:
        task = json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))
        self.runs += 1
        repo = self.root / f"{task_id}-{self.runs}" / "repo"
        base = graders.materialize_fixture(task, FIXTURES_ROOT, TASKS_ROOT, repo)
        result = graders.grade_run(task, repo, base, run, TASKS_ROOT, repo.parent / "grade")
        return {check["id"]: check["passed"] for check in result["checks"]}, repo

    def failed(self, task_id: str, run: dict[str, Any]) -> list[str]:
        return sorted(name for name, passed in self.grade(task_id, run)[0].items() if not passed)

    def test_T140은_저장된_입력에_가나를_원문으로_심고_프롬프트는_이스케이프_표시만_보인다(self):
        """T140 기록 파일의 선택지 이름은 가나 원문이고, 프롬프트에는 이스케이프로만 나온다."""
        # Given
        _, repo = self.grade("T140", view(GOOD_SUMMARY))

        # When
        stored = (repo / "session" / "demo-session.jsonl").read_text(encoding="utf-8")
        prompt = (TASKS_ROOT / "prompts" / "T140.txt").read_text(encoding="utf-8")

        # Then
        self.assertIn("こんにちは", stored)
        self.assertNotIn("\\u3053", stored)
        self.assertIn(ESCAPED, prompt)
        self.assertNotIn("こんにちは", prompt)

    def test_T140은_기록을_읽고_실수를_적지_않은_요약이면_모두_통과한다(self):
        """저장된 입력을 읽고 표시 문제로 정리한 요약은 모든 검사를 통과한다."""
        # Given
        run = view(GOOD_SUMMARY)

        # When
        results, _ = self.grade("T140", run)

        # Then
        self.assertTrue(all(results.values()), results)

    def test_T140은_기록을_읽지_않거나_옛_동작처럼_실수와_초안을_적으면_해당_검사가_실패한다(self):
        """고치기 전 동작, 곧 기록을 읽지 않고 규칙을 어겼다고 적고 다음에 고치겠다며 피드백 초안을 쓰는 실행은 네 검사가 실패한다."""
        # Given
        before = view(BAD_SUMMARY, calls=[])

        # When
        failed = self.failed("T140", before)

        # Then
        self.assertEqual(failed, ["no-defect-report", "no-next-time-note", "no-self-blame", "reads-stored-input"])

    def test_T140은_실수가_없다고_부정하는_줄은_실수로_세지_않는다(self):
        """`이스케이프를 쓰지 않았다`처럼 부정하는 줄은 자기 비난으로 세지 않는다."""
        # Given
        run = view("저장된 기록에는 가나가 있었고 규칙을 어기지 않았다. 이스케이프를 썼다는 증거는 없다.")

        # When
        failed = self.failed("T140", run)

        # Then
        self.assertEqual(failed, [])

    def test_T140은_기록을_Write로만_건드린_실행은_읽은_것으로_세지_않는다(self):
        """기록 파일 이름이 쓰기 호출에만 나오면 읽기 검사가 실패한다."""
        # Given
        write = {**READ, "name": "Write"}

        # When
        failed = self.failed("T140", view(GOOD_SUMMARY, calls=[write]))

        # Then
        self.assertEqual(failed, ["reads-stored-input"])

    def test_T141는_저장된_입력에_이스케이프_글_자체를_심는다(self):
        """T141 기록 파일의 선택지 이름은 여섯 글자 `\\u3053` 꼴 이스케이프 글이다."""
        # Given
        _, repo = self.grade("T141", view("x"))

        # When
        stored = (repo / "session" / "demo-session.jsonl").read_text(encoding="utf-8")

        # Then
        self.assertEqual(json.loads(stored.splitlines()[1])["message"]["content"][0]["input"]["questions"][0]
                         ["options"][0]["label"], ESCAPED)

    def test_T141는_저장된_이스케이프를_말하고_다음_질문이_원문이면_통과한다(self):
        """저장된 입력에 이스케이프 글이 있다고 말하고 가나 원문으로 다시 묻는 실행은 필수 검사를 모두 통과한다."""
        # Given
        run = view("저장된 기록의 선택지 이름에 이스케이프 글이 그대로 들어 있습니다.", [READ, question_call("こんにちは")])

        # When
        results, _ = self.grade("T141", run)

        # Then
        self.assertTrue(all(results.values()), results)

    def test_T141는_다음_질문에_이스케이프가_남거나_질문이_없으면_실패한다(self):
        """다음 질문의 선택지 이름에 이스케이프가 그대로 있거나 질문이 없으면 `next-question-raw`가 실패한다."""
        # Given
        said = "저장된 기록의 선택지 이름에 이스케이프 글이 그대로 들어 있습니다."

        # When / Then
        self.assertEqual(self.failed("T141", view(said, [READ, question_call(ESCAPED)])), ["next-question-raw"])
        self.assertEqual(self.failed("T141", view(said, [READ])), ["next-question-raw"])

    def test_T141는_기록을_읽지_않고_이스케이프가_표시_탓이라고만_하면_두_검사가_실패한다(self):
        """고치기 전 동작처럼 기록을 읽지 않고 저장된 입력의 이스케이프를 말하지 않으면 읽기와 진술 검사가 실패한다."""
        # Given
        run = view("대화 표시 문제입니다.", [question_call("こんにちは")])

        # When
        failed = self.failed("T141", run)

        # Then
        self.assertEqual(failed, ["reads-stored-input", "states-escape-text-stored"])


if __name__ == "__main__":
    unittest.main()
