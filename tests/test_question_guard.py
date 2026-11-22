"""PreToolUse hook that denies a question dialog holding an option that asks the user to type an answer."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD = REPO_ROOT / "scripts/question_guard.py"
HOOKS = json.loads((REPO_ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
MATCHER = "^(AskUserQuestion|request_user_input)$"


def option(label: str, description: str = "설명") -> dict:
    return {"label": label, "description": description}


def claude_input(*labels: str) -> dict:
    return {"questions": [{"question": "삭제할까요?", "header": "삭제", "multiSelect": False,
                           "options": [option(label) for label in labels]}]}


def codex_input(*labels: str) -> dict:
    return {"questions": [{"id": "drop_columns", "header": "열 삭제", "question": "두 열을 지울까요?",
                           "options": [option(label) for label in labels]}]}


def call_two_input() -> dict:
    """A fictional copy of the second dialog of the 2026-11-13 session: two real options and one the user must type."""
    return {"questions": [{
        "question": "demo 이슈 초안의 완료 체크리스트(구현이 끝났는지 정하는 목록)에서 두 줄을 지울까요?",
        "header": "검토 반복",
        "multiSelect": False,
        "options": [
            {"label": "두 줄 삭제 (Recommended)", "description": "A와 B를 지웁니다.",
             "preview": "demo 체크리스트\n  A  지움\n  B  지움"},
            {"label": "그대로 둠", "description": "A와 B를 남깁니다."},
            {"label": "직접 입력", "description": "원하는 답을 직접 씁니다."},
        ],
    }]}


class QuestionGuardTest(unittest.TestCase):
    def run_guard(self, tool_name: str, tool_input, event_name: str = "PreToolUse") -> dict | None:
        env = {"PATH": os.environ.get("PATH", "")}
        event = {"hook_event_name": event_name, "tool_name": tool_name, "session_id": "demo", "tool_input": tool_input}
        result = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event), env=env, capture_output=True,
                                text=True, check=True)
        if not result.stdout.strip():
            return None
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        return output

    def assert_denied(self, tool_name: str, tool_input) -> None:
        output = self.run_guard(tool_name, tool_input)
        self.assertIsNotNone(output)
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("free-form row", output["permissionDecisionReason"])
        self.assertIn("Remove that option", output["permissionDecisionReason"])

    def test_직접_입력_Other_Custom_선택지가_있는_질문은_호스트의_자유_입력_줄을_말하며_막는다(self):
        """AskUserQuestion의 선택지 이름이 `직접 입력`, `Other`, `Custom (Recommended)`이면 이유에 자유 입력 줄과 지울 것을 적어 막는다."""
        # Given
        labels = ("직접 입력", "Other", "Custom (Recommended)")

        # When / Then
        for label in labels:
            with self.subTest(label=label):
                self.assert_denied("AskUserQuestion", claude_input("삭제", label))

    def test_2026_11_13_세션의_두_번째_질문을_본뜬_입력은_막고_직접_입력만_뺀_입력은_통과한다(self):
        """호출 2를 본뜬 가상 입력은 막히고, 같은 입력에서 `직접 입력` 선택지만 빼면 출력이 없다."""
        # Given
        original = call_two_input()
        fixed = call_two_input()
        fixed["questions"][0]["options"] = fixed["questions"][0]["options"][:2]

        # When / Then
        self.assert_denied("AskUserQuestion", original)
        self.assertIsNone(self.run_guard("AskUserQuestion", fixed))

    def test_정해진_목록의_모든_이름은_대소문자와_뒤_괄호_설명과_공백을_무시하고_막는다(self):
        """`type your own`, `기타`, `직접 작성`을 포함한 목록의 이름은 대소문자, 앞뒤 공백, 뒤쪽 괄호 설명과 상관없이 막힌다."""
        # Given
        labels = ("OTHER", " other ", "Type your own", "type your own answer", "기타", "직접 작성", "직접 입력 (추천)",
                  "Other (Recommended)", "Custom (Recommended) (x)", "other.")

        # When / Then
        for label in labels:
            with self.subTest(label=label):
                self.assert_denied("AskUserQuestion", claude_input("삭제", label))

    def test_다른_말을_함께_담은_이름은_통과한다(self):
        """`Other files`, `Customize layout`, `기타 파일 삭제`처럼 목록의 낱말을 포함만 한 이름은 통과한다."""
        # Given
        labels = ("Other files", "Customize layout", "기타 파일 삭제", "Custom (Recommended) files")

        # When / Then
        for label in labels:
            with self.subTest(label=label):
                self.assertIsNone(self.run_guard("AskUserQuestion", claude_input("삭제", label)))

    def test_여러_질문_중_하나에만_있어도_막고_여러_질문이_모두_깨끗하면_통과한다(self):
        """질문이 둘일 때 두 번째 질문의 선택지에만 `Other`가 있어도 막고, 둘 다 없으면 출력이 없다."""
        # Given
        dirty = {"questions": [*claude_input("삭제", "유지")["questions"], *claude_input("가", "Other")["questions"]]}
        clean = {"questions": [*claude_input("삭제", "유지")["questions"], *claude_input("가", "나")["questions"]]}

        # When / Then
        self.assert_denied("AskUserQuestion", dirty)
        self.assertIsNone(self.run_guard("AskUserQuestion", clean))

    def test_Codex_request_user_input_입력에도_같은_검사를_한다(self):
        """Codex `request_user_input` 입력의 `Other`는 막고, 직접 입력이 없는 입력은 출력이 없다."""
        # Given
        dirty = codex_input("두 열 삭제 (Recommended)", "Other")
        clean = codex_input("두 열 삭제 (Recommended)", "그대로 둠")

        # When / Then
        self.assert_denied("request_user_input", dirty)
        self.assertIsNone(self.run_guard("request_user_input", clean))

    def test_다른_도구와_다른_이벤트와_모양이_다른_입력은_출력이_없다(self):
        """다른 도구, `PostToolUse`, 질문이 없거나 모양이 다른 입력은 출력도 오류도 없다."""
        # Given
        shapes = (None, "text", [], {}, {"questions": "x"}, {"questions": [None, 3, {"options": "x"}]},
                  {"questions": [{"options": [None, "Other", {"label": 5}, {}]}]})

        # When / Then
        self.assertIsNone(self.run_guard("Bash", claude_input("Other")))
        self.assertIsNone(self.run_guard("AskUserQuestion", claude_input("Other"), event_name="PostToolUse"))
        for shape in shapes:
            with self.subTest(shape=shape):
                self.assertIsNone(self.run_guard("AskUserQuestion", shape))

    def test_깨진_입력은_출력도_오류도_없이_끝난다(self):
        """표준 입력이 JSON이 아니면 종료 코드 0과 빈 출력으로 끝난다."""
        # Given / When
        result = subprocess.run([sys.executable, str(GUARD)], input="not json", env={"PATH": os.environ.get("PATH", "")},
                                capture_output=True, text=True)

        # Then
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_훅은_공용_hooks_json의_PreToolUse에_두_도구_이름만_잡는_matcher로_등록되어_있다(self):
        """Claude와 Codex가 함께 읽는 hooks.json의 PreToolUse에 AskUserQuestion과 request_user_input만 잡는 matcher로 한 번 등록돼 있다."""
        # Given
        groups = [group for group in HOOKS["PreToolUse"]
                  if any("question_guard.py" in handler["command"] for handler in group["hooks"])]

        # When / Then
        self.assertEqual([group["matcher"] for group in groups], [MATCHER])
        self.assertEqual(groups[0]["hooks"][0]["timeout"], 5)


if __name__ == "__main__":
    unittest.main()
