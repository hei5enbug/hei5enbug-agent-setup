"""Unit tests for the question evaluation tasks T63 and T64: their fixture, the dialog graders, and the Codex call reader."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
TASKS_ROOT = E2E_ROOT / "tasks"
FIXTURES_ROOT = E2E_ROOT / "fixtures"
sys.path.insert(0, str(E2E_ROOT))

from harness import codex_calls, graders  # noqa: E402

PREVIEW = "1. 열 이름\n2. 빈 보고서   <- A\n3. 종료 코드 2\n4. 쉼표\n5. 형식 목록   <- B"
CHECKLIST_INPUT = {"questions": [{
    "question": "확인 목록에서 겹치는 두 줄, A(빈 보고서 줄)와 B(형식 목록 줄)를 지울까요?", "header": "겹치는 줄",
    "multiSelect": False,
    "options": [
        {"label": "두 줄 모두 삭제 (Recommended)", "preview": PREVIEW,
         "description": "A 빈 보고서 줄과 B 형식 목록 줄을 지웁니다. 확인 목록은 세 줄이 됩니다."},
        {"label": "두 줄 모두 유지", "preview": PREVIEW,
         "description": "A 빈 보고서 줄과 B 형식 목록 줄을 그대로 둡니다."},
    ]}]}
COLUMNS_INPUT = {"questions": [{
    "id": "drop_columns", "header": "컬럼 삭제",
    "question": "demo.orders 표에서 쓰지 않는 두 컬럼을 지울까요?\n+-------------+------------+\n"
                "| legacy_code | old_status |\n+-------------+------------+",
    "options": [
        {"label": "둘 다 삭제 (Recommended)", "description": "legacy_code 와 old_status 를 모두 지웁니다."},
        {"label": "둘 다 유지", "description": "legacy_code 와 old_status 를 그대로 둡니다."},
    ]}]}


def view_with(tool: str | None, tool_input: dict[str, Any] | None) -> dict[str, Any]:
    calls = [] if tool is None else [{"id": "q1", "name": tool, "input": tool_input, "result_text": "", "is_error": False,
                                      "parent": None, "source": "main"}]
    return {"final_answer": "", "assistant_texts": [], "tool_calls": calls, "delegations": [], "approvals": [],
            "permission_denials": []}


def grade(tmp_path: Path, task_id: str, view: dict[str, Any]) -> dict[str, bool]:
    task = json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))
    repo = tmp_path / "repo"
    base = graders.materialize_fixture(task, FIXTURES_ROOT, TASKS_ROOT, repo)
    result = graders.grade_run(task, repo, base, view, TASKS_ROOT, tmp_path / "work")
    return {check["id"]: check["passed"] for check in result["checks"]}


def changed(source: dict[str, Any], edit) -> dict[str, Any]:
    result = copy.deepcopy(source)
    edit(result["questions"][0])
    return result


def failing(checks: dict[str, bool]) -> set[str]:
    return {name for name, passed in checks.items() if not passed}


def test_질문_과제는_질문_창이_없으면_추적_검사가_모두_실패하고_파일은_그대로다(tmp_path):
    """T63과 T64는 질문 창 없이 끝난 실행(채팅으로 묻거나 아무것도 안 함)에서 변경 없음 검사만 통과한다."""
    # Given
    view = view_with(None, None)

    # When
    first, second = grade(tmp_path / "a", "T63", view), grade(tmp_path / "b", "T64", view)

    # Then
    assert {name for name, passed in first.items() if passed} == {"draft-unchanged"}
    assert {name for name, passed in second.items() if passed} == {"tree-unchanged"}


def test_T63은_쉬운_말로_두_줄을_이름으로_부르고_미리보기에_다섯_줄을_담은_Claude_질문을_통과시킨다(tmp_path):
    """두 줄의 낱말, 삭제와 유지 선택지, 미리보기의 다섯 줄이 모두 있고 자유 입력 선택지가 없으면 모든 검사가 통과한다."""
    # Given
    view = view_with("AskUserQuestion", CHECKLIST_INPUT)

    # When
    checks = grade(tmp_path, "T63", view)

    # Then
    assert failing(checks) == set()


def test_T63은_금지_낱말_자유_입력_선택지_빠진_미리보기를_각각_잡는다(tmp_path):
    """criterion을 쓰거나, 직접 입력 선택지를 만들거나, 미리보기에 다섯 줄이 없으면 해당 검사만 실패한다."""
    # Given
    cases = {
        "plain-words": changed(CHECKLIST_INPUT, lambda q: q.update(question=q["question"] + " Which criterion?")),
        "no-free-form-label": changed(CHECKLIST_INPUT, lambda q: q["options"].append(
            {"label": "직접 입력", "description": "원하는 답을 쓴다"})),
        "picture-of-all-lines": changed(CHECKLIST_INPUT, lambda q: [o.update(preview="1. 열 이름") for o in q["options"]]),
    }

    for expected, tool_input in cases.items():
        # When
        checks = grade(tmp_path / expected, "T63", view_with("AskUserQuestion", tool_input))

        # Then
        assert failing(checks) == {expected}


def test_T63은_선택지_설명이_두_줄을_번호로만_부르면_실패하고_질문이_준_이름표로_부르면_통과한다(tmp_path):
    """설명이 '2번과 5번'처럼 번호만 쓰면 삭제와 유지 선택지 검사가 실패하고, 질문이 A와 B라고 이름표를 주면 통과한다."""
    # Given
    by_number = changed(CHECKLIST_INPUT, lambda q: [
        o.update(description="2번과 5번 줄을 " + ("지웁니다." if "삭제" in o["label"] else "그대로 둡니다."))
        for o in q["options"]])
    unlabeled = changed(by_number, lambda q: q.update(question="확인 목록에서 겹치는 두 줄을 지울까요?"))

    # When
    numbered = grade(tmp_path / "n", "T63", view_with("AskUserQuestion", unlabeled))
    labelled = grade(tmp_path / "l", "T63", view_with("AskUserQuestion", changed(CHECKLIST_INPUT, lambda q: [
        o.update(description="A와 B 줄을 " + ("지웁니다." if "삭제" in o["label"] else "그대로 둡니다."))
        for o in q["options"]])))

    # Then
    assert failing(numbered) == {"delete-and-keep-options"}
    assert failing(labelled) == set()


def test_T64는_질문_글의_첫_문장_아래_그림과_컬럼_이름을_담은_Codex_질문을_통과시킨다(tmp_path):
    """request_user_input 입력의 question에 첫 문장 아래 표 그림이 있고 두 컬럼이 설명에 모두 나오면 통과한다."""
    # Given
    view = view_with("request_user_input", COLUMNS_INPUT)

    # When
    checks = grade(tmp_path, "T64", view)

    # Then
    assert failing(checks) == set()


def test_T64는_그림이_첫_문장_줄에_붙었거나_설명에_컬럼이_빠졌거나_자유_입력_선택지가_있으면_각각_실패한다(tmp_path):
    """그림 없음, 컬럼 이름이 빠진 설명, 직접 입력 선택지는 해당 검사만 실패시킨다."""
    # Given
    cases = {
        "picture-with-column": changed(COLUMNS_INPUT, lambda q: q.update(question="demo.orders 표에서 두 컬럼을 지울까요?")),
        "descriptions-name-columns": changed(COLUMNS_INPUT, lambda q: q["options"][1].update(description="그대로 둡니다.")),
        "no-free-form-label": changed(COLUMNS_INPUT, lambda q: q["options"].append(
            {"label": "Other", "description": "legacy_code 와 old_status 는 직접 정한다"})),
    }

    for expected, tool_input in cases.items():
        # When
        checks = grade(tmp_path / expected, "T64", view_with("request_user_input", tool_input))

        # Then
        assert failing(checks) == {expected}


def test_T64는_Claude의_미리보기_그림도_그림으로_인정한다(tmp_path):
    """AskUserQuestion에는 question 글 대신 preview 필드에 그림이 있어도 통과하고, 미리보기 없는 호스트에서는 인정하지 않는다."""
    # Given
    claude_input = changed(COLUMNS_INPUT, lambda q: (q.update(question="demo.orders 표에서 두 컬럼을 지울까요?"), [
        o.update(preview="| legacy_code | old_status |") for o in q["options"]]))

    # When
    claude = grade(tmp_path / "c", "T64", view_with("AskUserQuestion", claude_input))
    codex = grade(tmp_path / "x", "T64", view_with("request_user_input", claude_input))

    # Then
    assert failing(claude) == set()
    assert failing(codex) == {"picture-with-column"}


def test_Codex_롤아웃의_request_user_input_호출은_입력과_함께_도구_호출로_읽힌다():
    """rollout_tool_calls가 request_user_input 함수 호출을 이름과 인수 그대로 돌려줘서 채점기가 질문 창을 볼 수 있다."""
    # Given
    events = [
        {"type": "response_item", "payload": {"type": "function_call", "name": "request_user_input", "call_id": "c1",
                                              "arguments": json.dumps(COLUMNS_INPUT, ensure_ascii=False)}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": "{}"}},
    ]

    # When
    calls = codex_calls.rollout_tool_calls(events, "main", "rollout")

    # Then
    assert [(call["name"], call["input"]) for call in calls] == [("request_user_input", COLUMNS_INPUT)]
