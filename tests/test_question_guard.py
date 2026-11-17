"""PreToolUse hook that denies a question dialog whose options include a self-made free-form option."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "question_guard.py"


def run_hook(tool_name: str, labels: list[str], extra_question: dict | None = None):
    options = [{"label": label, "description": f"{label}을 고른다"} for label in labels]
    questions = [{"question": "demo-tool 이슈 초안에서 겹치는 두 줄을 지울까요?", "header": "겹치는 줄",
                  "options": options, "multiSelect": False}]
    if extra_question:
        questions.append(extra_question)
    event = {"hook_event_name": "PreToolUse", "tool_name": tool_name, "tool_input": {"questions": questions}}
    return subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(event), capture_output=True, text=True,
                          check=False)


def reason_of(result: subprocess.CompletedProcess[str]) -> str | None:
    if not result.stdout:
        return None
    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse" and output["permissionDecision"] == "deny"
    return output["permissionDecisionReason"]


@pytest.mark.parametrize("tool_name", ["AskUserQuestion", "request_user_input"])
@pytest.mark.parametrize("label", ["직접 입력", "Other", "Custom (Recommended)", "type your own", "기타", "직접 작성"])
def test_스스로_만든_자유_입력_선택지는_호스트의_자유_입력_행을_알리며_거부한다(tool_name, label):
    # given
    labels = ["두 줄 지우기", "그대로 두기", label]
    # when
    result = run_hook(tool_name, labels)
    # then
    assert result.returncode == 0
    reason = reason_of(result)
    assert reason is not None and label in reason
    assert "host already adds its own free-form row" in reason and "Remove that option" in reason


def test_11월_13일_세션_두_번째_호출을_본뜬_입력은_직접_입력_선택지_때문에_거부한다():
    # given
    preview = "demo-tool 이슈 초안\n+---+----------------------+\n| 2 | 빈 보고서 첫 줄       |\n+---+----------------------+"
    event = {"hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion", "tool_input": {"questions": [{
        "question": "완료 조건(구현이 끝났는지 정하는 목록) 2번과 5번을 지울까요?", "header": "검토 반복",
        "options": [
            {"label": "두 줄 모두 삭제 (Recommended)", "description": "2번과 5번을 지운다", "preview": preview},
            {"label": "두 줄 모두 유지", "description": "그대로 둔다", "preview": preview},
            {"label": "직접 입력", "description": "원하는 답을 직접 쓴다"}],
        "multiSelect": False}]}}
    # when
    result = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(event), capture_output=True, text=True,
                            check=False)
    # then
    reason = reason_of(result) or ""
    assert '"직접 입력"' in reason and "free-form row" in reason


def test_자유_입력_선택지가_없으면_통과한다():
    # given
    labels = ["두 줄 지우기 (Recommended)", "그대로 두기"]
    # when
    result = run_hook("AskUserQuestion", labels)
    # then
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


@pytest.mark.parametrize("label", ["Other files", "Custom domain", "기타 파일 지우기", "Type your own tests first"])
def test_금지된_낱말을_포함하기만_한_선택지_이름은_통과한다(label):
    # given
    labels = ["Delete both", label]
    # when
    result = run_hook("AskUserQuestion", labels)
    # then
    assert reason_of(result) is None


def test_여러_질문_중_뒤_질문의_자유_입력_선택지도_거부한다():
    # given
    second = {"question": "어느 형식으로 낼까요?", "header": "형식",
              "options": [{"label": "csv", "description": "쉼표로 구분"}, {"label": "Other", "description": "다른 것"}]}
    # when
    result = run_hook("AskUserQuestion", ["두 줄 지우기"], second)
    # then
    assert '"Other"' in (reason_of(result) or "")


@pytest.mark.parametrize("stdin", ["", "not json", "[]", '{"tool_name": "AskUserQuestion", "label": 1}',
                                   '{"tool_name": "Bash", "tool_input": {"command": "echo label Other"}}'])
def test_읽을_수_없거나_다른_도구의_입력은_출력_없이_통과한다(stdin):
    # when
    result = subprocess.run([sys.executable, str(SCRIPT)], input=stdin, capture_output=True, text=True, check=False)
    # then
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
