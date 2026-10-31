from __future__ import annotations

import json
import os
import shlex
import struct
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import test_orca_plugin_refresh as base
from test_orca_plugin_refresh import FINISHED_TURN, RUNNING_TURN, FakeOrca, assistant_record, refresh, result_record, terminal, tool_use, turn_end, user_record, write_records

import refresh_process
import refresh_reload
import refresh_resume
import refresh_sessions

ProcessOs = refresh_process.ProcessOs
HANDLE = "term_claude"
SESSION_ID = "11111111-2222-3333-4444-555555555555"
CONFIG_DIR = "/home/test/profile dir/home"
OLD_EXE = "/home/test/.local/share/claude/versions/2.1.311"
NEW_EXE = "/home/test/.local/share/claude/versions/2.1.314"
CLAUDE_PATH = "/home/test/.local/bin/claude"
LAUNCH_ARGS = ["claude", "--plugin-dir", "/tmp/work/agent view", "--dangerously-skip-permissions", "--continue"]
GOOD_RELOAD = "Reloaded: 7 plugins · 56 skills · 14 agents · 20 hooks"
BAD_RELOAD = "Reloaded: 5 plugins · 44 skills · 12 agents · 15 hooks\n1 error during load. Run /plugin for details."
HELP = """Usage: claude [options] [command] [prompt]

Arguments:
  prompt                                Your prompt

Options:
  --add-dir <directories...>            Additional directories to allow tool
                                        access to
  --allowedTools, --allowed-tools <tools...>
      Comma or space-separated list of tool names to allow
  -c, --continue                        Continue the most recent conversation
  --dangerously-skip-permissions        Bypass all permission checks.
  -d, --debug [filter]                  Enable debug mode
  --fork-session                        When resuming, create a new session ID
  --model <model>                       Model for the current session
  --plugin-dir <path>                   Load a plugin from a directory
  -p, --print                           Print response and exit
  -r, --resume [value]                  Resume a conversation
  --session-id <uuid>                   Use a specific session ID
  -h, --help                            Display help for command

Commands:
  agents                                List agents
"""
LATER = lambda: (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat(timespec="milliseconds")


class FakeProcesses:
    """A process table with the same shape as the operating system calls the lookup makes."""

    def __init__(self):
        self.table: dict[int, dict] = {}
        self.next_pid = 100
        self.link_target = NEW_EXE
        self.files = {OLD_EXE, NEW_EXE}
        self.help_text = HELP

    def add(self, handle, argv, exe, config_dir, *, entrypoint=None, comm="claude", extra_env=None):
        self.next_pid += 1
        env = {"ORCA_TERMINAL_HANDLE": handle, **(extra_env or {})}
        if config_dir:
            env["CLAUDE_CONFIG_DIR"] = config_dir
        if entrypoint:
            env["CLAUDE_CODE_ENTRYPOINT"] = entrypoint
        self.table[self.next_pid] = {"comm": comm, "argv": list(argv), "env": env, "exe": exe}
        return self.next_pid

    def system(self):
        return ProcessOs(
            list_processes=lambda: [(pid, item["comm"]) for pid, item in self.table.items()],
            read_args=lambda pid: (self.table[pid]["argv"], self.table[pid]["env"]) if pid in self.table else None,
            exe_path=lambda pid: self.table.get(pid, {}).get("exe"),
            lsof_path=lambda pid: None,
            exists=lambda path: path in self.files,
            which=lambda name: CLAUDE_PATH,
            realpath=lambda path: self.link_target,
            version_text=lambda path: None,
            help_text=lambda path: self.help_text,
        )


class ResumeCase(unittest.TestCase):
    """A Claude Code session in one Orca terminal, with a fake process table and a fake Orca that reacts to what is sent."""

    reload_answer = GOOD_RELOAD
    exe = OLD_EXE
    config_dir = CONFIG_DIR
    launch_args = LAUNCH_ARGS

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {"ORCA_USER_DATA_PATH": self.temp.name, "XDG_STATE_HOME": self.temp.name, "ORCA_TERMINAL_HANDLE": "term_self"})
        env.start()
        self.addCleanup(env.stop)
        for module, name, value in ((refresh_sessions, "POLL_SECONDS", 0), (refresh_sessions, "DRAFT_STABLE_SECONDS", 0),
                                    (refresh_sessions, "PROBE_RECHECK_SECONDS", 0), (refresh_sessions, "CLEAR_SETTLE_SECONDS", 0),
                                    (refresh_sessions, "TYPE_CONFIRM_SECONDS", 0), (refresh_resume, "EXIT_TIMEOUT", 0.05),
                                    (refresh_resume, "MARKER_TIMEOUT", 0.05), (refresh_resume, "READY_TIMEOUT", 0.05),
                                    (refresh_resume, "RELOAD_TIMEOUT_AFTER_RESUME", 5.0), (refresh_resume, "POLL", 0)):
            patcher = patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.processes = FakeProcesses()
        factory = patch.object(refresh_process, "ProcessOs", lambda: self.processes.system())
        factory.start()
        self.addCleanup(factory.stop)
        refresh_reload.EXPECTED_CACHE.clear()
        counted = patch.object(refresh_reload, "enabled_count", return_value=7)
        self.enabled_count = counted.start()
        self.addCleanup(counted.stop)
        self.transcript = Path(self.temp.name) / f"{SESSION_ID}.jsonl"
        write_records(self.transcript, FINISHED_TURN)
        self.write_marker(source="startup")
        self.pid = self.processes.add(HANDLE, self.launch_args, self.exe, self.config_dir)
        self.hang_on_exit = False
        self.resumed_source = "resume"
        self.resumed_session = SESSION_ID
        self.resumed_config = self.config_dir
        self.fake = FakeOrca([terminal(HANDLE, "claude")], on_send=self.simulate)
        self.state = {"hosts": {"claude": {"digest": "d", "root": self.temp.name}, "codex": {"digest": "d", "root": self.temp.name}}, "sessions": {}}
        self.run_id = "b" * 32
        refresh.save_json(refresh.run_path(self.run_id), {**self.state, "run_id": self.run_id})

    def write_marker(self, source, session=SESSION_ID, written_at=None):
        directory = refresh.SESSION_CONTEXT.marker_directory()
        directory.mkdir(parents=True, exist_ok=True)
        payload = {"schema": 1, "host": "claude", "root": self.temp.name, "digest": "d", "source": source,
                   "transcript_path": str(Path(self.temp.name) / f"{session}.jsonl"), "written_at": written_at or refresh.now()}
        (directory / f"{HANDLE}.json").write_text(json.dumps(payload))

    def simulate(self, fake, handle, text):
        if text == "/exit":
            if not self.hang_on_exit:
                self.processes.table.pop(self.pid, None)
        elif "--resume" in text:
            tokens = shlex.split(text)
            config = tokens[0].partition("=")[2] if tokens[0].startswith("CLAUDE_CONFIG_DIR=") else None
            start = 1 if config is not None else 0
            argv = ["claude", *tokens[start + 1:]]
            self.processes.add(HANDLE, argv, NEW_EXE, self.resumed_config if self.resumed_config != self.config_dir else config)
            if self.resumed_source:
                self.write_marker(self.resumed_source, self.resumed_session, LATER())
        elif text == "/reload-plugins":
            record = {"type": "system", "subtype": "local_command", "content": self.reload_answer, "timestamp": refresh.now()}
            with self.transcript.open("a") as stream:
                stream.write(json.dumps(record) + "\n")

    def resume(self):
        with patch.object(refresh, "Orca", return_value=self.fake), patch.object(refresh_resume, "Orca", return_value=self.fake):
            return refresh_resume.run_resume(self.run_id, [HANDLE], sleep=lambda seconds: None)

    def exits(self):
        return [text for _, text in self.fake.sent if text == "/exit"]


