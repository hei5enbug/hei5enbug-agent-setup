"""Unit tests for the unapplied candidate script that prints the question-tool inputs a session transcript stores."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "evals/e2e/candidates/117/stored_question_input.py"
spec = importlib.util.spec_from_file_location("stored_question_input", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

QUESTION = {"questions": [{"question": "q", "options": [{"label": "こんにちは"}]}]}


def claude_line(tool_input: dict, ascii_only: bool = False) -> str:
    block = {"type": "tool_use", "id": "t1", "name": "AskUserQuestion", "input": tool_input}
    return json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [block]}}, ensure_ascii=ascii_only)


def run(tmp_path: Path, lines: list[str], capsys) -> tuple[int, str]:
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    code = module.main(["stored_question_input.py", str(path)])
    return code, capsys.readouterr().out


def test_JSON이_가나를_이스케이프로_적은_기록은_저장된_이스케이프_글이_아니라고_알린다(tmp_path, capsys):
    """파일에 `\\u3053`가 보여도 JSON 표기일 뿐이면 입력은 가나이므로 종료 코드 0과 원문 글자를 낸다. 텍스트 검색은 이 경우를 오탐한다."""
    # Given
    lines = [claude_line(QUESTION, ascii_only=True)]

    # When
    code, output = run(tmp_path, lines, capsys)

    # Then
    assert "\\u3053" in lines[0]
    assert (code, 'label: "こんにちは"' in output, "stored escape text: no" in output) == (0, True, True)


def test_입력_자체가_이스케이프_글을_담은_기록은_종료_코드_1과_표시를_낸다(tmp_path, capsys):
    """라벨이 여섯 글자 `\\u3053` 글 자체이면 그 줄에 표시가 붙고 종료 코드가 1이다."""
    # Given
    escaped = {"questions": [{"question": "q", "options": [{"label": "\\u3053\\u3093"}]}]}

    # When
    code, output = run(tmp_path, [claude_line(escaped)], capsys)

    # Then
    assert code == 1
    assert "<- the stored input itself holds escape text" in output
    assert "stored escape text: yes" in output


def test_Codex_롤아웃의_request_user_input과_읽을_수_없는_줄과_다른_도구를_구분한다(tmp_path, capsys):
    """롤아웃 함수 호출의 arguments 문자열을 풀어 읽고, 깨진 JSON 줄과 다른 도구 호출은 건너뛴다."""
    # Given
    rollout = json.dumps({"type": "response_item", "payload": {"type": "function_call", "name": "request_user_input",
                                                               "arguments": json.dumps(QUESTION, ensure_ascii=False)}}, ensure_ascii=False)
    other = json.dumps({"type": "response_item", "payload": {"type": "function_call", "name": "exec", "arguments": "{}"}})

    # When
    code, output = run(tmp_path, ["{not json", other, rollout], capsys)

    # Then
    assert code == 0
    assert "question inputs: 1" in output
    assert "request_user_input" in output


def test_없는_파일은_종료_코드_2다(tmp_path):
    """읽을 수 없는 경로는 결과를 만들지 않고 2로 끝나 호출한 쪽이 기록을 못 읽었다고 알 수 있다."""
    # Given
    missing = tmp_path / "none.jsonl"

    # When
    code = module.main(["stored_question_input.py", str(missing)])

    # Then
    assert code == 2
