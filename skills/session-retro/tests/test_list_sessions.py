#!/usr/bin/env python3
"""세션 목록 스크립트의 하루 경계, 호스트별 선별, 출력 형식, 오류 처리를 검사한다."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "list_sessions.py"
DAY = "2026-10-14"
ZONE = "Asia/Seoul"
CWD = "/work/project-a"
OTHER_CWD = "/work/project-b"
RECENT_MTIME = datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp()
ISOLATED_ENV = {"CLAUDE_CONFIG_DIR", "CODEX_HOME", "TZ"}
CANNOT_LIST_AS_ROOT = unittest.skipIf(
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    "root can list any directory",
)


def encode_cwd(cwd: str) -> str:
    return re.sub(r"[^A-Za-z0-9-]", "-", cwd)


def claude_entry(timestamp: str, content: object = "질문입니다", **extra: object) -> dict:
    return {"type": "user", "timestamp": timestamp, "message": {"role": "user", "content": content}, **extra}


def codex_meta(timestamp: str, cwd: str = CWD, session_id: str = "codex-1", source: object = "cli") -> dict:
    payload = {"id": session_id, "cwd": cwd, "originator": "codex_cli_rs", "source": source}
    return {"timestamp": timestamp, "type": "session_meta", "payload": payload}


def codex_user_message(timestamp: str, text: str = "질문입니다") -> dict:
    return {"timestamp": timestamp, "type": "event_msg", "payload": {"type": "user_message", "message": text}}


def codex_agent_message(timestamp: str) -> dict:
    return {"timestamp": timestamp, "type": "event_msg", "payload": {"type": "agent_message", "message": "답변"}}


def write_lines(path: Path, lines: list, mtime: float = RECENT_MTIME) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    chunks = []
    for line in lines:
        if isinstance(line, dict):
            line = json.dumps(line, ensure_ascii=False)
        if isinstance(line, str):
            line = line.encode("utf-8")
        chunks.append(line + b"\n")
    path.write_bytes(b"".join(chunks))
    os.utime(path, (mtime, mtime))


class ListSessionsCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.claude_dir = self.root / "claude"
        self.codex_dir = self.root / "codex"

    def claude_path(self, name: str = "claude-1.jsonl", cwd: str = CWD) -> Path:
        return self.claude_dir / "projects" / encode_cwd(cwd) / name

    def codex_path(
        self, name: str = "rollout-2026-10-14T10-00-00-codex-1.jsonl", folder: str = "2026/10/14"
    ) -> Path:
        return self.codex_dir / "sessions" / folder / name

    def claude_file(
        self, lines: list, name: str = "claude-1.jsonl", cwd: str = CWD, mtime: float = RECENT_MTIME
    ) -> Path:
        path = self.claude_path(name, cwd)
        write_lines(path, lines, mtime)
        return path

    def codex_file(self, lines: list, mtime: float = RECENT_MTIME, **location: str) -> Path:
        path = self.codex_path(**location)
        write_lines(path, lines, mtime)
        return path

    def scan(
        self,
        env: dict[str, str] | None = None,
        run_cwd: Path | None = None,
        **options: str | Path | None,
    ) -> subprocess.CompletedProcess[str]:
        values: dict[str, str | Path | None] = {
            "date": DAY,
            "tz": ZONE,
            "cwd": CWD,
            "claude_dir": self.claude_dir,
            "codex_dir": self.codex_dir,
        }
        values.update(options)
        command = [sys.executable, str(SCRIPT)]
        for name, value in values.items():
            if value is not None:
                command += ["--" + name.replace("_", "-"), str(value)]
        environment = {key: value for key, value in os.environ.items() if key not in ISOLATED_ENV}
        environment.update(env or {})
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            cwd=run_cwd,
            check=False,
        )

    def parse(self, result: subprocess.CompletedProcess[str]) -> dict:
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)


class DayWindowTest(ListSessionsCase):
    def test_records_are_counted_by_the_day_of_the_chosen_zone(self) -> None:
        """자정 직전과 직후의 기록은 빼고 지정한 시간대의 하루 안에 있는 기록만 센다."""
        # Given
        self.claude_file(
            [
                claude_entry("2026-10-13T14:59:59.999Z"),
                claude_entry("2026-10-13T15:00:00Z"),
                claude_entry("2026-10-14T14:59:59Z"),
                claude_entry("2026-10-14T15:00:00Z"),
            ]
        )
        # When
        result = self.scan()
        # Then
        session = self.parse(result)["sessions"][0]
        self.assertEqual("2026-10-14T00:00:00+09:00", session["first_record"])
        self.assertEqual("2026-10-14T23:59:59+09:00", session["last_record"])
        self.assertEqual(2, session["user_messages"])

    def test_session_with_records_only_outside_the_day_is_omitted(self) -> None:
        """하루 밖의 기록만 가진 세션은 목록에 넣지 않는다."""
        # Given
        self.claude_file([claude_entry("2026-10-13T14:59:59Z"), claude_entry("2026-10-14T15:00:00Z")])
        # When
        result = self.scan()
        # Then
        self.assertEqual([], self.parse(result)["sessions"])

    def test_day_with_a_daylight_saving_change_lasts_25_hours(self) -> None:
        """일광 절약 시간이 끝나는 날은 25시간으로 계산한다."""
        # Given
        self.claude_file(
            [
                claude_entry("2026-11-01T03:59:59Z"),
                claude_entry("2026-11-01T04:00:00Z"),
                claude_entry("2026-11-02T04:59:59Z"),
                claude_entry("2026-11-02T05:00:00Z"),
            ]
        )
        # When
        result = self.scan(date="2026-11-01", tz="America/New_York")
        # Then
        session = self.parse(result)["sessions"][0]
        self.assertEqual("2026-11-01T00:00:00-04:00", session["first_record"])
        self.assertEqual("2026-11-01T23:59:59-05:00", session["last_record"])
        self.assertEqual(2, session["user_messages"])

    def test_local_time_zone_is_used_when_tz_is_omitted(self) -> None:
        """--tz를 생략하면 TZ 환경 변수가 가리키는 지역 시간대로 하루를 정한다."""
        # Given
        self.claude_file([claude_entry("2026-10-13T14:59:59Z"), claude_entry("2026-10-13T15:00:00Z")])
        # When
        result = self.scan(tz=None, env={"TZ": ZONE})
        # Then
        data = self.parse(result)
        self.assertEqual(ZONE, data["tz"])
        self.assertEqual(["2026-10-14T00:00:00+09:00"], [item["first_record"] for item in data["sessions"]])


class ClaudeSessionsTest(ListSessionsCase):
    def test_project_folder_follows_the_observed_path_encoding(self) -> None:
        """경로의 영문자, 숫자, 하이픈 외의 모든 문자를 하이픈으로 바꾼 폴더에서 세션을 찾는다."""
        cases = {
            "/Users/a/Desktop/x/Back%20Office.b": "-Users-a-Desktop-x-Back-20Office-b",
            "/private/tmp/claude-501/-Users-a": "-private-tmp-claude-501--Users-a",
        }
        for cwd, folder in cases.items():
            with self.subTest(cwd=cwd):
                # Given
                path = self.claude_dir / "projects" / folder / "claude-1.jsonl"
                write_lines(path, [claude_entry("2026-10-14T01:00:00Z")])
                # When
                result = self.scan(cwd=cwd)
                # Then
                self.assertEqual([str(path)], [item["path"] for item in self.parse(result)["sessions"]])

    def test_tool_result_only_and_meta_entries_are_not_utterances(self) -> None:
        """도구 결과만 담은 항목과 isMeta 항목은 사용자 발화로 세지 않고 내용도 출력하지 않는다."""
        # Given
        self.claude_file(
            [
                claude_entry("2026-10-14T01:00:00Z", "SECRET-first"),
                claude_entry("2026-10-14T02:00:00Z", [{"type": "text", "text": "SECRET-second"}]),
                claude_entry(
                    "2026-10-14T03:00:00Z",
                    [{"type": "tool_result", "tool_use_id": "tool-1", "content": "SECRET-output"}],
                ),
                claude_entry("2026-10-14T04:00:00Z", "SECRET-meta", isMeta=True),
                {
                    "type": "assistant",
                    "timestamp": "2026-10-14T05:00:00Z",
                    "message": {"role": "assistant", "content": "SECRET-answer"},
                },
            ]
        )
        # When
        result = self.scan()
        # Then
        session = self.parse(result)["sessions"][0]
        self.assertEqual(2, session["user_messages"])
        self.assertEqual("2026-10-14T14:00:00+09:00", session["last_record"])
        self.assertNotIn("SECRET", result.stdout)

    def test_local_command_records_are_not_utterances(self) -> None:
        """로컬 명령 기록은 사용자가 입력한 발화로 세지 않는다."""
        # Given
        self.claude_file(
            [
                claude_entry("2026-10-14T01:00:00Z", "<command-name>/model</command-name>"),
                claude_entry("2026-10-14T01:00:01Z", "<local-command-stdout>Set model</local-command-stdout>"),
                claude_entry("2026-10-14T01:00:02Z", [{"type": "text", "text": "<local-command-caveat>x"}]),
                claude_entry("2026-10-14T01:00:03Z", "질문입니다"),
            ]
        )
        # When
        result = self.scan()
        # Then
        self.assertEqual(1, self.parse(result)["sessions"][0]["user_messages"])

    def test_file_whose_records_name_another_cwd_is_excluded(self) -> None:
        """같은 프로젝트 폴더로 변환되는 다른 작업 디렉터리의 세션은 기록의 cwd로 제외한다."""
        # Given
        cwd = "/work/x.y"
        kept = self.claude_file([claude_entry("2026-10-14T01:00:00Z", cwd=cwd)], name="kept.jsonl", cwd=cwd)
        self.claude_file([claude_entry("2026-10-14T01:00:00Z", cwd="/work/x-y")], name="other.jsonl", cwd=cwd)
        self.claude_file([claude_entry("2026-10-14T01:00:00Z")], name="no-cwd.jsonl", cwd=cwd)
        # When
        result = self.scan(cwd=cwd)
        # Then
        paths = sorted(item["path"] for item in self.parse(result)["sessions"])
        self.assertEqual(sorted([str(kept), str(self.claude_path("no-cwd.jsonl", cwd))]), paths)

    def test_entrypoint_comes_from_the_first_entry_that_has_it(self) -> None:
        """entrypoint는 그것을 가진 첫 항목에서 가져오고 없으면 null로 보고한다."""
        # Given
        self.claude_file(
            [
                {"type": "summary", "timestamp": "2026-10-14T00:30:00Z"},
                claude_entry("2026-10-14T01:00:00Z", entrypoint="cli"),
                claude_entry("2026-10-14T02:00:00Z", entrypoint="sdk-cli"),
            ],
            name="with-entrypoint.jsonl",
        )
        self.claude_file([claude_entry("2026-10-14T03:00:00Z")], name="without-entrypoint.jsonl")
        # When
        result = self.scan()
        # Then
        sources = {item["session_id"]: item["source"] for item in self.parse(result)["sessions"]}
        self.assertEqual({"with-entrypoint": "cli", "without-entrypoint": None}, sources)

    def test_subagent_transcripts_are_counted_and_not_listed_as_sessions(self) -> None:
        """하위 에이전트 기록은 별도 세션이 아니라 세션별 개수로만 보고한다."""
        # Given
        self.claude_file([claude_entry("2026-10-14T01:00:00Z")], name="claude-1.jsonl")
        self.claude_file([claude_entry("2026-10-14T02:00:00Z")], name="claude-2.jsonl")
        subagents = self.claude_path("claude-1").parent / "claude-1" / "subagents"
        write_lines(subagents / "agent-a.jsonl", [claude_entry("2026-10-14T01:10:00Z")])
        write_lines(subagents / "agent-b.jsonl", [claude_entry("2026-10-14T01:20:00Z")])
        write_lines(subagents / "agent-a.meta.json", [{"agentType": "Explore"}])
        # When
        result = self.scan()
        # Then
        counts = {item["session_id"]: item["subagent_transcripts"] for item in self.parse(result)["sessions"]}
        self.assertEqual({"claude-1": 2, "claude-2": 0}, counts)

    def test_corrupt_lines_keep_the_session_and_are_reported_as_skipped(self) -> None:
        """읽을 수 없는 줄이 있어도 세션은 남기고 그 줄의 개수를 skipped에 적는다."""
        # Given
        path = self.claude_file(
            [
                claude_entry("2026-10-14T01:00:00Z"),
                "not json",
                b'{"type": "user", "timestamp": "2026-10-14T01:30:00Z", "x": "\xff"}',
                "[1, 2]",
                {"type": "user", "timestamp": "yesterday"},
                claude_entry("2026-10-14T02:00:00Z"),
            ]
        )
        # When
        result = self.scan()
        # Then
        data = self.parse(result)
        self.assertEqual([2], [item["user_messages"] for item in data["sessions"]])
        self.assertEqual([{"path": str(path), "reason": "4 unreadable lines"}], data["skipped"])

    def test_file_without_readable_records_on_the_day_is_still_reported(self) -> None:
        """하루 안의 기록을 읽을 수 없는 손상 파일도 세션에서는 빠지지만 skipped에는 남는다."""
        # Given
        path = self.claude_file(["not json", "{broken"])
        # When
        result = self.scan()
        # Then
        data = self.parse(result)
        self.assertEqual([], data["sessions"])
        self.assertEqual(
            [{"path": str(path), "reason": "2 unreadable lines; no readable record on the day"}], data["skipped"]
        )

    def test_claude_file_modified_before_the_day_is_skipped_without_being_read(self) -> None:
        """수정 시각이 하루의 시작보다 이른 Claude 파일은 읽지 않으므로 손상 줄도 보고하지 않는다."""
        # Given
        day_start = datetime(2026, 10, 13, 15, 0, 0, tzinfo=timezone.utc).timestamp()
        self.claude_file([claude_entry("2026-10-14T02:00:00Z"), "{broken"], mtime=day_start - 1)
        # When
        result = self.scan()
        # Then
        data = self.parse(result)
        self.assertEqual([], data["sessions"])
        self.assertEqual([], data["skipped"])

    def test_unopenable_file_is_skipped_without_failing_the_scan(self) -> None:
        """열 수 없는 파일은 skipped에 적고 나머지 세션은 그대로 보고한다."""
        # Given
        self.claude_file([claude_entry("2026-10-14T01:00:00Z")], name="claude-1.jsonl")
        broken = self.claude_path("broken.jsonl")
        broken.symlink_to(self.root / "missing.jsonl")
        # When
        result = self.scan()
        # Then
        data = self.parse(result)
        self.assertEqual(["claude-1"], [item["session_id"] for item in data["sessions"]])
        self.assertEqual([str(broken)], [item["path"] for item in data["skipped"]])
        self.assertTrue(data["skipped"][0]["reason"].startswith("cannot be read"))


class CodexSessionsTest(ListSessionsCase):
    def test_file_in_an_earlier_date_folder_is_included_when_it_has_records_on_the_day(self) -> None:
        """전날 폴더에서 시작한 세션도 하루 안의 기록이 있으면 그 구간만 보고한다."""
        # Given
        path = self.codex_file(
            [
                codex_meta("2026-10-13T11:00:00Z"),
                codex_user_message("2026-10-13T12:00:00Z"),
                codex_user_message("2026-10-14T02:00:00Z"),
                codex_agent_message("2026-10-14T03:00:00Z"),
            ],
            folder="2026/10/13",
            name="rollout-2026-10-13T20-00-00-codex-1.jsonl",
        )
        # When
        result = self.scan()
        # Then
        session = self.parse(result)["sessions"][0]
        self.assertEqual(str(path), session["path"])
        self.assertEqual("2026-10-14T11:00:00+09:00", session["first_record"])
        self.assertEqual("2026-10-14T12:00:00+09:00", session["last_record"])
        self.assertEqual(1, session["user_messages"])

    def test_file_modified_before_the_day_is_skipped_without_being_read(self) -> None:
        """수정 시각이 하루의 시작보다 이른 파일은 읽지 않고, 시작과 같은 파일은 읽는다."""
        # Given
        day_start = datetime(2026, 10, 13, 15, 0, 0, tzinfo=timezone.utc).timestamp()
        in_day = [codex_user_message("2026-10-14T02:00:00Z"), "{broken"]
        self.codex_file(
            [codex_meta("2026-10-13T11:00:00Z", session_id="old"), *in_day],
            mtime=day_start - 1,
            name="rollout-old.jsonl",
        )
        self.codex_file(
            [codex_meta("2026-10-13T11:00:00Z", session_id="boundary"), codex_user_message("2026-10-14T02:00:00Z")],
            mtime=day_start,
            name="rollout-boundary.jsonl",
        )
        # When
        result = self.scan()
        # Then
        data = self.parse(result)
        self.assertEqual(["boundary"], [item["session_id"] for item in data["sessions"]])
        self.assertEqual([], data["skipped"])

    def test_subagent_source_reports_the_parent_session(self) -> None:
        """하위 에이전트 세션은 source를 subagent로, 부모 세션 id를 parent_session_id로 보고한다."""
        # Given
        spawn = {"subagent": {"thread_spawn": {"parent_thread_id": "parent-1", "depth": 1}}}
        self.codex_file(
            [codex_meta("2026-10-14T01:00:00Z", session_id="child-1", source=spawn)],
            name="rollout-child.jsonl",
        )
        self.codex_file(
            [codex_meta("2026-10-14T02:00:00Z", session_id="exec-1", source="exec")],
            name="rollout-exec.jsonl",
        )
        # When
        result = self.scan()
        # Then
        reported = {
            item["session_id"]: (item["source"], item["parent_session_id"]) for item in self.parse(result)["sessions"]
        }
        self.assertEqual({"child-1": ("subagent", "parent-1"), "exec-1": ("exec", None)}, reported)

    def test_only_user_message_events_are_utterances(self) -> None:
        """user_message 이벤트와 완료된 UserMessage 항목만 사용자 발화로 세고 내용은 출력하지 않는다."""
        # Given
        self.codex_file(
            [
                codex_meta("2026-10-14T01:00:00Z"),
                codex_user_message("2026-10-14T02:00:00Z", "SECRET-first"),
                codex_agent_message("2026-10-14T03:00:00Z"),
                {
                    "timestamp": "2026-10-14T04:00:00Z",
                    "type": "response_item",
                    "payload": {"type": "message", "role": "user", "content": "SECRET-echo"},
                },
                codex_user_message("2026-10-14T05:00:00Z", "SECRET-second"),
                {
                    "timestamp": "2026-10-14T06:00:00Z",
                    "type": "event_msg",
                    "payload": {"type": "item_completed", "item": {"type": "UserMessage", "content": "SECRET-third"}},
                },
                {
                    "timestamp": "2026-10-14T07:00:00Z",
                    "type": "event_msg",
                    "payload": {"type": "item_completed", "item": {"type": "AgentMessage", "content": "SECRET-reply"}},
                },
            ]
        )
        # When
        result = self.scan()
        # Then
        self.assertEqual(3, self.parse(result)["sessions"][0]["user_messages"])
        self.assertNotIn("SECRET", result.stdout)

    def test_corrupt_line_keeps_the_session_and_is_reported_as_skipped(self) -> None:
        """읽을 수 없는 줄이 있어도 세션은 남기고 그 줄의 개수를 skipped에 적는다."""
        # Given
        path = self.codex_file(
            [codex_meta("2026-10-14T01:00:00Z"), "{broken", codex_user_message("2026-10-14T02:00:00Z")]
        )
        # When
        result = self.scan()
        # Then
        data = self.parse(result)
        self.assertEqual([1], [item["user_messages"] for item in data["sessions"]])
        self.assertEqual([{"path": str(path), "reason": "1 unreadable lines"}], data["skipped"])

    def test_codex_file_without_readable_records_on_the_day_is_still_reported(self) -> None:
        """전날 메타데이터와 손상 줄만 있는 Codex 파일도 skipped에 남긴다."""
        # Given
        path = self.codex_file([codex_meta("2026-10-13T11:00:00Z"), "{broken"])
        # When
        result = self.scan()
        # Then
        data = self.parse(result)
        self.assertEqual([], data["sessions"])
        self.assertEqual(
            [{"path": str(path), "reason": "1 unreadable lines; no readable record on the day"}], data["skipped"]
        )

    def test_file_without_session_meta_is_reported_as_skipped(self) -> None:
        """session_meta로 시작하지 않는 파일은 작업 폴더를 알 수 없으므로 skipped에 적는다."""
        # Given
        path = self.codex_file([codex_user_message("2026-10-14T02:00:00Z")])
        # When
        result = self.scan()
        # Then
        data = self.parse(result)
        self.assertEqual([], data["sessions"])
        self.assertEqual([{"path": str(path), "reason": "first record is not session_meta"}], data["skipped"])

    def test_unopenable_file_is_skipped_without_failing_the_scan(self) -> None:
        """열 수 없는 파일은 skipped에 적고 나머지 세션은 그대로 보고한다."""
        # Given
        self.codex_file([codex_meta("2026-10-14T01:00:00Z")], name="rollout-ok.jsonl")
        broken = self.codex_path("rollout-broken.jsonl")
        broken.symlink_to(self.root / "missing.jsonl")
        # When
        result = self.scan()
        # Then
        data = self.parse(result)
        self.assertEqual(["codex-1"], [item["session_id"] for item in data["sessions"]])
        self.assertEqual([str(broken)], [item["path"] for item in data["skipped"]])
        self.assertTrue(data["skipped"][0]["reason"].startswith("cannot be read"))

    @CANNOT_LIST_AS_ROOT
    def test_unlistable_date_folder_is_skipped_without_failing_the_scan(self) -> None:
        """읽을 수 없는 날짜 폴더는 skipped에 적고 다른 폴더의 세션은 그대로 보고한다."""
        # Given
        self.codex_file([codex_meta("2026-10-14T01:00:00Z")], folder="2026/10/14", name="rollout-ok.jsonl")
        locked = self.codex_dir / "sessions" / "2026" / "10" / "13"
        locked.mkdir(parents=True)
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o755)
        # When
        result = self.scan()
        # Then
        data = self.parse(result)
        self.assertEqual(["codex-1"], [item["session_id"] for item in data["sessions"]])
        self.assertEqual([str(locked)], [item["path"] for item in data["skipped"]])
        self.assertTrue(data["skipped"][0]["reason"].startswith("cannot list directory"))


class OutputAndArgumentsTest(ListSessionsCase):
    def test_sessions_of_both_hosts_are_sorted_by_first_record_with_stable_fields(self) -> None:
        """두 호스트의 세션을 첫 기록 시각순으로 정렬하고 키를 정렬한 JSON 한 개로 출력한다."""
        # Given
        claude_path = self.claude_file(
            [claude_entry("2026-10-14T02:00:00Z", entrypoint="cli"), claude_entry("2026-10-14T02:30:00Z", "추가")],
        )
        codex_path = self.codex_file(
            [codex_meta("2026-10-14T01:00:00Z"), codex_user_message("2026-10-14T01:30:00Z")]
        )
        # When
        result = self.scan()
        # Then
        data = self.parse(result)
        self.assertEqual(json.dumps(data, sort_keys=True, ensure_ascii=False) + "\n", result.stdout)
        self.assertEqual({"date": DAY, "tz": ZONE, "cwd": CWD}, {key: data[key] for key in ("date", "tz", "cwd")})
        self.assertEqual(
            [
                {
                    "host": "codex",
                    "path": str(codex_path),
                    "session_id": "codex-1",
                    "first_record": "2026-10-14T10:00:00+09:00",
                    "last_record": "2026-10-14T10:30:00+09:00",
                    "user_messages": 1,
                    "source": "cli",
                    "parent_session_id": None,
                    "subagent_transcripts": None,
                },
                {
                    "host": "claude",
                    "path": str(claude_path),
                    "session_id": "claude-1",
                    "first_record": "2026-10-14T11:00:00+09:00",
                    "last_record": "2026-10-14T11:30:00+09:00",
                    "user_messages": 2,
                    "source": "cli",
                    "parent_session_id": None,
                    "subagent_transcripts": 0,
                },
            ],
            data["sessions"],
        )
        self.assertEqual([], data["skipped"])

    def test_sessions_of_another_cwd_are_excluded_on_both_hosts(self) -> None:
        """다른 작업 폴더의 세션은 Claude Code와 Codex 모두에서 제외한다."""
        # Given
        self.claude_file([claude_entry("2026-10-14T01:00:00Z")], name="claude-mine.jsonl")
        self.claude_file([claude_entry("2026-10-14T01:00:00Z")], name="claude-other.jsonl", cwd=OTHER_CWD)
        self.codex_file([codex_meta("2026-10-14T01:00:00Z", session_id="codex-mine")], name="rollout-mine.jsonl")
        self.codex_file(
            [codex_meta("2026-10-14T01:00:00Z", cwd=OTHER_CWD, session_id="codex-other")], name="rollout-other.jsonl"
        )
        # When
        result = self.scan()
        # Then
        ids = {item["session_id"] for item in self.parse(result)["sessions"]}
        self.assertEqual({"claude-mine", "codex-mine"}, ids)

    def test_empty_result_exits_zero_with_an_empty_session_list(self) -> None:
        """조건에 맞는 세션이 없으면 종료 코드 0과 빈 sessions를 돌려준다."""
        # Given
        self.claude_path().parent.mkdir(parents=True)
        (self.codex_dir / "sessions").mkdir(parents=True)
        # When
        result = self.scan()
        # Then
        data = self.parse(result)
        self.assertEqual([], data["sessions"])
        self.assertEqual([], data["skipped"])

    def test_missing_directories_are_not_an_error(self) -> None:
        """Claude Code와 Codex 디렉터리가 없어도 오류 없이 빈 결과를 돌려준다."""
        # Given: 임시 폴더 아래에 두 디렉터리를 만들지 않는다.
        # When
        result = self.scan()
        # Then
        data = self.parse(result)
        self.assertEqual([], data["sessions"])
        self.assertEqual([], data["skipped"])

    def test_invalid_date_exits_with_two(self) -> None:
        """YYYY-MM-DD가 아니거나 없는 날짜는 stderr 메시지와 종료 코드 2로 거부한다."""
        for date in ("2026-13-01", "2026-02-30", "2026-10-1", "20261014", "tomorrow", ""):
            with self.subTest(date=date):
                # When
                result = self.scan(date=date)
                # Then
                self.assertEqual(2, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertIn("invalid date", result.stderr)

    def test_unknown_time_zone_exits_with_two(self) -> None:
        """알 수 없는 시간대는 stderr 메시지와 종료 코드 2로 거부한다."""
        # When
        result = self.scan(tz="Mars/Olympus")
        # Then
        self.assertEqual(2, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("unknown time zone", result.stderr)

    def test_config_directory_that_is_a_file_exits_with_two(self) -> None:
        """디렉터리가 아닌 파일을 설정 디렉터리로 주면 종료 코드 2로 거부한다."""
        # Given
        not_a_directory = self.root / "plain-file"
        not_a_directory.write_text("x", encoding="utf-8")
        # When
        result = self.scan(claude_dir=not_a_directory)
        # Then
        self.assertEqual(2, result.returncode)
        self.assertIn("--claude-dir is not a directory", result.stderr)

    @CANNOT_LIST_AS_ROOT
    def test_unlistable_host_directory_exits_with_one(self) -> None:
        """존재하는 Claude Code 또는 Codex 디렉터리를 읽을 수 없으면 종료 코드 1을 돌려준다."""
        locked_directories = {
            "claude": self.claude_path().parent,
            "codex": self.codex_dir / "sessions",
        }
        for host, directory in locked_directories.items():
            with self.subTest(host=host):
                # Given
                directory.mkdir(parents=True)
                directory.chmod(0)
                try:
                    # When
                    result = self.scan()
                finally:
                    directory.chmod(0o755)
                # Then
                self.assertEqual(1, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertIn("cannot list directory", result.stderr)

    def test_directories_default_to_environment_variables(self) -> None:
        """--claude-dir와 --codex-dir를 생략하면 CLAUDE_CONFIG_DIR와 CODEX_HOME를 쓴다."""
        # Given
        self.claude_file([claude_entry("2026-10-14T01:00:00Z")])
        self.codex_file([codex_meta("2026-10-14T02:00:00Z")])
        environment = {"CLAUDE_CONFIG_DIR": str(self.claude_dir), "CODEX_HOME": str(self.codex_dir)}
        # When
        result = self.scan(claude_dir=None, codex_dir=None, env=environment)
        # Then
        self.assertEqual(["claude", "codex"], [item["host"] for item in self.parse(result)["sessions"]])

    def test_cwd_is_resolved_to_an_absolute_path(self) -> None:
        """--cwd를 상대 경로로 주거나 생략하면 현재 디렉터리의 절대 경로로 보고한다."""
        for cwd in (".", None):
            with self.subTest(cwd=cwd):
                # When
                result = self.scan(cwd=cwd, run_cwd=self.root)
                # Then
                self.assertEqual(os.path.realpath(self.root), self.parse(result)["cwd"])

    def test_output_is_utf8_with_the_original_cwd(self) -> None:
        """한글 작업 폴더도 이스케이프 없이 UTF-8로 출력한다."""
        # Given
        cwd = "/작업/프로젝트"
        self.claude_file([claude_entry("2026-10-14T01:00:00Z")], cwd=cwd)
        # When
        result = self.scan(cwd=cwd)
        # Then
        data = self.parse(result)
        self.assertEqual(cwd, data["cwd"])
        self.assertEqual(1, len(data["sessions"]))
        self.assertIn(f'"cwd": "{cwd}"', result.stdout)


if __name__ == "__main__":
    unittest.main()
