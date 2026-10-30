from __future__ import annotations

import dataclasses
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_orca_plugin_refresh as base
import test_refresh_compact_dialog as dialog_tests
import test_refresh_orphaned as orphan_tests
import test_refresh_resume as resume_tests
from test_refresh_compact_dialog import CompactDialogTest as DialogBase
from test_refresh_orphaned import OrphanCase as OrphanBase
from test_refresh_resume import ResumeCase as ResumeBase
from test_orca_plugin_refresh import FINISHED_TURN, RUNNING_TURN, FakeOrca, refresh, terminal, write_records

import refresh_core
import refresh_follow
from refresh_feed import RunFeed
import refresh_orphans
import refresh_process
import refresh_resume
import refresh_sessions

HANDLE = resume_tests.HANDLE


def setUpModule():
    base.setUpModule()


def tearDownModule():
    base.tearDownModule()


class FakeClock:
    """A clock that only moves when a test sleeps, so a long timeout passes without waiting."""

    def __init__(self, start=1000.0):
        self.now = start

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class ResumeRecheckTest(ResumeBase):
    def ps_output(self, *args, **kwargs):
        lines = "".join(f"{pid} {item['comm']}\n" for pid, item in self.processes.table.items())
        return subprocess.CompletedProcess(args, 0, lines, "")

    def test_탐색_중에_바빠진_세션에는_exit를_보내지_않는다(self):
        """프로세스와 claude 탐색이 끝난 뒤 세션이 바빠졌으면 /exit 직전의 재확인이 busy로 건너뛰고 아무것도 보내지 않는다."""
        # Given
        real_launch_arguments = refresh_resume.launch_arguments

        def busy_during_discovery(claude, argv, system):
            write_records(self.transcript, FINISHED_TURN + RUNNING_TURN)
            return real_launch_arguments(claude, argv, system)

        # When
        with patch.object(refresh_resume, "launch_arguments", busy_during_discovery):
            result = self.resume()

        # Then
        self.assertEqual(("skipped", "busy"), (result["sessions"][0]["status"], result["sessions"][0]["detail"]))
        self.assertEqual([], self.fake.sent)

    def test_exit_뒤_프로세스_목록을_읽지_못하면_종료로_보지_않고_재개_명령을_보내지_않는다(self):
        """/exit 뒤 ps가 실패하면 종료 여부를 알 수 없으므로 exit_timeout까지 기다리고 재개 줄을 보내지 않는다."""
        # Given
        system = dataclasses.replace(self.processes.system(), list_processes=refresh_process.list_processes)
        self.processes.system = lambda: system
        self.hang_on_exit = True

        def run(argv, **kwargs):
            if self.exits():
                raise OSError("ps unavailable")
            return self.ps_output(argv)

        # When
        with patch.object(refresh_process.subprocess, "run", run):
            result = self.resume()

        # Then
        self.assertEqual([(HANDLE, "/exit")], self.fake.sent)
        self.assertEqual(("failed", "exit_timeout"), (result["sessions"][0]["status"], result["sessions"][0]["detail"]))

    def test_exit_뒤_인자를_읽을_수_없는_프로세스가_남아_있으면_종료로_보지_않는다(self):
        """/exit 뒤 같은 PID의 인자를 읽지 못하면 살아 있는 세션일 수 있으므로 exit_timeout으로 끝내고 재개 줄을 보내지 않는다."""
        # Given
        system = self.processes.system()
        readable = system.read_args
        self.processes.system = lambda: dataclasses.replace(system, read_args=lambda pid: None if self.exits() else readable(pid))
        self.hang_on_exit = True

        # When
        result = self.resume()

        # Then
        self.assertEqual([(HANDLE, "/exit")], self.fake.sent)
        self.assertEqual(("failed", "exit_timeout"), (result["sessions"][0]["status"], result["sessions"][0]["detail"]))

    def test_ps가_실패하면_프로세스_목록_오류를_올린다(self):
        """ps를 실행하지 못하거나 비정상 종료하면 빈 목록이 아니라 process_list_failed 오류를 올린다."""
        # Given
        failed = subprocess.CompletedProcess(["ps"], 1, "", "")

        # When
        with patch.object(refresh_process.subprocess, "run", return_value=failed):
            with self.assertRaises(refresh_core.RefreshError) as caught:
                refresh_process.list_processes()

        # Then
        self.assertEqual("process_list_failed", caught.exception.code)