class ReloadAnswerTest(ResumeCase):
    def drive_reload(self):
        entry = {"handle": HANDLE, "host": "claude", "status": "pending", "actions": ["reload"], "worktree": self.temp.name, "title": "t"}
        refresh.drive(self.fake, [entry], self.state, __import__("time").time() + 30, sleep=lambda seconds: None)
        return entry

    def test_로드_오류가_보고된_reload_답은_plugin_load_error로_실패한다(self):
        """reload 답에 `1 error during load`가 있으면 Reloaded 줄이 있어도 done이 아니라 plugin_load_error로 실패하고 보고된 개수를 남긴다."""
        # Given
        self.reload_answer = BAD_RELOAD

        # When
        entry = self.drive_reload()

        # Then
        self.assertEqual(("failed", "plugin_load_error"), (entry["status"], entry["detail"]))
        self.assertEqual({"plugins": 5, "skills": 44, "agents": 12, "hooks": 15, "errors": 1, "expected_plugins": 7}, entry["plugin_load"])
        self.assertTrue(refresh.public({**entry, "handle": HANDLE})["resume_approval_needed"])

    def test_화면에만_보이는_로드_오류도_plugin_load_error로_실패한다(self):
        """기록이 없어 화면으로 확인할 때도 Reloaded 줄 아래의 오류 줄을 읽어 plugin_load_error로 실패한다."""
        # Given
        self.write_marker("startup")
        os.remove(self.transcript)
        self.fake.on_send = lambda fake, handle, text: fake.show(handle, "  ⎿  Reloaded: 5 plugins · 44 skills") or fake.show(handle, "     1 error during load. Run /plugin for details.")

        # When
        entry = self.drive_reload()

        # Then
        self.assertEqual(("failed", "plugin_load_error"), (entry["status"], entry["detail"]))
        self.assertEqual(1, entry["plugin_load"]["errors"])

    def test_활성화_목록보다_적은_플러그인을_불러온_reload_답은_plugin_load_error로_실패한다(self):
        """오류 문구가 없어도 불러온 플러그인 수가 claude plugin list의 활성화 수보다 적으면 plugin_load_error로 실패한다."""
        # Given
        self.reload_answer = "Reloaded: 5 plugins · 44 skills · 12 agents · 15 hooks"

        # When
        entry = self.drive_reload()

        # Then
        self.assertEqual(("failed", "plugin_load_error"), (entry["status"], entry["detail"]))
        self.assertEqual({"plugins": 5, "skills": 44, "agents": 12, "hooks": 15, "errors": 0, "expected_plugins": 7}, entry["plugin_load"])

    def test_활성화_수를_알_수_없으면_개수_비교만_건너뛰고_오류_문구는_계속_본다(self):
        """활성화 수를 얻지 못하면 적게 불러온 것은 비교하지 않아 done이고, 오류 문구가 있으면 여전히 실패한다."""
        # Given
        self.enabled_count.return_value = None
        records = [[{"subtype": "local_command", "content": "Reloaded: 5 plugins · 44 skills"}],
                   [{"subtype": "local_command", "content": BAD_RELOAD}]]

        # When
        outcomes = [refresh.transcript_outcome("claude", "reload", item, {"handle": HANDLE, "worktree": self.temp.name}) for item in records]

        # Then
        self.assertEqual(["done", "failed:plugin_load_error"], outcomes)

    def test_같은_설정과_작업_폴더의_활성화_수는_한_번만_읽는다(self):
        """같은 CLAUDE_CONFIG_DIR와 작업 폴더의 세션이 여러 번 판정되어도 claude plugin list는 한 번만 실행한다."""
        # Given
        entry = {"handle": HANDLE, "worktree": self.temp.name}

        # When
        counts = [refresh_reload.expected_plugins(entry) for _ in range(3)]

        # Then
        self.assertEqual([7, 7, 7], counts)
        self.enabled_count.assert_called_once_with({"CLAUDE_CONFIG_DIR": CONFIG_DIR}, self.temp.name)

    def test_세션_전용_플러그인_폴더가_다른_세션은_활성화_수를_따로_읽는다(self):
        """CLAUDE_CODE_PLUGIN_DIRS만 다른 두 세션은 각자의 값으로, 변수가 없는 세션은 그 변수 없이 claude plugin list를 실행한다."""
        # Given
        for handle, extra in (("term_a", {"CLAUDE_CODE_PLUGIN_DIRS": "/tmp/work/a"}), ("term_b", {"CLAUDE_CODE_PLUGIN_DIRS": "/tmp/work/b"}), ("term_c", {})):
            self.processes.add(handle, ["claude"], NEW_EXE, CONFIG_DIR, extra_env=extra)
        entries = [{"handle": handle, "worktree": self.temp.name} for handle in ("term_a", "term_b", "term_c")]

        # When
        counts = [refresh_reload.expected_plugins(entry) for entry in entries]

        # Then
        self.assertEqual([7, 7, 7], counts)
        self.assertEqual([call.args for call in self.enabled_count.call_args_list],
                         [({"CLAUDE_CONFIG_DIR": CONFIG_DIR, "CLAUDE_CODE_PLUGIN_DIRS": "/tmp/work/a"}, self.temp.name),
                          ({"CLAUDE_CONFIG_DIR": CONFIG_DIR, "CLAUDE_CODE_PLUGIN_DIRS": "/tmp/work/b"}, self.temp.name),
                          ({"CLAUDE_CONFIG_DIR": CONFIG_DIR}, self.temp.name)])

    def test_같은_수의_플러그인을_불러온_reload_답은_done이다(self):
        """오류가 없고 활성화 수와 같거나 많이 불러오면 done이며 이전 보고를 지운다."""
        # Given
        self.reload_answer = GOOD_RELOAD

        # When
        entry = self.drive_reload()

        # Then
        self.assertEqual(("done", "applied"), (entry["status"], entry["detail"]))
        self.assertNotIn("plugin_load", entry)


