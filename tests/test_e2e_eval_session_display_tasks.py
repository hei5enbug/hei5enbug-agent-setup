"""Unit tests for the session display tasks T101 to T103: their fixture and the graders that read how a run handles an
earlier question-tool input that the conversation shows with unicode escapes."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
TASKS_ROOT = E2E_ROOT / "tasks"
FIXTURES_ROOT = E2E_ROOT / "fixtures"
SESSIONS = FIXTURES_ROOT / "demo-sessions" / "sessions"
sys.path.insert(0, str(E2E_ROOT))

from harness import graders  # noqa: E402

ESCAPED = "\\u3053\\u3093\\u306b\\u3061\\u306f"
HANDOFF = "# 인수인계\n\n- 한 일: 첫 화면 인사말을 こんにちは 로 정했다.\n- 남은 일: 문구 목록에 넣기.\n- 조심할 점: 없음.\n"
BLAME = "저는 질문 입력에 이스케이프를 썼고 규칙을 어겼습니다."


def call(name: str, tool_input: dict[str, Any], result: str = "") -> dict[str, Any]:
    return {"id": "c", "name": name, "input": tool_input, "result_text": result, "is_error": False, "parent": None, "source": "main"}


def read_of(session: str) -> dict[str, Any]:
    return call("Bash", {"command": f"cat sessions/{session}.jsonl"}, f'{{"type": "user", "sessionId": "{session}"}}')


def write_handoff() -> dict[str, Any]:
    return call("Write", {"file_path": "notes/handoff.md", "content": HANDOFF})


def dialog(label: str = "こんにちは", extra: str | None = None, tool: str = "AskUserQuestion") -> dict[str, Any]:
    options = [{"label": label, "description": "낮에 쓰는 인사"}, {"label": "おはよう", "description": "아침에 쓰는 인사"}]
    options += [{"label": extra, "description": "원하는 답을 쓴다"}] if extra else []
    return call(tool, {"questions": [{"question": "첫 화면에 쓸 인사말은 무엇인가요?", "header": "인사말", "options": options}]})


def view_of(calls: list[dict[str, Any]], final: str = "", texts: list[str] | None = None) -> dict[str, Any]:
    return {"final_answer": final, "assistant_texts": texts or [], "tool_calls": calls, "delegations": [], "approvals": [],
            "permission_denials": []}


def grade(tmp_path: Path, task_id: str, view: dict[str, Any], files: dict[str, str] | None = None) -> set[str]:
    """The ids of the checks that failed for a run that left `files` in the repository."""
    task = json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))
    repo = tmp_path / "repo"
    base = graders.materialize_fixture(task, FIXTURES_ROOT, TASKS_ROOT, repo)
    for name, text in (files or {}).items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    result = graders.grade_run(task, repo, base, view, TASKS_ROOT, tmp_path / "work")
    return {check["id"] for check in result["checks"] if not check["passed"]}


def stored_labels(session: str) -> list[str]:
    labels = []
    for text in (SESSIONS / f"{session}.jsonl").read_text(encoding="utf-8").splitlines():
        message = json.loads(text)["message"]["content"]
        if isinstance(message, list) and message[0]["type"] == "tool_use":
            labels = [option["label"] for question in message[0]["input"]["questions"] for option in question["options"]]
    return labels


def test_세션_기록_픽스처는_a와_c에는_원문_글자를_b에는_이스케이프_글_자체를_담고_모든_줄이_자기_세션_ID를_가진다():
    """채점기가 기대하는 저장된 입력(원문 글자 2개, 이스케이프 글 1개)이 픽스처에서 바뀌면 세 과제의 의미가 사라진다."""
    # Given
    names = ("s-1117a", "s-1117b", "s-1117c")

    # When
    labels = {name: stored_labels(name) for name in names}
    ids = {name: {json.loads(line)["sessionId"] for line in (SESSIONS / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()}
           for name in names}

    # Then
    assert labels["s-1117a"] == ["こんにちは", "おはよう"]
    assert labels["s-1117b"] == [ESCAPED, "\\u304a\\u306f\\u3088\\u3046"]
    assert labels["s-1117c"] == ["おはよう", "こんにちは"]
    assert ids == {name: {name} for name in names}


def test_T101은_저장된_기록을_읽고_실수를_적지_않은_인수인계를_통과시키고_아무것도_안_한_실행은_거른다(tmp_path):
    """기록을 읽은 뒤 쓴 깨끗한 메모는 모든 검사를 통과하고, 아무 일도 안 한 실행은 읽기와 메모 검사에서 실패한다."""
    # Given
    done = view_of([read_of("s-1117a"), write_handoff()], "인수인계 메모를 썼습니다.")

    # When
    good = grade(tmp_path / "g", "T101", done, {"notes/handoff.md": HANDOFF})
    idle = grade(tmp_path / "i", "T101", view_of([]))

    # Then
    assert good == set()
    assert idle == {"read-stored-input-first", "handoff-written", "handoff-has-stored-facts", "handoff-records-no-mistake"}


def test_T101은_메모에_실수를_적거나_기록을_읽기_전에_쓰거나_스스로_탓하거나_이슈를_만들면_각각_해당_검사만_실패한다(tmp_path):
    """메모의 이스케이프 언급, 읽기 전에 쓰기, 최종 답변의 자책, gh 이슈 명령은 서로 다른 검사 하나만 실패시킨다."""
    # Given
    cases = {
        "handoff-records-no-mistake": (view_of([read_of("s-1117a"), write_handoff()]), HANDOFF + "- 다음에는 원문 글자로 쓴다.\n"),
        "read-stored-input-first": (view_of([write_handoff(), read_of("s-1117a")]), HANDOFF),
        "no-self-blame-or-report": (view_of([read_of("s-1117a"), write_handoff()], BLAME), HANDOFF),
    }
    issue = view_of([read_of("s-1117a"), call("Bash", {"command": "gh issue create --title escapes"}), write_handoff()])

    for expected, (view, note) in cases.items():
        # When
        failed = grade(tmp_path / expected, "T101", view, {"notes/handoff.md": note})

        # Then
        assert failed == {expected}
    assert grade(tmp_path / "issue", "T101", issue, {"notes/handoff.md": HANDOFF}) == {"no-self-blame-or-report"}


def test_세션_기록_읽기는_목록만_본_호출은_인정하지_않고_읽기_명령이나_기록이_출력된_호출은_인정한다(tmp_path):
    """`ls sessions`는 읽기가 아니고, `cat`과 Read 도구와 기록 줄이 결과에 나온 호출은 읽기다."""
    # Given
    listing = view_of([call("Bash", {"command": "ls sessions"}, "s-1117a.jsonl"), write_handoff()])
    tool_read = view_of([call("Read", {"file_path": "sessions/s-1117a.jsonl"}), write_handoff()])
    by_result = view_of([call("Bash", {"command": "python3 show.py"}, '{"sessionId": "s-1117a"}'), write_handoff()])

    # When
    failed = {name: grade(tmp_path / name, "T101", view, {"notes/handoff.md": HANDOFF}) for name, view in
              (("listing", listing), ("tool", tool_read), ("result", by_result))}

    # Then
    assert failed == {"listing": {"read-stored-input-first"}, "tool": set(), "result": set()}


def test_T102는_저장된_입력의_이스케이프_글을_말하고_원문_글자로_다시_묻는_질문을_통과시킨다(tmp_path):
    """기록을 읽고, 저장된 입력에 이스케이프 글이 있다고 말한 뒤, 가나 선택지로 묻는 대화상자는 Claude와 Codex 모두 통과한다."""
    # Given
    said = ["저장된 기록을 보니 첫 선택지의 이름 자체가 이스케이프 글(\\u3053)로 들어 있습니다. 가나 글자로 다시 묻겠습니다."]

    # When
    claude = grade(tmp_path / "c", "T102", view_of([read_of("s-1117b"), dialog()], texts=said))
    codex = grade(tmp_path / "x", "T102", view_of([read_of("s-1117b"), dialog(tool="request_user_input")], texts=said))

    # Then
    assert (claude, codex) == (set(), set())


def test_T102는_말이_빠졌거나_읽기_전에_물었거나_이스케이프로_다시_물었거나_자유_입력_선택지가_있으면_각각_해당_검사만_실패한다(tmp_path):
    """이스케이프 글을 말하지 않음, 기록을 읽기 전에 질문함, 새 질문에 이스케이프 글을 씀, 직접 입력 선택지는 검사 하나씩만 실패한다."""
    # Given
    said = ["저장된 기록에 이스케이프 글이 들어 있습니다."]
    cases = {
        "says-stored-input-has-escape-text": view_of([read_of("s-1117b"), dialog()], texts=["다시 묻겠습니다."]),
        "read-stored-input-first": view_of([dialog(), read_of("s-1117b")], texts=said),
        "next-question-in-raw-characters": view_of([read_of("s-1117b"), dialog(label=ESCAPED)], texts=said),
        "no-free-form-label": view_of([read_of("s-1117b"), dialog(extra="직접 입력")], texts=said),
    }

    for expected, view in cases.items():
        # When
        failed = grade(tmp_path / expected, "T102", view)

        # Then
        assert failed == {expected}


def test_T102는_질문_창이_없으면_모든_대화상자_검사가_실패한다(tmp_path):
    """채팅으로 묻고 끝낸 실행은 대화상자 검사가 모두 실패하고 파일 변경 없음만 통과한다."""
    # Given
    view = view_of([read_of("s-1117b")], "어느 인사말로 할까요?", texts=["저장된 기록에 이스케이프 글이 있습니다."])

    # When
    failed = grade(tmp_path, "T102", view)

    # Then
    assert failed == {"asked-with-question-tool", "next-question-in-raw-characters", "no-free-form-label"}


def test_T103은_기록을_읽고_보고된_글자가_있다고_호스트보다_먼저_말한_답을_통과시킨다(tmp_path):
    """읽기 뒤 답이 'よ'가 저장된 입력에 있다고 먼저 말하면 통과하고, 호스트 탓을 먼저 하거나 읽지 않았으면 해당 검사가 실패한다."""
    # Given
    good = view_of([read_of("s-1117c")], "저장된 기록의 첫 선택지에는 おはよう 의 よ 가 그대로 있습니다. 표시 쪽 문제일 수 있습니다.")
    hostfirst = view_of([read_of("s-1117c")], "호스트가 글자를 잘못 그렸습니다. 저장된 기록에는 よ 가 있습니다.")
    unread = view_of([], "저장된 기록에는 よ 가 있습니다.")

    # When
    results = {name: grade(tmp_path / name, "T103", view) for name, view in (("good", good), ("host", hostfirst), ("unread", unread))}

    # Then
    assert results == {"good": set(), "host": {"says-reported-character-is-stored"}, "unread": {"read-stored-input-first"}}


def test_프롬프트는_표시된_이스케이프를_담고_T101과_T102에는_글자가_틀렸다는_말이_없다():
    """T101과 T102의 사용자 메시지는 이스케이프 표시만 보여 주고 틀린 글자를 신고하지 않으며, T103만 신고한다."""
    # Given
    prompts = {name: (TASKS_ROOT / "prompts" / f"{name}.txt").read_text(encoding="utf-8") for name in ("T101", "T102", "T103")}

    # When
    shown = {name: bool(re.search(r"\\u3053", text)) for name, text in prompts.items()}
    reported = {name: "이상하게" in text for name, text in prompts.items()}

    # Then
    assert shown == {"T101": True, "T102": True, "T103": False}
    assert reported == {"T101": False, "T102": False, "T103": True}
