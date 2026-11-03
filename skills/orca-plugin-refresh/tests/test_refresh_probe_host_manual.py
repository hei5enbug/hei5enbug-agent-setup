from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_orca_plugin_refresh as base
import test_refresh_resume as resume_tests
from test_orca_plugin_refresh import CLAUDE_EMPTY, FakeOrca, refresh, terminal
from test_refresh_resume import HANDLE, ResumeCase

import refresh_core
import refresh_process
import refresh_resume
import refresh_sessions

SHELL_SCREEN = ["Resume this session with:", "claude --resume 11111111-2222-3333-4444-555555555555", "demo@example ~ %"]
UNDECIDED_SCREEN = ["Welcome back", "loading the workspace"]


def setUpModule():
    base.setUpModule()


def tearDownModule():
    base.tearDownModule()


class FakeClock:
    """A clock that moves on every read and every sleep, so a settle loop ends without waiting."""

    def __init__(self, start=1000.0):
        self.now = start

    def time(self):
        self.now += 0.5
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class CursorOrca(FakeOrca):
    """A fake Orca whose input line keeps a cursor, so a typed character lands where the cursor is."""

    def __init__(self, *args, cursor, stuck=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.cursor = cursor
        self.stuck = stuck

    def keys(self, handle, text):
        self.keystrokes.append((handle, text))
        current, at = self.typed.get(handle, ""), self.cursor
        if text == refresh.BACKSPACE:
            if self.stuck:
                return
            self.typed[handle], self.cursor = current[:at - 1] + current[at:], at - 1
        else:
            self.typed[handle], self.cursor = current[:at] + text + current[at:], at + len(text)
        if getattr(self, "on_keys", None):
            self.on_keys(self, handle, text)


class ProbeInterruptedTest(unittest.TestCase):
    TYPED = "첫 문장. 둘째 문장"

    def setUp(self):
        self.clock = FakeClock()
        patcher = patch.object(refresh_sessions, "time", SimpleNamespace(time=self.clock.time, sleep=self.clock.sleep))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_커서가_글_중간이면_확인_글자만_지우고_입력은_그대로_둔다(self):
        """확인 글자가 글 중간에 끼어 들어가도 그 글자 하나만 백스페이스로 지우고, 쓰던 글을 입력으로 판정한다."""
        # Given
        fake = CursorOrca([terminal("term_claude", "claude")], typed={"term_claude": self.TYPED}, cursor=5)
        trace: dict = {}

        # When
        verdict = refresh.claude_draft_state(fake, "term_claude", self.TYPED, self.clock.sleep, trace)

        # Then
        self.assertEqual("text", verdict)
        self.assertEqual(self.TYPED, fake.draft("term_claude"))
        self.assertEqual([refresh.PROBE_KEY, refresh.BACKSPACE], [text for _, text in fake.keystrokes])
        self.assertEqual({}, trace)

    def test_글자를_지우지_못하면_남은_글자의_위치를_알려_준다(self):
        """확인 글자가 글 중간에 남고 지워지지 않으면 일반 건너뜀이 아니라 남은 글자의 1부터 센 위치와 함께 probe_character_left로 실패한다."""
        # Given
        fake = CursorOrca([terminal("term_claude", "claude")], typed={"term_claude": self.TYPED}, cursor=5, stuck=True)
        entry = {"handle": "term_claude", "host": "claude", "status": "pending", "actions": ["reload"], "draft_seen": (self.TYPED, 0.0)}
        live = {"term_claude": terminal("term_claude", "claude")}

        # When
        with patch.object(refresh_sessions, "read_marker", return_value=None):
            refresh.step(fake, entry, {}, live)

        # Then
        self.assertEqual(("failed", "probe_character_left", 6), (entry["status"], entry["detail"], entry["probe_position"]))
        self.assertEqual("첫 문장.x 둘째 문장", fake.draft("term_claude"))
        self.assertEqual([], fake.sent)
        self.assertEqual(6, refresh.public({**entry, "handle": "term_claude"})["probe_position"])

    def test_확인_중_초안이_다른_글로_바뀌면_위치를_주장하지_않고_지우지도_않는다(self):
        """확인 글자 말고도 초안이 바뀌어 위치를 알 수 없으면 키를 더 보내지 않고 probe_interrupted_check_input으로 알린다."""
        # Given
        fake = CursorOrca([terminal("term_claude", "claude")], typed={"term_claude": self.TYPED}, cursor=len(self.TYPED))

        def user_edits(fake, handle, text):
            fake.typed[handle] = "다른 글"
        fake.on_keys = user_edits
        entry = {"handle": "term_claude", "host": "claude", "status": "pending", "actions": ["reload"], "draft_seen": (self.TYPED, 0.0)}
        live = {"term_claude": terminal("term_claude", "claude")}

        # When
        with patch.object(refresh_sessions, "read_marker", return_value=None):
            refresh.step(fake, entry, {}, live)

        # Then
        self.assertEqual(("failed", "probe_interrupted_check_input"), (entry["status"], entry["detail"]))
        self.assertNotIn("probe_position", entry)
        self.assertEqual([("term_claude", refresh.PROBE_KEY)], fake.keystrokes)


class SequencedScreens(FakeOrca):
    """A fake Orca whose screen reads come from a fixed sequence, the last one repeating."""

    def __init__(self, terminals, sequence):
        super().__init__(terminals)
        self.sequence = list(sequence)
        self.reads = 0

    def screen(self, handle):
        index = min(self.reads, len(self.sequence) - 1)
        self.reads += 1
        return list(self.sequence[index]), None


class HostIdentificationTest(ResumeCase):
    def setUp(self):
        super().setUp()
        for name, value in (("SCREEN_REREAD_SECONDS", 0), ("session_process_present", refresh_process.session_process_present)):
            patcher = patch.object(refresh_sessions, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def plan(self, fake):
        return refresh.plan_sessions(fake, self.state, "never", [])

    def test_결정되지_않은_화면_뒤에서_Claude_프로세스가_돌면_Claude_세션으로_본다(self):
        """Orca가 agentIdentity를 기록하지 않고 화면도 호스트를 가리지 못해도, 터미널 핸들을 가진 Claude Code 프로세스가 있으면 건너뛰지 않고 세션으로 계획한다."""
        # Given
        fake = SequencedScreens([terminal(HANDLE, None)], [UNDECIDED_SCREEN])

        # When
        sessions = self.plan(fake)

        # Then
        self.assertEqual(["claude"], [entry["host"] for entry in sessions])
        self.assertTrue(sessions[0]["screen_identified"])
        self.assertGreater(fake.reads, 1)

    def test_첫_화면이_결정되지_않아도_다시_읽어_호스트가_드러나면_프로세스를_보지_않는다(self):
        """처음 읽은 화면이 미정이어도 다시 읽은 화면이 Claude 입력창으로 끝나면 그 호스트로 보고 프로세스 목록은 읽지 않는다."""
        # Given
        fake = SequencedScreens([terminal(HANDLE, None)], [UNDECIDED_SCREEN, CLAUDE_EMPTY])

        # When
        with patch.object(refresh_sessions, "session_process_present", side_effect=AssertionError("not needed")):
            sessions = self.plan(fake)

        # Then
        self.assertEqual(["claude"], [entry["host"] for entry in sessions])

    def test_프로세스가_없는_낡은_표식의_터미널은_세션으로_보지_않는다(self):
        """화면이 미정이고 그 터미널에 Claude Code 프로세스가 없으면 남은 표식만으로 세션이 되지 않는다."""
        # Given
        self.processes.table.pop(self.pid)
        fake = SequencedScreens([terminal(HANDLE, None)], [SHELL_SCREEN])

        # When
        sessions = self.plan(fake)

        # Then
        self.assertEqual([], sessions)

    def test_화면이_다른_호스트를_가리키면_프로세스가_있어도_세션으로_보지_않는다(self):
        """화면이 Codex 입력창으로 끝나면 Claude 표식과 프로세스가 있어도 Claude 세션으로 보지 않는다."""
        # Given
        fake = SequencedScreens([terminal(HANDLE, None)], [base.CODEX_EMPTY])

        # When
        sessions = self.plan(fake)

        # Then
        self.assertEqual([], sessions)


class LateExitTest(ResumeCase):
    def setUp(self):
        super().setUp()
        for module, name, value in ((refresh_resume, "LATE_EXIT_TIMEOUT", 3.0), (refresh_resume, "EXIT_TIMEOUT", 0.05)):
            patcher = patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.exited_at = None
        self.ends_after = 0.15
        self.shell_screen = SHELL_SCREEN
        real = self.processes.system()
        self.process_list_error = False

        def listing():
            if self.exited_at is not None and self.process_list_error:
                raise refresh_core.RefreshError("process_list_failed", "unreadable")
            alive = self.exited_at is None or time.time() - self.exited_at < self.ends_after
            return [(pid, item["comm"]) for pid, item in self.processes.table.items() if alive or pid != self.pid]
        self.processes.system = lambda: dataclasses.replace(real, list_processes=listing)
        inner = self.fake.on_send

        def late_simulate(fake, handle, text):
            if text == "/exit":
                self.exited_at = time.time()
                fake.screens[handle] = list(self.shell_screen)
                return
            inner(fake, handle, text)
        self.fake.on_send = late_simulate

    def test_첫_대기_뒤에_끝난_프로세스는_셸_프롬프트가_보이면_재개_줄을_보낸다(self):
        """/exit 대기 시간이 지난 뒤 프로세스가 끝나고 터미널이 빈 셸 프롬프트를 보이면 재개 줄을 한 번 보내 같은 대화를 다시 연다."""
        # Given
        inner = self.fake.on_send

        def resumed(fake, handle, text):
            inner(fake, handle, text)
            if "--resume" in text:
                fake.screens[handle] = list(base.CLAUDE_EMPTY)
        self.fake.on_send = resumed

        # When
        result = self.resume()

        # Then
        view = result["sessions"][0]
        self.assertEqual(("done", "resumed", True), (view["status"], view["detail"], view["exit_late"]))
        self.assertEqual(["/exit"], [text for _, text in self.fake.sent[:1]])
        self.assertEqual(1, sum(1 for _, text in self.fake.sent if "--resume" in text))

    def test_프로세스가_늦게_끝나도_프롬프트가_없으면_터미널과_재개_줄을_알린다(self):
        """프로세스는 끝났지만 터미널에 빈 셸 프롬프트가 없으면 재개 줄을 보내지 않고 터미널 핸들, 정확한 재개 줄, 늦게 끝났다는 사실을 알린다."""
        # Given
        self.shell_screen = ["Resume this session with:", "$ claude --resume x --flag"]

        # When
        result = self.resume()

        # Then
        view = result["sessions"][0]
        self.assertEqual([(HANDLE, "/exit")], self.fake.sent)
        self.assertEqual(("failed", "exit_timeout", "ended_late", HANDLE), (view["status"], view["detail"], view["exit_state"], view["terminal_handle"]))
        self.assertIn(f"--resume {resume_tests.SESSION_ID}", view["resume_line"])
        self.assertTrue(view["resume_line"].startswith("CLAUDE_CONFIG_DIR="))

    def test_프로세스가_계속_남아_있으면_still_running으로_알린다(self):
        """추가 대기 뒤에도 프로세스가 남아 있으면 재개 줄을 보내지 않고 still_running과 재개 줄을 알린다."""
        # Given
        self.ends_after = 10**6

        # When
        result = self.resume()

        # Then
        view = result["sessions"][0]
        self.assertEqual([(HANDLE, "/exit")], self.fake.sent)
        self.assertEqual(("exit_timeout", "still_running"), (view["detail"], view["exit_state"]))

    def test_프로세스_목록을_읽을_수_없으면_읽지_못했다고_알린다(self):
        """추가 대기 동안 프로세스 목록을 읽지 못하면 끝난 것으로 보지 않고 process_list_unreadable과 재개 줄을 알린다."""
        # Given
        self.process_list_error = True

        # When
        result = self.resume()

        # Then
        view = result["sessions"][0]
        self.assertEqual([(HANDLE, "/exit")], self.fake.sent)
        self.assertEqual(("exit_timeout", "process_list_unreadable", HANDLE), (view["detail"], view["exit_state"], view["terminal_handle"]))


class RecordManualTest(unittest.TestCase):
    RUN = "c" * 32

    def setUp(self):
        import tempfile
        import os
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {"XDG_STATE_HOME": self.temp.name})
        env.start()
        self.addCleanup(env.stop)
        views = {
            "term_skipped": {"terminal": "…skippe", "host": "claude", "status": "skipped", "detail": "not_a_claude_session", "actions": ["reload", "compact"]},
            "term_resume": {"terminal": "…resume", "host": "claude", "status": "skipped", "detail": "input_unknown", "host_release_outdated": {"running": "2.1.9"},
                            "resume_approval_needed": True},
            "term_done": {"terminal": "…done00", "host": "claude", "status": "done", "detail": "applied"},
            "term_cleared": {"terminal": "…clear0", "host": "claude", "status": "skipped", "detail": "input_changed",
                             "planned": ["reload", "compact"]},
        }
        refresh.save_json(refresh.run_path(self.RUN), {"run_id": self.RUN, "hosts": {}, "sessions": views})

    def record(self, *extra):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = refresh.main(["record-manual", "--run-id", self.RUN, *extra, "--json"])
        return code, json.loads(output.getvalue())

    def status(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            refresh.main(["status", "--run-id", self.RUN, "--json"])
        return json.loads(output.getvalue())

    def test_손으로_끝낸_동작은_status와_not_refreshed에_반영된다(self):
        """건너뛴 세션의 남은 동작을 모두 손으로 끝내고 기록하면 마지막 기록에서 done이 되어 not_refreshed에서 빠지고 완료 동작이 남는다."""
        # Given
        before = self.status()

        # When
        first = self.record("--terminal", "term_skipped", "--action", "reload", "--result", "done")
        middle = self.status()
        second = self.record("--terminal", "term_skipped", "--action", "compact", "--result", "done")
        after = self.status()

        # Then
        self.assertEqual(3, len(before["not_refreshed"]))
        self.assertEqual(("skipped", ["compact"]), (first[1]["session"]["status"], first[1]["session"]["actions"]))
        self.assertEqual(3, len(middle["not_refreshed"]))
        self.assertEqual(("done", "applied_by_agent", ["reload", "compact"], True),
                         tuple(second[1]["session"][key] for key in ("status", "detail", "completed", "manual")))
        self.assertEqual(2, len(after["not_refreshed"]))

    def test_손으로_한_재개는_승인_필요_표시를_지우고_resumed에_남는다(self):
        """재개를 손으로 끝내고 기록하면 resume_approval_needed와 host_release_outdated가 사라지고 status의 resumed에 수동으로 표시된다."""
        # When
        code, output = self.record("--terminal", "term_resume", "--action", "resume", "--result", "done")

        # Then
        self.assertEqual(0, code)
        self.assertNotIn("resume_approval_needed", output["session"])
        self.assertNotIn("host_release_outdated", output["session"])
        self.assertEqual([("done", True)], [(item["status"], item["manual"]) for item in self.status()["resumed"]])

    def test_실패한_결과는_failed와_이유로_남는다(self):
        """손으로 한 동작이 실패했다고 기록하면 세션은 failed가 되고 주어진 이유가 남으며 not_refreshed에 계속 보인다."""
        # When
        code, output = self.record("--terminal", "term_skipped", "--action", "reload", "--result", "failed", "--detail", "reload_unconfirmed")

        # Then
        self.assertEqual(0, code)
        self.assertEqual(("failed", "reload_unconfirmed", ["reload:reload_unconfirmed"]),
                         tuple(output["session"][key] for key in ("status", "detail", "completed")))

    def test_실패를_기록해도_남은_동작은_미완으로_남고_실패한_동작만_나중에_지울_수_있다(self):
        """reload 실패 뒤 reload 완료를 기록해도 compact가 남아 있으면 세션은 done이 아니고, 이어서 compact 기록도 받아들여 그때 done이 된다."""
        # When
        failed = self.record("--terminal", "term_skipped", "--action", "reload", "--result", "failed", "--detail", "reload_unconfirmed")
        retried = self.record("--terminal", "term_skipped", "--action", "reload", "--result", "done")
        finished = self.record("--terminal", "term_skipped", "--action", "compact", "--result", "done")

        # Then
        self.assertEqual((["reload", "compact"], "failed", "reload_unconfirmed"),
                         tuple(failed[1]["session"][key] for key in ("actions", "status", "detail")))
        self.assertEqual((["compact"], "skipped", "not_a_claude_session"),
                         tuple(retried[1]["session"][key] for key in ("actions", "status", "detail")))
        self.assertEqual((0, "done", "applied_by_agent", []),
                         (finished[0], finished[1]["session"]["status"], finished[1]["session"]["detail"], finished[1]["session"]["actions"]))

    def test_남은_동작을_비운_건너뛴_세션은_계획한_동작으로_남은_일을_계산한다(self):
        """자동 처리가 actions를 비운 건너뛴 세션도 reload 기록 뒤 계획한 compact가 남고, compact 기록에서야 done이 된다."""
        # When
        first = self.record("--terminal", "term_cleared", "--action", "reload", "--result", "done")
        second = self.record("--terminal", "term_cleared", "--action", "compact", "--result", "done")

        # Then
        self.assertEqual(("skipped", ["compact"]), (first[1]["session"]["status"], first[1]["session"]["actions"]))
        self.assertEqual(("done", "applied_by_agent"), (second[1]["session"]["status"], second[1]["session"]["detail"]))

    def test_재개를_기록하면_계획한_reload는_남지_않는다(self):
        """새 프로세스가 플러그인을 불러오므로 resume 완료 기록은 계획한 reload도 끝난 것으로 보고 compact만 남긴다."""
        # When
        resumed = self.record("--terminal", "term_cleared", "--action", "resume", "--result", "done")

        # Then
        self.assertEqual(("skipped", ["compact"]), (resumed[1]["session"]["status"], resumed[1]["session"]["actions"]))

    def test_이미_끝난_세션과_모르는_세션은_기록하지_않는다(self):
        """done 세션이나 실행에 없는 터미널을 기록하려 하면 오류로 끝나고 저장된 결과를 바꾸지 않는다."""
        # When
        done = self.record("--terminal", "term_done", "--action", "reload", "--result", "done")
        unknown = self.record("--terminal", "term_missing", "--action", "reload", "--result", "done")

        # Then
        self.assertEqual((2, "session_not_recordable"), (done[0], done[1]["error"]["code"]))
        self.assertEqual((2, "session_not_in_run"), (unknown[0], unknown[1]["error"]["code"]))
        self.assertEqual("done", refresh_core.load_run(self.RUN)["sessions"]["term_done"]["status"])


if __name__ == "__main__":
    unittest.main()
