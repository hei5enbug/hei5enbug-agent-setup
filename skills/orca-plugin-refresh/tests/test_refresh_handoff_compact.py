from __future__ import annotations

import io
import json
import os
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import test_orca_plugin_refresh as base
from test_orca_plugin_refresh import FINISHED_TURN, RUNNING_TURN, FakeOrca, refresh, terminal, user_record, write_records

import refresh_host_record
import refresh_sessions

HANDLE = "demo-a"
RELOADED = {"type": "system", "subtype": "local_command", "content": "<local-command-stdout>Reloaded: 7 plugins</local-command-stdout>"}
NOTHING_TO_COMPACT = {"type": "system", "subtype": "local_command",
                      "content": "<local-command-stdout>Not enough messages to compact.</local-command-stdout>"}
COMMAND_ONLY = [user_record("/reload-plugins"), user_record("<command-name>/reload-plugins</command-name>"), RELOADED]


def setUpModule():
    base.setUpModule()


def tearDownModule():
    base.tearDownModule()


class HandoffTailTest(unittest.TestCase):
    setUp = base.DriveTest.setUp
    write_marker = base.DriveTest.write_marker
    simulate = base.DriveTest.simulate

    def marker_with(self, handle, records, partial=""):
        path = write_records(Path(self.temp.name) / f"{handle}.jsonl", records, partial)
        self.write_marker(handle, "claude", transcript=path)
        return path

    def deferred(self, handle, path):
        return [{"handle": handle, "host": "claude", "actions": ["reload"], "status": "pending", "detail": "busy",
                 "deadline": time.time() + 0.3, "deferred_at": time.time(),
                 "handoff_transcript": str(path), "handoff_offset": path.stat().st_size}]

    def follow(self, fake, entries):
        fake.never_idle = {entry["handle"] for entry in entries}
        refresh.follow_up(fake, entries, self.state, sleep=lambda seconds: None)

    def test_핸드오프_뒤_새_기록이_없어도_끝난_슬래시_명령으로_끝난_기록이면_쉬는_중으로_보고_남은_동작을_보낸다(self):
        """demo-a: 차례 종료 기록 없이 슬래시 명령 결과로 끝난 기록은 핸드오프 뒤 기록이 없어도 idle이고, tui-idle이 오지 않아도 도우미가 reload를 보낸다."""
        # Given
        path = self.marker_with(HANDLE, COMMAND_ONLY)
        fake = FakeOrca([terminal(HANDLE, "claude")], busy={HANDLE: 10**9}, on_send=self.simulate)
        entries = self.deferred(HANDLE, path)

        # When
        self.follow(fake, entries)

        # Then
        self.assertEqual("idle", refresh.host_record(entries[0]))
        self.assertEqual([(HANDLE, "/reload-plugins")], fake.sent)
        self.assertEqual(("done", "host_record"), (entries[0]["status"], entries[0]["ready_signal"]))

    def test_끝난_차례로_끝난_기록도_핸드오프_뒤_새_기록이_없으면_쉬는_중으로_보고_보낸다(self):
        """demo-a: 끝난 차례와 끝난 슬래시 명령으로 끝난 기록은 핸드오프 뒤 기록이 없어도 tui-idle 없이 idle로 판정해 보낸다."""
        # Given
        path = self.marker_with(HANDLE, [*FINISHED_TURN, *COMMAND_ONLY])
        fake = FakeOrca([terminal(HANDLE, "claude")], busy={HANDLE: 10**9}, on_send=self.simulate)
        entries = self.deferred(HANDLE, path)

        # When
        self.follow(fake, entries)

        # Then
        self.assertEqual([(HANDLE, "/reload-plugins")], fake.sent)
        self.assertEqual(("done", "host_record"), (entries[0]["status"], entries[0]["ready_signal"]))

    def test_핸드오프_뒤_새_기록이_없어도_진행_중인_차례로_끝난_기록은_바쁜_것으로_보고_보내지_않는다(self):
        """demo-a: 기록의 꼬리가 진행 중인 차례이면 핸드오프 뒤 기록이 없어도 busy이고, Orca가 쉬는 중이라고 해도 보내지 않는다."""
        # Given
        path = self.marker_with(HANDLE, RUNNING_TURN)
        fake = FakeOrca([terminal(HANDLE, "claude")], on_send=self.simulate)
        entries = self.deferred(HANDLE, path)
        fake.never_idle = set()

        # When
        refresh.follow_up(fake, entries, self.state, sleep=lambda seconds: None)

        # Then
        self.assertEqual("busy", refresh.host_record(entries[0]))
        self.assertEqual([], fake.sent)
        self.assertEqual(("skipped", "not_idle_before_deadline"), (entries[0]["status"], entries[0]["detail"]))

    def test_기록의_마지막_줄이_덜_쓰였으면_Orca의_쉬는_신호가_판단한다(self):
        """demo-a: 꼬리의 마지막 줄이 덜 쓰여 판단할 수 없으면 host_record는 None이고, tui-idle이 오면 tui_idle을 근거로 보낸다."""
        # Given
        path = self.marker_with(HANDLE, COMMAND_ONLY, partial='{"type": "assis')
        fake = FakeOrca([terminal(HANDLE, "claude")], busy={HANDLE: 1}, on_send=self.simulate)
        entries = self.deferred(HANDLE, path)

        # When
        refresh.follow_up(fake, entries, self.state, sleep=lambda seconds: None)

        # Then
        self.assertIsNone(refresh.host_record(entries[0]))
        self.assertEqual([(HANDLE, "/reload-plugins")], fake.sent)
        self.assertEqual(("done", "tui_idle"), (entries[0]["status"], entries[0]["ready_signal"]))

    def test_기록이_없으면_Orca가_쉬는_신호를_주기_전에는_보내지_않는다(self):
        """demo-a: 대화 기록 파일이 없으면 host_record는 None이고, tui-idle이 오지 않으면 기한까지 보내지 않는다."""
        # Given
        self.write_marker(HANDLE, "claude", transcript=Path(self.temp.name) / "missing.jsonl")
        fake = FakeOrca([terminal(HANDLE, "claude")], busy={HANDLE: 10**9}, on_send=self.simulate)
        entries = [{"handle": HANDLE, "host": "claude", "actions": ["reload"], "status": "pending", "detail": "busy",
                    "deadline": time.time() + 0.3, "deferred_at": time.time(), "handoff_transcript": None, "handoff_offset": None}]

        # When
        self.follow(fake, entries)

        # Then
        self.assertIsNone(refresh.host_record(entries[0]))
        self.assertEqual([], fake.sent)
        self.assertEqual(("skipped", "not_idle_before_deadline"), (entries[0]["status"], entries[0]["detail"]))