class EnabledCountTest(unittest.TestCase):
    PLUGINS = [{"id": "a", "enabled": True}, {"id": "b", "enabled": False}, {"id": "c", "enabled": True}, "x", {"id": "d"}]

    def run_count(self, session_env):
        caller = {"PATH": "/usr/bin", "CLAUDE_CODE_PLUGIN_DIRS": "/tmp/work/caller", "CLAUDE_CONFIG_DIR": "/home/test/stray"}
        listed = type("Listed", (), {"returncode": 0, "stdout": json.dumps(self.PLUGINS)})()
        with tempfile.TemporaryDirectory() as cwd, patch.dict(os.environ, caller, clear=True), \
                patch.object(refresh_reload.core, "executable", return_value=CLAUDE_PATH), \
                patch.object(refresh_reload.subprocess, "run", return_value=listed) as run:
            count = refresh_reload.enabled_count(session_env, cwd)
        return count, run.call_args.kwargs["env"]

    def test_세션에_없는_플러그인_변수는_호출자의_값을_물려받지_않는다(self):
        """세션 환경에 CLAUDE_CODE_PLUGIN_DIRS가 없으면 호출자 환경에 있어도 하위 프로세스에는 없고, 설정 폴더도 세션 값만 쓴다."""
        # Given
        session_env = {"CLAUDE_CONFIG_DIR": CONFIG_DIR}

        # When
        count, environment = self.run_count(session_env)

        # Then
        self.assertEqual(2, count)
        self.assertNotIn("CLAUDE_CODE_PLUGIN_DIRS", environment)
        self.assertEqual(CONFIG_DIR, environment["CLAUDE_CONFIG_DIR"])
        self.assertEqual("/usr/bin", environment["PATH"])

    def test_세션의_플러그인_변수는_호출자의_값을_덮어쓴다(self):
        """세션 환경에 자기 CLAUDE_CODE_PLUGIN_DIRS가 있으면 하위 프로세스에는 정확히 그 값만 들어간다."""
        # Given
        session_env = {"CLAUDE_CONFIG_DIR": CONFIG_DIR, "CLAUDE_CODE_PLUGIN_DIRS": "/tmp/work/session"}

        # When
        count, environment = self.run_count(session_env)

        # Then
        self.assertEqual(2, count)
        self.assertEqual("/tmp/work/session", environment["CLAUDE_CODE_PLUGIN_DIRS"])

    def test_세션에_설정_폴더가_없으면_호출자의_설정_폴더도_쓰지_않는다(self):
        """세션 환경에 CLAUDE_CONFIG_DIR가 없으면 호출자의 값이 하위 프로세스에 남지 않는다."""
        # Given
        session_env = {}

        # When
        count, environment = self.run_count(session_env)

        # Then
        self.assertNotIn("CLAUDE_CONFIG_DIR", environment)


