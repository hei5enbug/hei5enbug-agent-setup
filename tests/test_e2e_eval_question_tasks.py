"""Unit tests for the question dialog evaluation tasks T76 and T77: their seeded files, graders, and Codex call mapping."""

from __future__ import annotations

import copy
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

from harness import codex_calls, graders  # noqa: E402

CHECKLIST_PREVIEW = (
    "demo-tool 체크리스트\n"
    " 1  weekly.csv에 day,count 헤더와 일별 한 행을 쓴다\n"
    " 2  파일의 첫 줄은 헤더 행이다  -> 지움\n"
    " 3  두 번 실행해도 같은 파일이다\n"
    " 4  빈 칸이 아니라 0을 보인다\n"
    " 5  두 번 실행해도 사본이 생기지 않는다  -> 지움"
)
GOOD_CLAUDE = {"questions": [{
    "header": "체크리스트",
    "question": "demo-tool 이슈 초안의 체크리스트에서 다른 줄과 겹치는 두 줄을 지울까요? "
                "A: 파일의 첫 줄은 헤더 행이다 (1번이 이미 헤더를 말함), B: 두 번 실행해도 사본이 생기지 않는다 "
                "(3번이 이미 같은 파일을 말함)",
    "multiSelect": False,
    "options": [
        {"label": "A와 B 삭제 (Recommended)", "description": "첫 줄 문장과 사본 문장을 지우고 세 줄만 남깁니다.",
         "preview": CHECKLIST_PREVIEW},
        {"label": "그대로 유지", "description": "첫 줄 문장과 사본 문장을 모두 남기고 다섯 줄을 유지합니다."},
    ],
}]}
TABLE = ("+-------------+------------+\n| legacy_code | old_status |\n+-------------+------------+")
GOOD_CODEX = {"questions": [{
    "id": "drop_columns", "header": "열 삭제",
    "question": f"demo.orders 테이블에서 안 쓰는 두 열을 지울까요?\n{TABLE}",
    "options": [
        {"label": "두 열 삭제 (Recommended)", "description": "legacy_code와 old_status를 지우고 나머지 열을 남깁니다."},
        {"label": "그대로 둠", "description": "legacy_code와 old_status를 모두 남깁니다."},
    ],
}]}


def view_with(tool: str, tool_input: Any, result: str = "") -> dict[str, Any]:
    call = {"id": "q1", "name": tool, "input": tool_input, "result_text": result, "is_error": False, "parent": None,
            "source": "main"}
    return {"final_answer": "", "assistant_texts": [], "tool_calls": [call], "delegations": [], "approvals": [],
            "permission_denials": []}


class QuestionTaskTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.runs = 0

    def repo_of(self, task_id: str) -> Path:
        return self.root / f"{task_id}-{self.runs}" / "repo"

    def grade(self, task_id: str, view: dict[str, Any]) -> dict[str, bool]:
        task = json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))
        self.runs += 1
        repo = self.repo_of(task_id)
        base = graders.materialize_fixture(task, FIXTURES_ROOT, TASKS_ROOT, repo)
        result = graders.grade_run(task, repo, base, view, TASKS_ROOT, repo.parent / "grade")
        return {check["id"]: check["passed"] for check in result["checks"]}

    def failed(self, task_id: str, view: dict[str, Any]) -> list[str]:
        return sorted(name for name, passed in self.grade(task_id, view).items() if not passed)

    def test_과제_정의는_프롬프트_설정_검사_함수가_모두_있고_프롬프트에_금지어가_없다(self):
        """T76과 T77의 프롬프트, 설정 스크립트, 검사 함수가 있고 프롬프트와 심은 파일에 `acceptance criteria`, `regression`, `criterion`이 없다."""
        # Given
        banned = ("acceptance criteria", "regression", "criterion", "reviewer")

        # When / Then
        for task_id in ("T76", "T77"):
            task = json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))
            source = (TASKS_ROOT / "custom" / f"{task_id}.py").read_text(encoding="utf-8")
            texts = [(TASKS_ROOT / task["prompt_file"]).read_text(encoding="utf-8"),
                     (TASKS_ROOT / task["setup"]).read_text(encoding="utf-8")]
            with self.subTest(task=task_id):
                self.assertEqual([c["function"] for c in task["checks"] if c.get("function")
                                  and f"def {c['function']}(" not in source], [])
                self.assertEqual([word for word in banned for text in texts if word in text.lower()], [])

    def test_T76은_다섯_줄_체크리스트와_두_번_달린_의견을_심고_파일을_고치지_않으면_변경이_없다(self):
        """T76 설정은 다섯 줄 체크리스트와 의견 파일을 만들고, 좋은 질문을 낸 뒤 변경이 없으면 `files-untouched`가 통과한다."""
        # Given
        view = view_with("AskUserQuestion", GOOD_CLAUDE)

        # When
        results = self.grade("T76", view)
        draft = (self.repo_of("T76") / "drafts" / "demo-tool-issue.md").read_text(encoding="utf-8")

        # Then
        self.assertEqual(sum(line[:2] in {f"{n}." for n in range(1, 6)} for line in draft.splitlines()), 5)
        self.assertTrue(all(results.values()), results)

    def test_T76은_질문을_열지_않았으면_모든_검사가_실패한다(self):
        """질문 도구 호출이 없는 실행은 열림과 이름 짓기, 옵션, 그림 검사가 모두 실패한다."""
        # Given
        view = view_with("Bash", {"command": "ls"})

        # When
        failed = self.failed("T76", view)

        # Then
        self.assertEqual(failed, sorted(["dialog-opened", "names-both-flagged-lines",
                                         "delete-and-keep-options-name-both-lines", "diagram-shows-all-five-lines",
                                         "no-free-form-option"]))

    def test_T76은_금지어가_있거나_미리보기가_없거나_직접_입력_선택지가_있으면_해당_검사만_실패한다(self):
        """질문에 `acceptance criteria`나 `reviewer`가 들어가면, 미리보기를 빼면, `직접 입력`을 더하면 각각 그 검사만 실패한다."""
        # Given
        worded = copy.deepcopy(GOOD_CLAUDE)
        worded["questions"][0]["question"] += " (the reviewer flagged both as acceptance criteria)"
        plain = copy.deepcopy(GOOD_CLAUDE)
        del plain["questions"][0]["options"][0]["preview"]
        typed = copy.deepcopy(GOOD_CLAUDE)
        typed["questions"][0]["options"].append({"label": "직접 입력", "description": "직접 쓴다"})

        # When / Then
        self.assertEqual(self.failed("T76", view_with("AskUserQuestion", worded)), ["uses-no-internal-terms"])
        self.assertEqual(self.failed("T76", view_with("AskUserQuestion", plain)), ["diagram-shows-all-five-lines"])
        self.assertEqual(self.failed("T76", view_with("AskUserQuestion", typed)), ["no-free-form-option"])

    def test_T76은_선택지_설명이_번호만_쓰면_실패하고_질문이_준_이름표로_부르면_통과한다(self):
        """설명이 `2번과 5번`처럼 번호만 쓰면 실패하고, 질문이 `A`, `B`로 이름 붙인 줄을 `A와 B`로 부르면 통과한다."""
        # Given
        numbered = copy.deepcopy(GOOD_CLAUDE)
        for item, text in zip(numbered["questions"][0]["options"], ("2번과 5번을 지웁니다.", "2번과 5번을 남깁니다.")):
            item["description"] = text
        labelled = copy.deepcopy(GOOD_CLAUDE)
        for item, text in zip(labelled["questions"][0]["options"], ("A와 B를 지웁니다.", "A와 B를 남깁니다.")):
            item["description"] = text

        # When / Then
        self.assertEqual(self.failed("T76", view_with("AskUserQuestion", numbered)),
                         ["delete-and-keep-options-name-both-lines"])
        self.assertEqual(self.failed("T76", view_with("AskUserQuestion", labelled)), [])

    def test_T76은_질문_가드가_막은_호출은_세지_않고_다시_낸_질문으로_채점한다(self):
        """가드가 거부한 첫 호출은 건너뛰고 마지막으로 보여 준 대화상자로 채점한다."""
        # Given
        typed = copy.deepcopy(GOOD_CLAUDE)
        typed["questions"][0]["options"].append({"label": "Other", "description": "직접 쓴다"})
        view = view_with("AskUserQuestion", typed, result="Blocked: ... the host already adds its own free-form row ...")
        view["tool_calls"].append({**view["tool_calls"][0], "id": "q2", "input": GOOD_CLAUDE, "result_text": ""})

        # When / Then
        self.assertEqual(self.failed("T76", view), [])
        self.assertEqual(self.failed("T76", {**view, "tool_calls": view["tool_calls"][:1]}),
                         sorted(["dialog-opened", "names-both-flagged-lines",
                                 "delete-and-keep-options-name-both-lines", "diagram-shows-all-five-lines",
                                 "no-free-form-option"]))

    def test_T77은_두_열과_그림을_질문_문장_아래에_둔_질문을_통과시킨다(self):
        """Codex 모양의 입력이 두 열 이름, 선택지 설명, 질문 문장 아래의 표 그림을 모두 갖추면 모든 검사를 통과한다."""
        # Given
        view = view_with("request_user_input", GOOD_CODEX)

        # When
        results = self.grade("T77", view)

        # Then
        self.assertTrue(all(results.values()), results)
        self.assertIn("legacy_code", (self.repo_of("T77") / "db" / "demo_orders.sql").read_text(encoding="utf-8"))

    def test_T77은_그림이_없거나_설명이_열을_빼먹거나_직접_입력이_있으면_해당_검사만_실패한다(self):
        """그림 줄을 지우면, 설명에서 열 이름을 빼면, `기타` 선택지를 더하면 각각 그 검사만 실패한다."""
        # Given
        flat = copy.deepcopy(GOOD_CODEX)
        flat["questions"][0]["question"] = flat["questions"][0]["question"].splitlines()[0]
        short = copy.deepcopy(GOOD_CODEX)
        short["questions"][0]["options"][1]["description"] = "legacy_code를 남깁니다."
        typed = copy.deepcopy(GOOD_CODEX)
        typed["questions"][0]["options"].append(
            {"label": "기타", "description": "legacy_code와 old_status 중 직접 고른다"})
        bulleted = copy.deepcopy(GOOD_CODEX)
        bulleted["questions"][0]["question"] = "두 열을 지울까요?\n- legacy_code\n- old_status"

        # When / Then
        self.assertEqual(self.failed("T77", view_with("request_user_input", flat)), ["diagram-shows-columns"])
        self.assertEqual(self.failed("T77", view_with("request_user_input", short)), ["options-name-both-columns"])
        self.assertEqual(self.failed("T77", view_with("request_user_input", typed)), ["no-free-form-option"])
        self.assertEqual(self.failed("T77", view_with("request_user_input", bulleted)), ["diagram-shows-columns"])

    def test_Codex_rollout의_request_user_input_호출이_도구_호출로_보인다(self):
        """rollout의 `request_user_input` function_call은 이름과 파싱된 인자, 출력 글과 함께 도구 호출 하나가 된다."""
        # Given
        events = [
            {"type": "response_item", "payload": {"type": "function_call", "name": "request_user_input",
                                                   "call_id": "c1", "arguments": json.dumps(GOOD_CODEX)}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1",
                                                   "output": "{\"answers\": {}}"}},
        ]

        # When
        calls = codex_calls.rollout_tool_calls(events, "main", "rollout-main.jsonl")

        # Then
        self.assertEqual([(call["name"], call["input"], call["result_text"]) for call in calls],
                         [("request_user_input", GOOD_CODEX, "{\"answers\": {}}")])


if __name__ == "__main__":
    unittest.main()