class StaleCommandTailTest(unittest.TestCase):
    def setUp(self):
        self.directory = base.tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "session.jsonl"

    def state(self, records, age):
        write_records(self.path, records)
        now = time.time()
        os.utime(self.path, (now - age, now - age))
        return refresh_host_record.record_state("claude", str(self.path), now=now)

    def test_차례_종료_기록이_없는_옛_버전_기록도_오래_손대지_않은_끝난_슬래시_명령으로_끝나면_쉬는_중으로_본다(self):
        """demo-a: turn_duration 없이 assistant 기록 뒤에 끝난 /reload-plugins가 오고 파일이 기준 시간 넘게 그대로면 idle이다."""
        # Given
        records = [user_record("질문"), base.assistant_record(), *COMMAND_ONLY]

        # When
        state = self.state(records, refresh_host_record.STALE_TRANSCRIPT_SECONDS + 60)

        # Then
        self.assertEqual("idle", state)

    def test_같은_기록이라도_파일이_방금_바뀌었으면_판단하지_않고_Orca에_맡긴다(self):
        """demo-a: 같은 꼬리라도 파일이 기준 시간 안에 바뀌었으면 None이라 tui-idle이 판단한다."""
        # Given
        records = [user_record("질문"), base.assistant_record(), *COMMAND_ONLY]

        # When
        state = self.state(records, 5)

        # Then
        self.assertIsNone(state)

    def test_결과가_아직_없는_슬래시_명령은_오래_지나도_바쁜_것으로_본다(self):
        """demo-a: 결과가 없는 최신 명령 기록은 파일이 오래 그대로여도 busy이다."""
        # Given
        records = [user_record("질문"), base.assistant_record(), user_record("/reload-plugins"),
                   user_record("<command-name>/reload-plugins</command-name>")]

        # When
        state = self.state(records, refresh_host_record.STALE_TRANSCRIPT_SECONDS + 60)

        # Then
        self.assertEqual("busy", state)