class ReleaseReportTest(ResumeCase):
    def plan(self):
        return refresh.plan_sessions(self.fake, self.state, "never", [])[0]

    def test_설치된_것보다_오래된_릴리스로_도는_세션은_host_release_outdated로_보고한다(self):
        """세션 실행 파일의 버전 폴더 이름이 설치된 claude보다 숫자로 낮으면 두 버전과 함께 host_release_outdated를 남긴다."""
        # Given
        self.processes.table[self.pid]["exe"] = "/home/test/.local/share/claude/versions/2.1.9"
        self.processes.files.add(self.processes.table[self.pid]["exe"])

        # When
        entry = self.plan()

        # Then
        self.assertEqual("2.1.9", entry["release"])
        self.assertEqual({"running": "2.1.9", "installed": "2.1.314"}, entry["host_release_outdated"])
        self.assertTrue(refresh.public(entry)["resume_approval_needed"])

    def test_실행_파일이_디스크에서_사라진_세션은_host_release_outdated로_보고한다(self):
        """같은 릴리스라도 실행 중인 파일이 없어졌으면 executable_missing과 함께 host_release_outdated를 남긴다."""
        # Given
        self.processes.table[self.pid]["exe"] = NEW_EXE
        self.processes.files.discard(NEW_EXE)

        # When
        entry = self.plan()

        # Then
        self.assertEqual({"running": "2.1.314", "installed": "2.1.314", "executable_missing": True}, entry["host_release_outdated"])

    def test_현재_릴리스로_도는_세션은_릴리스만_기록하고_표시하지_않는다(self):
        """설치된 것과 같은 릴리스면 release만 보고하고 host_release_outdated는 붙이지 않는다."""
        # Given
        self.processes.table[self.pid]["exe"] = NEW_EXE

        # When
        entry = self.plan()

        # Then
        self.assertEqual("2.1.314", entry["release"])
        self.assertNotIn("host_release_outdated", entry)
        self.assertNotIn("resume_approval_needed", refresh.public(entry))

    def test_승인_없이는_어떤_경로도_세션을_끝내지_않는다(self):
        """오래된 릴리스와 로드 오류가 있는 세션도 apply는 reload만 보내고 /exit은 보내지 않으며 보고서에 승인 필요를 적는다."""
        # Given
        self.reload_answer = BAD_RELOAD

        # When
        with patch.object(refresh, "Orca", return_value=self.fake):
            result = refresh.command_apply(self.run_id, "never", [], 60, spawn=lambda run: 1)

        # Then
        self.assertEqual([(HANDLE, "/reload-plugins")], self.fake.sent)
        view = result["sessions"][0]
        self.assertEqual(("failed", "plugin_load_error", True), (view["status"], view["detail"], view["resume_approval_needed"]))
        self.assertIn("host_release_outdated", view)


