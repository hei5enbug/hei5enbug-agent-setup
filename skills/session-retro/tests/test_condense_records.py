#!/usr/bin/env python3
"""기록 압축 스크립트의 종류 분류, 줄 번호 보존, 길이 제한, 시간 범위, 출력 형식, 오류 처리를 검사한다."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "condense_records.py"
ZONE = "Asia/Seoul"
ISOLATED_ENV = {"TZ"}


def stamp(minute: int, hour: int = 1) -> str:
    return f"2026-10-14T{hour:02d}:{minute:02d}:00Z"


def claude_user(timestamp: str, content: object, **extra: object) -> dict:
    return {"type": "user", "timestamp": timestamp, "message": {"role": "user", "content": content}, **extra}


def claude_assistant(timestamp: str, content: object, **extra: object) -> dict:
    return {"type": "assistant", "timestamp": timestamp, "message": {"role": "assistant", "content": content}, **extra}


def tool_use(name: str, tool_input: dict, tool_id: str = "tool-1") -> dict:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}


def tool_result(content: object, is_error: bool = False, tool_id: str = "tool-1") -> dict:
    item = {"type": "tool_result", "tool_use_id": tool_id, "content": content}
    if is_error:
        item["is_error"] = True
    return item


def codex_meta(timestamp: str) -> dict:
    payload = {"id": "codex-1", "cwd": "/work/project-a", "originator": "codex_cli_rs", "source": "cli"}
    return {"timestamp": timestamp, "type": "session_meta", "payload": payload}


def codex_event(timestamp: str, payload: dict) -> dict:
    return {"timestamp": timestamp, "type": "event_msg", "payload": payload}


def codex_item(timestamp: str, payload: dict) -> dict:
    return {"timestamp": timestamp, "type": "response_item", "payload": payload}


def write_lines(path: Path, lines: list) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    chunks = []
    for line in lines:
        if isinstance(line, dict):
            line = json.dumps(line, ensure_ascii=False)
        if isinstance(line, str):
            line = line.encode("utf-8")
        chunks.append(line + b"\n")
    path.write_bytes(b"".join(chunks))
    return path


class CondenseCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.out = self.root / "out"

    def source(self, lines: list, name: str = "session-1.jsonl", folder: str = "in") -> Path:
        return write_lines(self.root / folder / name, lines)

    def condense(
        self, *inputs: Path, env: dict[str, str] | None = None, **options: str | Path | None
    ) -> subprocess.CompletedProcess[str]:
        values: dict[str, str | Path | None] = {"out": self.out}
        values.update(options)
        command = [sys.executable, str(SCRIPT), *map(str, inputs)]
        for name, value in values.items():
            if value is not None:
                command += ["--" + name.replace("_", "-"), str(value)]
        environment = {key: value for key, value in os.environ.items() if key not in ISOLATED_ENV}
        environment.update(env or {})
        return subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", env=environment, check=False
        )

    def parse(self, result: subprocess.CompletedProcess[str]) -> dict:
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def output_lines(self, report: dict, index: int = 0) -> list[str]:
        text = Path(report["files"][index]["output"]).read_text(encoding="utf-8")
        return text.splitlines()


class ClaudeKindsTest(CondenseCase):
    def test_each_record_becomes_one_line_with_its_original_line_number(self) -> None:
        """사용자 입력, 답변, 도구 호출, 오류가 각각 원래 줄 번호가 붙은 한 줄이 된다."""
        # Given
        path = self.source(
            [
                {"type": "summary", "timestamp": stamp(0)},
                claude_user(stamp(1), "첫 요청입니다"),
                claude_assistant(stamp(2), [{"type": "thinking", "thinking": "THINK"}, {"type": "text", "text": "답변"}]),
                claude_assistant(stamp(3), [tool_use("Bash", {"command": "ls -la", "description": "list"})]),
                claude_user(stamp(4), [tool_result("boom: permission denied", is_error=True)]),
            ]
        )
        # When
        result = self.condense(path)
        # Then
        report = self.parse(result)
        self.assertEqual(
            [
                "L2 user 첫 요청입니다",
                "L3 reply 답변",
                "L4 tool Bash command=ls -la",
                "L5 error boom: permission denied",
            ],
            self.output_lines(report),
        )
        self.assertNotIn("THINK", "\n".join(self.output_lines(report)))
        self.assertEqual({"user": 1, "reply": 1, "tool": 1, "error": 1}, report["files"][0]["lines"])

    def test_tool_results_that_succeeded_and_meta_or_command_records_are_not_user_input(self) -> None:
        """성공한 도구 결과, isMeta, 로컬 명령 기록은 사용자 입력으로 남기지 않는다."""
        # Given
        path = self.source(
            [
                claude_user(stamp(0), [tool_result("SECRET-output")]),
                claude_user(stamp(1), "SECRET-meta", isMeta=True),
                claude_user(stamp(2), "<command-name>/model</command-name>"),
                claude_user(stamp(3), "<local-command-stdout>ok</local-command-stdout>"),
                claude_user(stamp(4), [{"type": "text", "text": "목록 입력"}]),
            ]
        )
        # When
        result = self.condense(path)
        # Then
        self.assertEqual(["L5 user 목록 입력"], self.output_lines(self.parse(result)))

    def test_newlines_inside_a_record_are_collapsed(self) -> None:
        """한 기록 안의 줄바꿈은 공백으로 합쳐 한 줄로 만든다."""
        # Given
        path = self.source([claude_user(stamp(0), "첫째 줄\n\n둘째 줄\r\n셋째 줄")])
        # When
        result = self.condense(path)
        # Then
        self.assertEqual(["L1 user 첫째 줄 둘째 줄 셋째 줄"], self.output_lines(self.parse(result)))

    def test_api_errors_hook_blocks_and_hook_failures_are_errors(self) -> None:
        """API 오류 응답, 훅 차단, 훅 실패 요약은 오류 줄로 남긴다."""
        # Given
        path = self.source(
            [
                claude_assistant(stamp(0), [{"type": "text", "text": "API Error: 529 overloaded"}], isApiErrorMessage=True),
                {
                    "type": "attachment",
                    "timestamp": stamp(1),
                    "attachment": {"type": "hook_blocking_error", "hookEvent": "PreToolUse", "blockingError": "blocked by guard"},
                },
                {
                    "type": "system",
                    "subtype": "stop_hook_summary",
                    "timestamp": stamp(2),
                    "hookErrors": ["hook crashed"],
                    "preventedContinuation": False,
                },
                {"type": "system", "subtype": "stop_hook_summary", "timestamp": stamp(3), "hookErrors": []},
            ]
        )
        # When
        result = self.condense(path)
        # Then
        lines = self.output_lines(self.parse(result))
        self.assertEqual(3, len(lines))
        self.assertTrue(lines[0].startswith("L1 error API Error: 529 overloaded"))
        self.assertTrue(lines[1].startswith("L2 error ") and "blocked by guard" in lines[1])
        self.assertTrue(lines[2].startswith("L3 error ") and "hook crashed" in lines[2])

    def test_line_numbers_count_blank_and_unreadable_lines(self) -> None:
        """빈 줄과 읽을 수 없는 줄도 줄 번호에 세고, 읽을 수 없는 줄의 개수를 보고한다."""
        # Given
        path = self.source(["", "not json", claude_user(stamp(0), "셋째 줄 이후"), "[1, 2]", claude_user(stamp(1), "여섯")])
        # When
        result = self.condense(path)
        # Then
        report = self.parse(result)
        self.assertEqual(["L3 user 셋째 줄 이후", "L5 user 여섯"], self.output_lines(report))
        self.assertEqual(2, report["files"][0]["unreadable_lines"])


class TruncationTest(CondenseCase):
    def test_each_kind_is_truncated_at_its_limit_with_a_dropped_count(self) -> None:
        """답변과 도구는 300자, 오류는 500자, 사용자 입력은 2000자에서 자르고 버린 글자 수를 표시한다."""
        # Given
        path = self.source(
            [
                claude_user(stamp(0), "u" * 2100),
                claude_assistant(stamp(1), [{"type": "text", "text": "r" * 400}]),
                claude_assistant(stamp(2), [tool_use("Bash", {"command": "c" * 400})]),
                claude_user(stamp(3), [tool_result("e" * 700, is_error=True)]),
            ]
        )
        # When
        result = self.condense(path)
        # Then
        user, reply, tool, error = self.output_lines(self.parse(result))
        self.assertEqual("L1 user " + "u" * 2000 + "…[100 chars dropped]", user)
        self.assertEqual("L2 reply " + "r" * 300 + "…[100 chars dropped]", reply)
        self.assertTrue(tool.startswith("L3 tool Bash command=") and tool.endswith("…[" + str(len("Bash command=" + "c" * 400) - 300) + " chars dropped]"))
        self.assertEqual("L4 error " + "e" * 500 + "…[200 chars dropped]", error)

    def test_text_within_the_limit_is_kept_whole(self) -> None:
        """제한 이내의 글은 표시 없이 그대로 둔다."""
        # Given
        path = self.source([claude_user(stamp(0), "u" * 2000), claude_assistant(stamp(1), "r" * 300)])
        # When
        result = self.condense(path)
        # Then
        user, reply = self.output_lines(self.parse(result))
        self.assertEqual("L1 user " + "u" * 2000, user)
        self.assertEqual("L2 reply " + "r" * 300, reply)

    def test_user_input_and_error_are_never_dropped_even_when_empty_text_follows(self) -> None:
        """내용이 비어 있는 오류도 줄 번호가 있는 줄로 남긴다."""
        # Given
        path = self.source([claude_user(stamp(0), [tool_result("", is_error=True)])])
        # When
        result = self.condense(path)
        # Then
        self.assertEqual(["L1 error (no text)"], self.output_lines(self.parse(result)))


class TimeRangeTest(CondenseCase):
    def test_records_outside_the_range_are_skipped_and_line_numbers_are_kept(self) -> None:
        """범위 밖의 기록과 시각이 없는 기록은 빼고 범위 안 기록은 원래 줄 번호를 지킨다."""
        # Given
        path = self.source(
            [
                claude_user("2026-10-14T00:59:59Z", "이른"),
                claude_user("2026-10-14T01:00:00Z", "시작"),
                {"type": "user", "message": {"role": "user", "content": "시각 없음"}},
                claude_user("2026-10-14T01:59:59Z", "끝 직전"),
                claude_user("2026-10-14T02:00:00Z", "끝"),
            ]
        )
        # When
        result = self.condense(path, since="2026-10-14T10:00", until="2026-10-14T11:00", tz=ZONE)
        # Then
        self.assertEqual(["L2 user 시작", "L4 user 끝 직전"], self.output_lines(self.parse(result)))

    def test_without_a_range_every_record_is_kept(self) -> None:
        """범위를 주지 않으면 시각이 없는 기록을 포함해 모든 기록을 남긴다."""
        # Given
        path = self.source(
            [claude_user(stamp(0), "하나"), {"type": "user", "message": {"role": "user", "content": "시각 없음"}}]
        )
        # When
        result = self.condense(path)
        # Then
        self.assertEqual(["L1 user 하나", "L2 user 시각 없음"], self.output_lines(self.parse(result)))

    def test_invalid_range_arguments_exit_with_two(self) -> None:
        """잘못된 범위 인자는 stderr 메시지와 종료 코드 2로 거부하고 아무것도 쓰지 않는다."""
        path = self.source([claude_user(stamp(0), "하나")])
        cases = {
            "malformed": ({"since": "2026-10-14"}, "invalid --since"),
            "reversed": ({"since": "2026-10-14T11:00", "until": "2026-10-14T10:00"}, "must be earlier"),
            "until alone": ({"until": "2026-10-14T10:00"}, "--until requires --since"),
            "unknown zone": ({"since": "2026-10-14T10:00", "tz": "Mars/Olympus"}, "unknown time zone"),
        }
        for label, (options, message) in cases.items():
            with self.subTest(label):
                # When
                result = self.condense(path, **options)
                # Then
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertEqual("", result.stdout)
                self.assertIn(message, result.stderr)
                self.assertFalse(self.out.exists())


class CodexKindsTest(CondenseCase):
    def test_codex_rollout_records_are_detected_and_condensed(self) -> None:
        """Codex 롤아웃은 session_meta로 알아보고 같은 종류의 줄로 압축한다."""
        # Given
        path = self.source(
            [
                codex_meta(stamp(0)),
                codex_event(stamp(1), {"type": "user_message", "message": "코덱스 요청"}),
                codex_item(
                    stamp(2),
                    {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "INJECTED-context"}]},
                ),
                codex_event(stamp(3), {"type": "agent_message", "message": "코덱스 답변"}),
                codex_item(stamp(4), {"type": "function_call", "name": "shell", "arguments": json.dumps({"command": ["bash", "-lc", "ls"]}), "call_id": "c1"}),
                codex_event(stamp(5), {"type": "exec_command_end", "call_id": "c1", "exit_code": 2, "aggregated_output": "no such file"}),
                codex_event(stamp(6), {"type": "exec_command_end", "call_id": "c1", "exit_code": 0, "aggregated_output": "fine"}),
                codex_event(stamp(7), {"type": "error", "message": "stream disconnected"}),
            ]
        )
        # When
        result = self.condense(path)
        # Then
        report = self.parse(result)
        lines = self.output_lines(report)
        self.assertEqual("codex", report["files"][0]["host"])
        self.assertEqual("L2 user 코덱스 요청", lines[0])
        self.assertEqual("L4 reply 코덱스 답변", lines[1])
        self.assertTrue(lines[2].startswith("L5 tool shell "))
        self.assertTrue(lines[3].startswith("L6 error ") and "no such file" in lines[3])
        self.assertEqual("L8 error stream disconnected", lines[4])
        self.assertEqual(5, len(lines))
        self.assertNotIn("INJECTED", "\n".join(lines))

    def test_newer_codex_item_completed_events_are_condensed(self) -> None:
        """item_completed 형식의 사용자·답변 항목과 모든 명령 실행을 남기고 실패한 명령에는 오류 줄을 더한다."""
        # Given
        path = self.source(
            [
                codex_meta(stamp(0)),
                codex_event(stamp(1), {"type": "item_completed", "item": {"type": "UserMessage", "content": [{"type": "text", "text": "새 형식 요청"}]}}),
                codex_event(stamp(2), {"type": "item_completed", "item": {"type": "AgentMessage", "content": [{"type": "Text", "text": "새 형식 답변"}]}}),
                codex_event(stamp(3), {"type": "item_completed", "item": {"type": "CommandExecution", "command": "pytest", "exit_code": 1, "aggregated_output": "1 failed"}}),
                codex_event(stamp(4), {"type": "item_completed", "item": {"type": "CommandExecution", "command": "true", "exit_code": 0, "aggregated_output": ""}}),
            ]
        )
        # When
        result = self.condense(path)
        # Then
        lines = self.output_lines(self.parse(result))
        self.assertEqual(["L2 user 새 형식 요청", "L3 reply 새 형식 답변"], lines[:2])
        self.assertEqual("L4 tool shell command=pytest", lines[2])
        self.assertTrue(lines[3].startswith("L4 error ") and "1 failed" in lines[3])
        self.assertEqual("L5 tool shell command=true", lines[4])
        self.assertEqual(5, len(lines))

    def test_successful_command_execution_item_leaves_one_tool_line_and_no_error(self) -> None:
        """성공한 CommandExecution 항목도 명령을 담은 도구 줄 하나를 남기고 오류 줄은 만들지 않는다."""
        # Given
        item = {"type": "CommandExecution", "command": "python3 run.py --pr 501", "aggregated_output": "ok", "exit_code": 0}
        path = self.source([codex_meta(stamp(0)), codex_event(stamp(1), {"type": "item_completed", "item": item})])
        # When
        result = self.condense(path)
        # Then
        report = self.parse(result)
        self.assertEqual(["L2 tool shell command=python3 run.py --pr 501"], self.output_lines(report))
        self.assertEqual({"user": 0, "reply": 0, "tool": 1, "error": 0}, report["files"][0]["lines"])

    def test_file_change_item_leaves_a_tool_line_and_an_error_only_when_not_completed(self) -> None:
        """FileChange 항목은 변경 경로를 담은 도구 줄을 남기고, 상태가 completed가 아닐 때만 오류 줄을 더한다."""
        # Given
        done = {"type": "FileChange", "status": "completed", "changes": [{"path": "/work/a.py", "kind": "update"}]}
        failed = {"type": "FileChange", "status": "failed", "stderr": "hunk rejected", "changes": [{"path": "/work/b.py"}]}
        path = self.source(
            [
                codex_meta(stamp(0)),
                codex_event(stamp(1), {"type": "item_completed", "item": done}),
                codex_event(stamp(2), {"type": "item_completed", "item": failed}),
            ]
        )
        # When
        result = self.condense(path)
        # Then
        lines = self.output_lines(self.parse(result))
        self.assertEqual(3, len(lines))
        self.assertEqual("L2 tool FileChange path=/work/a.py", lines[0])
        self.assertEqual("L3 tool FileChange path=/work/b.py", lines[1])
        self.assertTrue(lines[2].startswith("L3 error ") and "hunk rejected" in lines[2])

    def test_exec_command_end_and_patch_apply_end_add_no_tool_line(self) -> None:
        """exec_command_end와 patch_apply_end는 같은 호출의 function_call이 이미 있으므로 도구 줄을 더하지 않는다."""
        # Given
        path = self.source(
            [
                codex_meta(stamp(0)),
                codex_event(stamp(1), {"type": "exec_command_end", "call_id": "c1", "exit_code": 0, "aggregated_output": "fine"}),
                codex_event(stamp(2), {"type": "patch_apply_end", "call_id": "p1", "success": True}),
                codex_event(stamp(3), {"type": "patch_apply_end", "call_id": "p2", "success": False, "stderr": "no match"}),
            ]
        )
        # When
        result = self.condense(path)
        # Then
        lines = self.output_lines(self.parse(result))
        self.assertEqual(1, len(lines))
        self.assertTrue(lines[0].startswith("L4 error ") and "no match" in lines[0])


class CodexToolOutputTest(CondenseCase):
    def call_and_output(self, output_type: str, output: object, call_id: str = "c1") -> list:
        return [
            codex_meta(stamp(0)),
            codex_item(stamp(1), {"type": "function_call", "name": "shell", "arguments": json.dumps({"command": ["bash", "-lc", "make"]}), "call_id": call_id}),
            codex_item(stamp(2), {"type": output_type, "call_id": call_id, "output": output}),
        ]

    def test_failed_json_output_becomes_an_error_line_with_the_output_line_number(self) -> None:
        """metadata.exit_code가 0이 아닌 JSON 출력은 출력 기록의 줄 번호가 붙은 오류 줄이 된다."""
        # Given
        output = json.dumps({"output": "make: *** no rule", "metadata": {"exit_code": 2}})
        path = self.source(self.call_and_output("function_call_output", output))
        # When
        result = self.condense(path)
        # Then
        lines = self.output_lines(self.parse(result))
        self.assertEqual(2, len(lines))
        self.assertTrue(lines[0].startswith("L2 tool shell "))
        self.assertTrue(lines[1].startswith("L3 error ") and "no rule" in lines[1])

    def test_failed_text_output_and_custom_tool_output_become_error_lines(self) -> None:
        """Exit code: n으로 시작하는 문자열 출력과 custom_tool_call_output의 실패도 오류 줄이 된다."""
        # Given
        path = self.source(
            [
                codex_meta(stamp(0)),
                codex_item(stamp(1), {"type": "function_call_output", "call_id": "t1", "output": "Exit code: 127\nWall time: 0 seconds\nOutput:\nnot found"}),
                codex_item(stamp(2), {"type": "custom_tool_call_output", "call_id": "t2", "output": json.dumps({"output": "patch rejected", "metadata": {"exit_code": 1}})}),
            ]
        )
        # When
        result = self.condense(path)
        # Then
        lines = self.output_lines(self.parse(result))
        self.assertEqual(2, len(lines))
        self.assertTrue(lines[0].startswith("L2 error ") and "not found" in lines[0])
        self.assertTrue(lines[1].startswith("L3 error ") and "patch rejected" in lines[1])

    def test_successful_or_unstructured_outputs_leave_no_error(self) -> None:
        """종료 코드가 0이거나 종료 코드를 알 수 없는 출력은 오류 줄을 만들지 않는다."""
        # Given
        path = self.source(
            [
                codex_meta(stamp(0)),
                codex_item(stamp(1), {"type": "function_call_output", "call_id": "a", "output": json.dumps({"output": "ok", "metadata": {"exit_code": 0}})}),
                codex_item(stamp(2), {"type": "function_call_output", "call_id": "b", "output": "Exit code: 0\nOutput:\nfine"}),
                codex_item(stamp(3), {"type": "function_call_output", "call_id": "c", "output": "plain text with Exit code: 9 inside"}),
                codex_item(stamp(4), {"type": "function_call_output", "call_id": "d", "output": "[1, 2]"}),
            ]
        )
        # When
        result = self.condense(path)
        # Then
        self.assertEqual([], self.output_lines(self.parse(result)))

    def test_one_error_per_call_id_when_exec_command_end_also_failed(self) -> None:
        """같은 call_id의 exec_command_end가 이미 실패했으면 순서와 상관없이 오류 줄은 하나만 남긴다."""
        # Given
        failed_output = json.dumps({"output": "boom", "metadata": {"exit_code": 2}})
        end = codex_event(stamp(2), {"type": "exec_command_end", "call_id": "c1", "exit_code": 2, "aggregated_output": "boom"})
        output = codex_item(stamp(3), {"type": "function_call_output", "call_id": "c1", "output": failed_output})
        for label, records in {"end first": [end, output], "output first": [output, end]}.items():
            with self.subTest(label):
                path = self.source([codex_meta(stamp(0)), *records], name=label.replace(" ", "-") + ".jsonl")
                # When
                result = self.condense(path)
                # Then
                lines = self.output_lines(self.parse(result))
                self.assertEqual(1, len(lines), lines)
                self.assertIn(" error ", lines[0])
                self.assertIn("boom", lines[0])

    def test_failed_outputs_of_different_call_ids_are_each_reported(self) -> None:
        """call_id가 다른 실패 출력은 서로 가리지 않고 각각 오류 줄이 된다."""
        # Given
        failed = json.dumps({"output": "boom", "metadata": {"exit_code": 2}})
        path = self.source(
            [
                codex_meta(stamp(0)),
                codex_event(stamp(1), {"type": "exec_command_end", "call_id": "c1", "exit_code": 2, "aggregated_output": "boom"}),
                codex_item(stamp(2), {"type": "function_call_output", "call_id": "c2", "output": failed}),
            ]
        )
        # When
        result = self.condense(path)
        # Then
        self.assertEqual(2, len(self.output_lines(self.parse(result))))


class OutputAndErrorsTest(CondenseCase):
    def test_report_lists_paths_sizes_and_counts_for_every_input(self) -> None:
        """입력마다 경로, 입력·출력 바이트, 종류별 줄 수를 담은 JSON 하나를 출력한다."""
        # Given
        first = self.source([claude_user(stamp(0), "하나"), claude_assistant(stamp(1), "답")], name="a.jsonl")
        second = self.source([codex_meta(stamp(0)), codex_event(stamp(1), {"type": "user_message", "message": "x"})], name="rollout-b.jsonl")
        # When
        result = self.condense(first, second)
        # Then
        report = self.parse(result)
        self.assertEqual(json.dumps(report, sort_keys=True, ensure_ascii=False) + "\n", result.stdout)
        self.assertEqual([str(first), str(second)], [item["input"] for item in report["files"]])
        for item, source in zip(report["files"], (first, second)):
            self.assertEqual(source.stat().st_size, item["input_bytes"])
            self.assertEqual(Path(item["output"]).stat().st_size, item["output_bytes"])
            self.assertEqual(self.out, Path(item["output"]).parent)
        self.assertEqual({"user": 1, "reply": 1, "tool": 0, "error": 0}, report["files"][0]["lines"])
        self.assertEqual({"user": 1, "reply": 0, "tool": 0, "error": 0}, report["files"][1]["lines"])
        self.assertEqual([], report["failed"])

    def test_inputs_with_the_same_file_name_get_distinct_outputs(self) -> None:
        """이름이 같은 입력 파일도 서로 덮어쓰지 않도록 출력 파일 이름을 구분한다."""
        # Given
        first = self.source([claude_user(stamp(0), "하나")], folder="one")
        second = self.source([claude_user(stamp(0), "둘")], folder="two")
        # When
        result = self.condense(first, second)
        # Then
        report = self.parse(result)
        self.assertEqual(2, len({item["output"] for item in report["files"]}))
        self.assertEqual(["L1 user 하나"], self.output_lines(report, 0))
        self.assertEqual(["L1 user 둘"], self.output_lines(report, 1))

    def test_condensed_file_is_much_smaller_than_the_input(self) -> None:
        """큰 도구 결과와 생각 기록을 버려 출력이 입력보다 훨씬 작다."""
        # Given
        big = "x" * 50000
        path = self.source(
            [claude_user(stamp(0), "요청"), claude_user(stamp(1), [tool_result(big)]), claude_assistant(stamp(2), [{"type": "thinking", "thinking": big}])]
        )
        # When
        result = self.condense(path)
        # Then
        item = self.parse(result)["files"][0]
        self.assertLess(item["output_bytes"] * 100, item["input_bytes"])

    def test_missing_input_exits_with_one_after_condensing_the_others(self) -> None:
        """읽을 수 없는 입력이 있으면 종료 코드 1을 돌려주지만 나머지는 압축하고 failed에 적는다."""
        # Given
        good = self.source([claude_user(stamp(0), "하나")])
        missing = self.root / "in" / "missing.jsonl"
        # When
        result = self.condense(good, missing)
        # Then
        self.assertEqual(1, result.returncode)
        report = json.loads(result.stdout)
        self.assertEqual([str(good)], [item["input"] for item in report["files"]])
        self.assertEqual([str(missing)], [item["path"] for item in report["failed"]])
        self.assertIn(str(missing), result.stderr)

    def test_missing_arguments_and_bad_out_exit_with_two(self) -> None:
        """--out이 없거나 파일이면 종료 코드 2로 거부한다."""
        # Given
        path = self.source([claude_user(stamp(0), "하나")])
        plain = self.root / "plain-file"
        plain.write_text("x", encoding="utf-8")
        # When
        without_out = subprocess.run(
            [sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True, check=False
        )
        file_out = self.condense(path, out=plain)
        # Then
        self.assertEqual(2, without_out.returncode)
        self.assertEqual(2, file_out.returncode)
        self.assertIn("--out is not a directory", file_out.stderr)

    def test_condensing_never_adds_text_that_the_record_lacks(self) -> None:
        """출력은 기록의 글자만 옮기고 그 밖의 필드(사용자 이름 등)를 더하지 않는다."""
        # Given
        path = self.source(
            [claude_user(stamp(0), "요청", cwd="/home/test/secret-dir", sessionId="SID-123", gitBranch="BRANCH-9")]
        )
        # When
        result = self.condense(path)
        # Then
        text = "\n".join(self.output_lines(self.parse(result)))
        for forbidden in ("secret-dir", "SID-123", "BRANCH-9"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