class DialogDeadlineTest(DialogBase):
    def test_Run을_확인한_뒤에도_대화상자가_열려_있으면_제한_시간_뒤_더_보내지_않고_실패로_끝낸다(self):
        """Enter 뒤에도 대화상자가 compact 제한 시간이 지나도록 남아 있으면 compact_dialog_open으로 끝내고 키를 더 보내지 않는다."""
        # Given
        clock = FakeClock()
        fake = self.dialog_fake(dialog_tests.dialog_screen(dialog_tests.RUN))
        fake.on_keys = lambda *args: None
        sessions = self.session(fake)

        # When
        with patch.object(refresh_sessions, "time", SimpleNamespace(time=clock.time, sleep=clock.sleep)):
            refresh.drive(fake, sessions, self.state, clock.now + 10**6, sleep=lambda seconds: clock.sleep(100))

        # Then
        self.assertEqual(("failed", "compact_dialog_open"), (sessions[0]["status"], sessions[0]["detail"]))
        self.assertEqual([(HANDLE, dialog_tests.ENTER)], fake.keystrokes)
        self.assertEqual([(HANDLE, "/compact")], fake.sent)


class OrphanCloseMergeTest(OrphanBase):
    def test_닫는_동안_도우미가_쓴_결과는_closed_저장_뒤에도_남는다(self):
        """close가 실행 상태를 읽은 뒤 도우미가 sessions를 갱신해도 closed만 합쳐 저장하므로 그 결과가 지워지지 않는다."""
        # Given
        self.session(orphan_tests.CLAUDE, "claude", FINISHED_TURN)
        fake = orphan_tests.OrphanFake([orphan_tests.orphan(orphan_tests.CLAUDE, "claude")])
        close = fake.close

        def close_and_write(handle):
            close(handle)
            refresh_core.update_run(self.run_id, lambda saved: {**saved, "sessions": {"term_x": {"status": "done"}}})

        fake.close = close_and_write

        # When
        report = self.close(fake, [orphan_tests.CLAUDE])

        # Then
        saved = refresh_core.load_run(self.run_id)
        self.assertEqual({"term_x": {"status": "done"}}, saved["sessions"])
        self.assertEqual(["closed"], [item["status"] for item in saved["closed"].values()])
        self.assertTrue(report["ok"])


class HandedCompactModeTest(base.DriveTest):
    def test_나중_apply의_compact_always는_도우미의_처음_모드가_auto여도_유지된다(self):
        """도우미가 auto로 시작한 뒤 apply --compact always가 넘긴 항목은 자기 모드를 지녀 최신 표식이어도 compact를 유지한다."""
        # Given
        self.write_marker("term_claude", "claude")
        fake = FakeOrca([terminal("term_claude", "claude")], busy={"term_claude": 10**9})
        run_id = "d" * 32
        refresh.save_json(refresh.run_path(run_id), {**self.state, "run_id": run_id, "compact_mode": "auto"})
        helper_state = {**self.state, "compact_mode": "auto"}

        # When
        with patch.object(refresh, "Orca", return_value=fake):
            refresh.command_apply(run_id, "always", [], 0, spawn=lambda run: 1)
        entry = RunFeed(run_id, 3600.0, 3600.0).poll()[0]
        refresh_follow.still_needed(entry, helper_state, {})

        # Then
        self.assertEqual("always", entry["compact_mode"])
        self.assertIn("compact", entry["actions"])


class ArgvSplitTest(unittest.TestCase):
    def test_cmdline의_중간_빈_인자는_보존하고_끝_종결자_하나만_뗀다(self):
        """리눅스 cmdline에서 빈 인자를 지키지 않으면 값이 앞당겨져 재실행 인자가 어긋나므로 중간과 마지막 빈 인자를 모두 남긴다."""
        # Given
        cmdline = b"claude\0--append-system-prompt\0\0--model\0m\0\0"
        environ = b"A=1\0\0B=\0"
        files = {"/proc/7/cmdline": cmdline, "/proc/7/environ": environ}

        # When
        with patch.object(refresh_process, "Path", lambda path: SimpleNamespace(read_bytes=lambda: files[path])):
            argv, env = refresh_process.read_args_linux(7)

        # Then
        self.assertEqual(["claude", "--append-system-prompt", "", "--model", "m", ""], argv)
        self.assertEqual({"A": "1", "B": ""}, env)

    def test_빈_값을_가진_옵션은_재실행_줄에서도_빈_따옴표로_남는다(self):
        """값이 빈 문자열인 옵션은 재실행 인자에 그대로 남아 셸 줄에서 빈 따옴표가 된다."""
        # Given
        argv = refresh_process.split_argv(b"claude\0--model\0\0--plugin-dir\0/tmp/work\0")
        table = refresh_process.option_table(resume_tests.HELP)

        # When
        arguments = refresh_process.relaunch_arguments(argv, table)

        # Then
        self.assertEqual(["--model", "", "--plugin-dir", "/tmp/work"], arguments)
        self.assertEqual("claude --model '' --plugin-dir /tmp/work --resume abc", refresh_resume.resume_line("claude", None, arguments, "abc"))

    def test_빈_cmdline은_빈_목록이다(self):
        """읽은 바이트가 비면 빈 문자열 하나가 아니라 빈 목록을 돌려준다."""
        # Given
        data = b""

        # When
        argv = refresh_process.split_argv(data)

        # Then
        self.assertEqual([], argv)


del DialogBase, OrphanBase, ResumeBase


if __name__ == "__main__":
    unittest.main()