class ResumeTest(ResumeCase):
    def test_유휴_세션은_같은_터미널에서_세션_ID로_끝내고_다시_연다(self):
        """승인된 유휴 세션은 /exit 뒤 프로세스 환경의 CLAUDE_CONFIG_DIR와 원래 인자(계속/재개 제외, 공백 인자는 따옴표)로 --resume <세션 ID>를 실행하고 표식과 reload로 확인해 done을 보고한다."""
        # Given
        self.processes.table[self.pid]["argv"] = ["claude", "-r", "old-id", *LAUNCH_ARGS[1:]]

        # When
        result = self.resume()

        # Then
        self.assertEqual("/exit", self.fake.sent[0][1])
        expected = (f"CLAUDE_CONFIG_DIR={shlex.quote(CONFIG_DIR)} {CLAUDE_PATH} --plugin-dir {shlex.quote('/tmp/work/agent view')} "
                    f"--dangerously-skip-permissions --resume {SESSION_ID}")
        self.assertEqual((HANDLE, expected), self.fake.sent[1])
        self.assertEqual([(HANDLE, "/reload-plugins")], self.fake.sent[2:])
        view = result["sessions"][0]
        self.assertEqual(("done", "resumed", "2.1.311", "2.1.314"), (view["status"], view["detail"], view["release_before"], view["release_after"]))
        self.assertTrue(result["ok"])
        self.assertEqual("resume", refresh.read_marker(HANDLE)["source"])
        self.assertEqual("done", refresh.load_run(self.run_id)["resumed"][HANDLE]["status"])

    def test_프로세스에_설정_폴더가_없으면_접두어를_빼고_알린다(self):
        """끝난 프로세스에 CLAUDE_CONFIG_DIR가 없으면 접두어 없이 다시 열고 note로 알린다."""
        # Given
        self.processes.table[self.pid]["env"].pop("CLAUDE_CONFIG_DIR")
        self.config_dir = None
        self.resumed_config = None

        # When
        result = self.resume()

        # Then
        self.assertEqual(f"{CLAUDE_PATH} --plugin-dir {shlex.quote('/tmp/work/agent view')} --dangerously-skip-permissions --resume {SESSION_ID}", self.fake.sent[1][1])
        self.assertEqual(("done", "no_config_dir_in_process"), (result["sessions"][0]["status"], result["sessions"][0]["note"]))

    def test_재개한_세션이_다시_로드_오류를_내면_plugin_load_error로_실패한다(self):
        """재개 뒤 reload 답에 로드 오류가 있으면 resumed가 아니라 plugin_load_error로 실패하고 개수를 남긴다."""
        # Given
        self.reload_answer = BAD_RELOAD

        # When
        result = self.resume()

        # Then
        view = result["sessions"][0]
        self.assertEqual(("failed", "plugin_load_error", 5), (view["status"], view["detail"], view["plugin_load"]["plugins"]))
        self.assertFalse(result["ok"])

    def test_프로세스가_끝나지_않으면_exit_timeout으로_실패하고_명령을_더_보내지_않는다(self):
        """/exit 뒤에도 프로세스가 남아 있으면 제한 시간 뒤 exit_timeout으로 실패하고 재개 명령을 보내지 않는다."""
        # Given
        self.hang_on_exit = True

        # When
        result = self.resume()

        # Then
        self.assertEqual([(HANDLE, "/exit")], self.fake.sent)
        self.assertEqual(("failed", "exit_timeout"), (result["sessions"][0]["status"], result["sessions"][0]["detail"]))

    def test_표식이_다시_쓰이지_않으면_resume_marker_missing으로_실패한다(self):
        """재개 명령 뒤 표식이 갱신되지 않으면 resume_marker_missing으로 실패하고 reload를 보내지 않는다."""
        # Given
        self.resumed_source = None

        # When
        result = self.resume()

        # Then
        self.assertEqual(("failed", "resume_marker_missing"), (result["sessions"][0]["status"], result["sessions"][0]["detail"]))
        self.assertNotIn("/reload-plugins", [text for _, text in self.fake.sent])

    def test_표식의_출처나_세션이_다르면_resume_session_mismatch로_실패한다(self):
        """표식이 source resume이 아니거나 다른 대화의 기록을 가리키면 resume_session_mismatch로 실패한다."""
        # Given
        self.resumed_session = "99999999-8888-7777-6666-555555555555"

        # When
        result = self.resume()

        # Then
        self.assertEqual(("failed", "resume_session_mismatch"), (result["sessions"][0]["status"], result["sessions"][0]["detail"]))

    def test_새_프로세스의_설정_폴더가_다르면_config_dir_mismatch로_실패한다(self):
        """재개된 프로세스의 CLAUDE_CONFIG_DIR가 끝난 프로세스와 다르면 config_dir_mismatch로 실패한다."""
        # Given
        self.resumed_config = "/home/test/other"

        # When
        result = self.resume()

        # Then
        self.assertEqual(("failed", "config_dir_mismatch"), (result["sessions"][0]["status"], result["sessions"][0]["detail"]))