class CompactRefusedTest(unittest.TestCase):
    setUp = base.DriveTest.setUp
    write_marker = base.DriveTest.write_marker

    def refused_session(self, handle, prompts):
        records = FINISHED_TURN if prompts else COMMAND_ONLY
        path = write_records(Path(self.temp.name) / f"{handle}.jsonl", records)
        self.write_marker(handle, "claude", digest="old", transcript=path)

        def respond(fake, sent_handle, text):
            if text == "/reload-plugins":
                record = RELOADED
            elif text == "/compact":
                record = NOTHING_TO_COMPACT
            else:
                self.write_marker(sent_handle, "claude", transcript=path)
                return
            with path.open("a") as stream:
                stream.write(json.dumps(record) + "\n")
        return respond

    def drive(self, handle, prompts):
        respond = self.refused_session(handle, prompts)
        fake = FakeOrca([terminal(handle, "claude")], on_send=respond)
        sessions = refresh.plan_sessions(fake, self.state, "auto", [])
        refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=lambda seconds: None)
        return fake, sessions

    def test_프롬프트가_있는_세션이_compact를_거절당하면_reload_확인_뒤_done과_다음_compact_안내로_끝낸다(self):
        """demo-a: reload가 확인된 뒤 Not enough messages로 compact가 거절돼도 프롬프트가 있으면 failed가 아니라 done과 instructions_on_next_compaction 안내로 끝내고 /clear는 보내지 않는다."""
        # Given / When
        fake, sessions = self.drive(HANDLE, prompts=True)

        # Then
        entry = sessions[0]
        self.assertEqual([(HANDLE, "/reload-plugins"), (HANDLE, "/compact")], fake.sent)
        self.assertEqual(("done", "instructions_on_next_compaction"), (entry["status"], entry["note"]))
        self.assertEqual(["reload", "compact:nothing_to_compact"], entry["completed"])
        self.assertEqual([], entry["actions"])

    def test_프롬프트가_없는_세션만_clear로_지침을_넣는다(self):
        """demo-a: 프롬프트가 없는 세션은 compact가 거절되면 /clear로 지침을 넣고 empty_session_cleared로 끝내며 안내 note는 남기지 않는다."""
        # Given / When
        fake, sessions = self.drive(HANDLE, prompts=False)

        # Then
        entry = sessions[0]
        self.assertIn((HANDLE, "/clear"), fake.sent)
        self.assertEqual(("done", "empty_session_cleared"), (entry["status"], entry["note"]))

    def test_clear_직전에_프롬프트가_생기면_clear_없이_done과_다음_compact_안내로_끝낸다(self):
        """demo-a: 빈 세션으로 보고 clear를 예약했어도 보내기 직전에 프롬프트가 생기면 /clear를 보내지 않고 done과 instructions_on_next_compaction으로 끝낸다."""
        # Given
        self.write_marker(HANDLE, "claude", digest="old")
        fake = FakeOrca([terminal(HANDLE, "claude")])
        entry = {"handle": HANDLE, "host": "claude", "actions": ["clear"], "status": "pending", "detail": "empty_session_needs_clear"}

        # When
        with patch.object(refresh_sessions, "claude_has_prompts", return_value=True):
            refresh.step(fake, entry, self.state["hosts"]["claude"], {HANDLE: terminal(HANDLE, "claude")})

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual(("done", "instructions_on_next_compaction", ["compact:nothing_to_compact"], []),
                         (entry["status"], entry["note"], entry["completed"], entry["actions"]))

    def test_거절된_compact는_성공으로_세어_다른_세션이_모두_끝났으면_종료_코드_0이다(self):
        """demo-a: 프롬프트가 있는 세션의 compact 거절은 성공으로 세어 apply가 ok이고 종료 코드가 0이다."""
        # Given
        respond = self.refused_session(HANDLE, prompts=True)
        fake = FakeOrca([terminal(HANDLE, "claude")], on_send=respond)
        run_id = "f" * 32
        refresh.save_json(refresh.run_path(run_id), {**self.state, "run_id": run_id})
        output = io.StringIO()

        # When
        with patch.object(refresh, "Orca", return_value=fake), redirect_stdout(output):
            code = refresh.main(["apply", "--run-id", run_id, "--json", "--timeout-seconds", "30"])

        # Then
        result = json.loads(output.getvalue())
        self.assertEqual(0, code)
        self.assertTrue(result["ok"])
        self.assertEqual(("done", "instructions_on_next_compaction"), (result["sessions"][0]["status"], result["sessions"][0]["note"]))


if __name__ == "__main__":
    unittest.main()