class LaunchArgumentsTest(ResumeCase):
    def test_위치_인자_프롬프트는_재개_줄에서_빼고_값_옵션은_모두_남긴다(self):
        """처음 실행에 붙은 프롬프트는 다시 보내지 않고, 여러 값을 받는 --add-dir의 값과 충돌하는 --session-id/--fork-session은 줄에 넣지 않는다."""
        # Given
        self.processes.table[self.pid]["argv"] = ["claude", "--session-id", SESSION_ID, "--add-dir", "/tmp/work/a", "/tmp/work/b",
                                                  "--fork-session", "빌드해줘"]

        # When
        result = self.resume()

        # Then
        self.assertEqual(f"CLAUDE_CONFIG_DIR={shlex.quote(CONFIG_DIR)} {CLAUDE_PATH} --add-dir /tmp/work/a /tmp/work/b --resume {SESSION_ID}",
                         self.fake.sent[1][1])
        self.assertEqual("done", result["sessions"][0]["status"])

    def test_도움말에_없는_옵션이_있으면_세션을_끝내지_않고_건너뛴다(self):
        """실행 인자에 도움말 표에 없는 옵션이 있으면 launch_arguments_unknown으로 건너뛰고 /exit도 보내지 않는다."""
        # Given
        self.processes.table[self.pid]["argv"] = ["claude", "--brand-new-option", "value"]

        # When
        result = self.resume()

        # Then
        self.assertEqual([], self.fake.sent)
        self.assertEqual(("skipped", "launch_arguments_unknown"), (result["sessions"][0]["status"], result["sessions"][0]["detail"]))

    def test_도움말을_얻지_못하면_세션을_끝내지_않고_건너뛴다(self):
        """claude --help 출력을 얻지 못하면 값과 프롬프트를 가를 수 없으므로 launch_arguments_unknown으로 건너뛰고 아무것도 보내지 않는다."""
        # Given
        self.processes.help_text = None

        # When
        result = self.resume()

        # Then
        self.assertEqual([], self.fake.sent)
        self.assertEqual("launch_arguments_unknown", result["sessions"][0]["detail"])


class NeverEndedTest(ResumeCase):
    def assert_kept(self, result, detail):
        self.assertEqual([], self.exits())
        self.assertEqual([], self.fake.sent)
        self.assertEqual(("skipped", detail), (result["sessions"][0]["status"], result["sessions"][0]["detail"]))

    def test_턴이_진행_중인_세션은_승인돼도_끝내지_않는다(self):
        """마지막 턴이 끝나지 않은 세션은 busy로 건너뛰고 아무것도 보내지 않는다."""
        # Given
        write_records(self.transcript, RUNNING_TURN)

        # When
        result = self.resume()

        # Then
        self.assert_kept(result, "busy")

    def test_입력창에_글이_있는_세션은_승인돼도_끝내지_않는다(self):
        """입력창에 쓰던 글이 있으면 unsent_input으로 건너뛰고 글을 지우거나 명령을 보내지 않는다."""
        # Given
        self.fake.typed[HANDLE] = "쓰던 질문"
        self.fake.screens[HANDLE] = base.CLAUDE_EMPTY[:3] + ["❯ 쓰던 질문"] + base.CLAUDE_EMPTY[4:]

        # When
        result = self.resume()

        # Then
        self.assert_kept(result, "unsent_input")

    def test_도구_승인이나_질문을_기다리는_세션은_승인돼도_끝내지_않는다(self):
        """마지막 기록이 답이 없는 도구 호출이면 승인 대기로 보아 busy로 건너뛴다."""
        # Given
        write_records(self.transcript, [*FINISHED_TURN, user_record("실행해줘"), assistant_record(tool_use("AskUserQuestion", question="계속할까요?"))])

        # When
        result = self.resume()

        # Then
        self.assert_kept(result, "busy")

    def test_입력창이_없는_대화상자_화면의_세션은_승인돼도_끝내지_않는다(self):
        """기록은 유휴여도 화면에 입력창 대신 대화상자가 떠 있으면 input_unknown으로 건너뛴다."""
        # Given
        self.fake.screens[HANDLE] = ["Do you want to proceed?", "❯ 1. Yes", "  2. No"]

        # When
        result = self.resume()

        # Then
        self.assert_kept(result, "input_unknown")

    def test_백그라운드_작업이_알림을_남긴_세션은_끝내지_않고_background_task로_알린다(self):
        """턴은 끝났어도 백그라운드 작업이 알림을 남겼다면 끝내면 멈추므로 건너뛰고 background_task를 보고한다."""
        # Given
        launched = result_record("Command running in background with ID: bg1")
        write_records(self.transcript, [user_record("빌드"), assistant_record(tool_use("Bash", command="make", run_in_background=True)), launched, turn_end()])

        # When
        result = self.resume()

        # Then
        self.assert_kept(result, "background_task")

    def test_세션_ID를_알_수_없는_세션은_끝내지_않는다(self):
        """표식에 기록 경로가 없어 세션 ID를 알 수 없으면 session_id_unknown으로 건너뛴다."""
        # Given
        marker = refresh.read_marker(HANDLE)
        marker.pop("transcript_path")
        (refresh.SESSION_CONTEXT.marker_directory() / f"{HANDLE}.json").write_text(json.dumps(marker))

        # When
        result = self.resume()

        # Then
        self.assert_kept(result, "session_id_unknown")

    def test_승인한_터미널이_아닌_세션은_건드리지_않는다(self):
        """resume은 이름 붙인 터미널만 대상으로 하고 Claude 세션이 아닌 터미널은 not_a_claude_session으로 건너뛴다."""
        # Given
        other = "term_shell"
        self.fake.list.append(terminal(other, None))

        # When
        with patch.object(refresh_resume, "Orca", return_value=self.fake):
            result = refresh_resume.run_resume(self.run_id, [other], sleep=lambda seconds: None)

        # Then
        self.assertEqual([], self.fake.sent)
        self.assertEqual("not_a_claude_session", result["sessions"][0]["detail"])


class ProcessLookupTest(unittest.TestCase):
    def table(self, *items):
        processes = FakeProcesses()
        for item in items:
            processes.add(*item[:4], **item[4])
        return processes

    def test_터미널_핸들이_같은_대화형_프로세스만_찾는다(self):
        """ORCA_TERMINAL_HANDLE이 같은 프로세스 중 다른 진입점이나 print 모드 자식은 제외하고 대화형 하나를 찾는다."""
        # Given
        processes = self.table(
            (HANDLE, ["claude", "-p", "--session-id", "x"], NEW_EXE, CONFIG_DIR, {"entrypoint": "cli"}),
            (HANDLE, ["claude"], NEW_EXE, CONFIG_DIR, {"entrypoint": "sdk-cli"}),
            ("term_other", ["claude"], NEW_EXE, CONFIG_DIR, {}),
            (HANDLE, ["claude", "--plugin-dir", "/tmp/work/a b"], OLD_EXE, CONFIG_DIR, {}),
            (HANDLE, ["python"], NEW_EXE, CONFIG_DIR, {"comm": "python"}),
        )

        # When
        found = refresh_process.find_session_process(HANDLE, processes.system())

        # Then
        self.assertEqual(("claude", "--plugin-dir", "/tmp/work/a b"), found.argv)
        self.assertEqual((OLD_EXE, CONFIG_DIR), (found.exe, found.config_dir))

    def test_대화형_프로세스가_둘_이상이면_모호하다고_멈춘다(self):
        """같은 핸들을 주장하는 대화형 프로세스가 둘이면 어느 쪽도 끝내지 않도록 오류를 낸다."""
        # Given
        processes = self.table((HANDLE, ["claude"], NEW_EXE, None, {}), (HANDLE, ["claude"], NEW_EXE, None, {}))

        # When / Then
        with self.assertRaises(refresh.RefreshError) as caught:
            refresh_process.find_session_process(HANDLE, processes.system())
        self.assertEqual("session_process_ambiguous", caught.exception.code)

    def test_릴리스는_실행_파일_또는_버전_폴더_이름에서_숫자로_비교한다(self):
        """버전 파일이나 폴더 이름에서 릴리스를 읽고 삭제 표시는 무시하며 2.1.9가 2.1.311보다 낮게 비교한다."""
        # Given
        paths = [OLD_EXE, "/home/test/.local/share/claude/versions/2.1.311/claude", OLD_EXE + " (deleted)", "/usr/bin/claude", None]

        # When
        releases = [refresh_process.release_of(path) for path in paths]

        # Then
        self.assertEqual(["2.1.311", "2.1.311", "2.1.311", None, None], releases)
        self.assertLess(refresh_process.release_key("2.1.9"), refresh_process.release_key("2.1.311"))

    def test_설치된_릴리스는_링크를_푼_경로에서_읽고_없으면_버전_출력을_쓴다(self):
        """PATH의 claude가 가리키는 버전 이름을 쓰고, 이름에서 알 수 없으면 --version 출력의 첫 버전을 쓴다."""
        # Given
        by_link = ProcessOs(which=lambda name: CLAUDE_PATH, realpath=lambda path: NEW_EXE, version_text=lambda path: None)
        by_output = ProcessOs(which=lambda name: CLAUDE_PATH, realpath=lambda path: "/opt/claude/bin/claude",
                                              version_text=lambda path: "2.1.320 (Claude Code)\n")

        # When
        observed = [refresh_process.installed_release(by_link), refresh_process.installed_release(by_output)]

        # Then
        self.assertEqual([("2.1.314", CLAUDE_PATH), ("2.1.320", CLAUDE_PATH)], observed)

    def test_재개_인자는_값을_가진_옵션만_남기고_프롬프트와_충돌하는_옵션을_뺀다(self):
        """도움말 표의 인자 수대로 값을 묶어, 위치 인자 프롬프트와 계속/재개/세션 ID/분기/print 옵션은 빼고 공백이 든 값은 그대로 둔다."""
        # Given
        table = refresh_process.option_table(HELP)
        argv = ["claude", "-c", "--resume", "old", "--session-id", "x", "--fork-session", "-p", "--model=m", "--plugin-dir", "/tmp/work/a b",
                "--add-dir", "a", "b", "-d", "hooks", "--allowed-tools", "Bash", "Edit", "--dangerously-skip-permissions", "-r", "고쳐줘"]

        # When
        kept = refresh_process.relaunch_arguments(argv, table)

        # Then
        self.assertEqual(["--model=m", "--plugin-dir", "/tmp/work/a b", "--add-dir", "a", "b", "-d", "hooks",
                          "--allowed-tools", "Bash", "Edit", "--dangerously-skip-permissions"], kept)

    def test_선택값_옵션은_다음_토큰이_옵션이_아닐_때만_값으로_본다(self):
        """`[value]` 옵션은 다음 토큰이 `-`로 시작하면 값 없이 플래그로, 아니면 한 토큰만 값으로 가져가고 나머지 위치 인자는 뺀다."""
        # Given
        table = refresh_process.option_table(HELP)

        # When
        kept = [refresh_process.relaunch_arguments(argv, table) for argv in (
            ["claude", "-d", "--model", "m", "prompt"], ["claude", "--debug", "hooks", "prompt", "--model", "m"], ["claude", "--", "-p"])]

        # Then
        self.assertEqual([["-d", "--model", "m"], ["--debug", "hooks", "--model", "m"], []], kept)

    def test_도움말_표에_없는_옵션이나_빈_표는_알_수_없음으로_본다(self):
        """표에 없는 옵션이 있거나 도움말을 얻지 못해 표가 비면 값과 프롬프트를 가를 수 없으므로 None을 돌려준다."""
        # Given
        table = refresh_process.option_table(HELP)

        # When
        observed = [refresh_process.relaunch_arguments(["claude", "--new-flag", "x"], table),
                    refresh_process.relaunch_arguments(["claude", "--model", "m"], refresh_process.option_table(None))]

        # Then
        self.assertEqual([None, None], observed)

    def test_도움말의_짧은_별칭은_긴_옵션과_같은_인자_수를_가진다(self):
        """`-r, --resume [value]`처럼 함께 적힌 별칭은 같은 인자 수로 읽고, 줄을 바꿔 적힌 설명과 명령 목록은 옵션으로 읽지 않는다."""
        # Given / When
        table = refresh_process.option_table(HELP)

        # Then
        self.assertEqual({"-r": "optional", "--resume": "optional", "--add-dir": "many", "--allowed-tools": "many", "--allowedTools": "many",
                          "--model": "one", "-c": "flag", "-d": "optional"}, {name: table[name] for name in (
                              "-r", "--resume", "--add-dir", "--allowed-tools", "--allowedTools", "--model", "-c", "-d")})
        self.assertNotIn("agents", table)

    def test_KERN_PROCARGS2_버퍼에서_argv와_환경을_정확히_나눈다(self):
        """argc, 실행 경로, 패딩, 공백이 든 argv, 환경 문자열을 있는 그대로 분리한다."""
        # Given
        data = struct.pack("=i", 3) + b"/opt/claude\0\0\0" + b"claude\0--plugin-dir\0/tmp/work/a b\0" + b"HOME=/home/test\0A=b=c\0\0"

        # When
        parsed = refresh_process.parse_procargs2(data)

        # Then
        self.assertEqual((["claude", "--plugin-dir", "/tmp/work/a b"], {"HOME": "/home/test", "A": "b=c"}), parsed)

    def test_현재_프로세스의_argv와_실행_파일을_운영체제에서_그대로_읽는다(self):
        """이 컴퓨터의 운영체제 호출로 자기 프로세스의 argv와 환경 변수, 실행 파일 경로를 읽어 파이썬이 아는 값과 맞춘다."""
        # Given
        read = ProcessOs()

        # When
        args = read.read_args(os.getpid())

        # Then
        self.assertIsNotNone(args)
        self.assertEqual(list(sys.orig_argv), args[0])
        self.assertIn("PATH", args[1])
        self.assertTrue(os.path.exists(read.exe_path(os.getpid())))


if __name__ == "__main__":
    unittest.main()
