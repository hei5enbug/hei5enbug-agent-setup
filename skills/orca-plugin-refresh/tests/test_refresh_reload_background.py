from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import test_orca_plugin_refresh as base
from test_orca_plugin_refresh import FakeOrca, refresh, result_record, terminal, tool_use, turn_end, user_record, write_records, assistant_record, RUNNING_TURN

HANDLE = "term_demo-a"
RELOADED = {"type": "system", "subtype": "local_command", "content": "<local-command-stdout>Reloaded: 7 plugins</local-command-stdout>"}
OWING = [user_record("빌드"), assistant_record(tool_use("Bash", command="sleep 600", run_in_background=True)),
         result_record("Command running in background with ID: bg1"), turn_end()]


def setUpModule():
    base.setUpModule()


def tearDownModule():
    base.tearDownModule()


class ReloadWhileBackgroundTaskTest(unittest.TestCase):
    setUp = base.DriveTest.setUp
    write_marker = base.DriveTest.write_marker

    def session(self, records, digest="d"):
        path = write_records(Path(self.temp.name) / f"{HANDLE}.jsonl", records)
        self.write_marker(HANDLE, "claude", digest=digest, transcript=path)
        return path

    def reload_on_send(self, path):
        def respond(fake, handle, text):
            with path.open("a") as stream:
                stream.write(json.dumps(RELOADED) + "\n")
        return respond

    def deferred(self, path, actions, **extra):
        return {"handle": HANDLE, "host": "claude", "actions": list(actions), "status": "pending", "detail": "busy",
                "deadline": time.time() + 0.3, "deferred_at": time.time(), "handoff_transcript": str(path),
                "handoff_offset": path.stat().st_size, **extra}

    def follow(self, entries, on_send=None):
        fake = FakeOrca([terminal(HANDLE, "claude")], busy={HANDLE: 10**9}, on_send=on_send)
        fake.never_idle = {HANDLE}
        refresh.follow_up(fake, entries, self.state, sleep=lambda seconds: time.sleep(0.01))
        return fake

    def test_백그라운드_작업이_남은_세션도_reload만_남았으면_apply가_바로_보낸다(self):
        """term_demo-a: 차례는 끝났고 백그라운드 명령이 아직 알리지 않았어도 남은 동작이 reload뿐이면 Orca가 바쁘다고 해도 host_record 근거로 /reload-plugins를 보낸다."""
        # Given
        path = self.session(OWING)
        fake = FakeOrca([terminal(HANDLE, "claude")], busy={HANDLE: 10**9}, on_send=self.reload_on_send(path))
        sessions = refresh.plan_sessions(fake, self.state, "auto", [])

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 5, sleep=lambda seconds: None, expire="deferred")

        # Then
        self.assertEqual([(HANDLE, "/reload-plugins")], fake.sent)
        self.assertEqual(("done", "host_record"), (sessions[0]["status"], sessions[0]["ready_signal"]))

    def test_백그라운드_작업이_남은_세션도_도우미가_기한_안에_reload를_보낸다(self):
        """term_demo-a: 같은 세션이 도우미에 넘겨져도 폴링이 기한 전에 /reload-plugins를 보내고 not_idle_before_deadline으로 건너뛰지 않는다."""
        # Given
        path = self.session(OWING)
        entries = [self.deferred(path, ["reload"])]

        # When
        fake = self.follow(entries, self.reload_on_send(path))

        # Then
        self.assertEqual([(HANDLE, "/reload-plugins")], fake.sent)
        self.assertEqual("done", entries[0]["status"])

    def test_이미_현재_지침인_표식이면_남은_compact를_빼고_reload를_백그라운드_작업_중에도_보낸다(self):
        """term_demo-a: 계획에 compact가 있어도 표식이 이미 설치된 지침이면 still_needed 규칙으로 그것을 뺀 뒤 reload만 남은 것으로 보고 보낸다."""
        # Given
        path = self.session(OWING)
        entries = [self.deferred(path, ["reload", "compact"])]

        # When
        fake = self.follow(entries, self.reload_on_send(path))

        # Then
        self.assertEqual([(HANDLE, "/reload-plugins")], fake.sent)
        self.assertEqual(("done", []), (entries[0]["status"], entries[0]["actions"]))

    def test_compact가_함께_필요하면_백그라운드_작업이_남은_세션에_아무것도_보내지_않고_미룬다(self):
        """term_demo-a: 지침이 달라 compact도 필요하면 백그라운드 작업이 남은 세션은 준비되지 않은 것으로 보고 reload도 보내지 않은 채 deferred로 남는다."""
        # Given
        path = self.session(OWING, digest="old")
        fake = FakeOrca([terminal(HANDLE, "claude")], busy={HANDLE: 10**9})
        sessions = refresh.plan_sessions(fake, self.state, "auto", [])

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 0.2, sleep=lambda seconds: time.sleep(0.01), expire="deferred")

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual((["reload", "compact"], "deferred"), (sessions[0]["actions"], sessions[0]["status"]))
        self.assertTrue(path.is_file())


class ReloadOwedAfterHandoffTest(unittest.TestCase):
    setUp = base.DriveTest.setUp
    write_marker = base.DriveTest.write_marker

    def rewrite_marker(self, path, **fields):
        self.write_marker(HANDLE, "claude", digest="d", transcript=path)
        marker_path = refresh.SESSION_CONTEXT.marker_directory() / f"{HANDLE}.json"
        marker = json.loads(marker_path.read_text())
        marker_path.write_text(json.dumps({**marker, "written_at": refresh.now(), **fields}))

    def busy_session(self):
        path = write_records(Path(self.temp.name) / f"{HANDLE}.jsonl", RUNNING_TURN)
        self.write_marker(HANDLE, "claude", digest="old", transcript=path)
        return path

    def entry(self, path, **extra):
        return {"handle": HANDLE, "host": "claude", "actions": ["reload"], "status": "pending", "detail": "busy",
                "deadline": time.time() + 0.3, "deferred_at": time.time() - 1, "handoff_transcript": str(path),
                "handoff_offset": path.stat().st_size, **extra}

    def other_root(self):
        directory = Path(self.temp.name) / "plugin-2.0.0"
        directory.mkdir()
        return str(directory)

    def follow(self, entries):
        fake = FakeOrca([terminal(HANDLE, "claude")], busy={HANDLE: 10**9})
        fake.never_idle = {HANDLE}
        seen = []

        def sleep(seconds):
            seen.append((entries[0]["status"], list(entries[0]["actions"])))
            time.sleep(0.01)

        refresh.follow_up(fake, entries, self.state, sleep=sleep)
        return fake, seen

    def test_compact_표식이_다른_옛_폴더를_가리켜도_reload는_기한까지_남는다(self):
        """term_demo-a: 넘긴 뒤 compact가 표식을 설치된 지침과 다른 폴더로 다시 썼고 기록에 reload가 없으면 reload를 지우지 않고 기한에 건너뛴다."""
        # Given
        path = self.busy_session()
        self.rewrite_marker(path, source="compact", root=self.other_root())
        entries = [self.entry(path)]

        # When
        fake, seen = self.follow(entries)

        # Then
        self.assertEqual({("pending", ("reload",)), ("skipped", ())}, {(status, tuple(actions)) for status, actions in seen})
        self.assertEqual(("skipped", "not_idle_before_deadline"), (entries[0]["status"], entries[0]["detail"]))
        self.assertEqual([], fake.sent)

    def test_compact_표식이_설치된_폴더를_가리켜도_reload는_기한까지_남는다(self):
        """term_demo-a: 표식이 compact로 다시 쓰였고 폴더도 설치된 것과 같아도 새 프로세스가 아니므로 기록에 reload가 없으면 reload가 남는다."""
        # Given
        path = self.busy_session()
        self.rewrite_marker(path, source="compact", root=self.temp.name)
        entries = [self.entry(path)]

        # When
        fake, seen = self.follow(entries)

        # Then
        self.assertEqual({("pending", ("reload",)), ("skipped", ())}, {(status, tuple(actions)) for status, actions in seen})
        self.assertEqual([], fake.sent)

    def test_끝내_반영하지_못한_세션은_done이_아니고_status의_not_refreshed에_나온다(self):
        """term_demo-a: 도우미 기한이 지나도 reload가 안 된 세션은 상태가 done이 아니고 status가 not_refreshed에 담는다."""
        # Given
        path = self.busy_session()
        self.rewrite_marker(path, source="compact", root=self.other_root())
        run_id = "c" * 32
        deferred_at = time.time() - refresh.FOLLOW_UP_SECONDS + 0.3
        item = {"handle": HANDLE, "host": "claude", "actions": ["reload"], "detail": "busy", "deferred_at": deferred_at,
                "handoff_transcript": str(path), "handoff_offset": path.stat().st_size}
        refresh.save_json(refresh.run_path(run_id), {**self.state, "run_id": run_id, "follow_up": [item],
                                                     "initiator": {"handle": "term_self", "host": "claude"}})
        fake = FakeOrca([terminal(HANDLE, "claude"), terminal("term_self", "claude")], busy={HANDLE: 10**9})
        fake.never_idle = {HANDLE}

        # When
        with patch.object(refresh, "Orca", return_value=fake):
            refresh.command_self_apply(run_id, sleep=lambda seconds: time.sleep(0.02))

        # Then
        status = refresh.command_status(run_id)
        self.assertEqual([("skipped", "not_idle_before_deadline")], [(item["status"], item["detail"]) for item in status["not_refreshed"]])

    def test_새_프로세스가_표식을_다시_썼으면_reload를_보내지_않고_already_current로_끝낸다(self):
        """term_demo-a: 넘긴 뒤 표식이 source resume으로 설치된 지침과 폴더로 다시 쓰였고 남은 동작이 reload뿐이면 아무것도 보내지 않고 already_current로 끝낸다."""
        # Given
        path = self.busy_session()
        self.rewrite_marker(path, source="resume", root=self.temp.name)
        entries = [self.entry(path)]

        # When
        fake, seen = self.follow(entries)

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual(("done", "already_current"), (entries[0]["status"], entries[0]["detail"]))

    def test_새_프로세스_표식은_폴더나_지침이_달라도_reload를_끝난_것으로_본다(self):
        """term_demo-a: source startup 표식은 지침과 폴더가 설치된 것과 달라도 새 프로세스가 플러그인을 읽었으므로 reload를 지운다."""
        # Given
        path = self.busy_session()
        self.rewrite_marker(path, source="startup", root=self.other_root(), digest="old")
        entries = [self.entry(path)]

        # When
        fake, seen = self.follow(entries)

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual(("done", "already_current"), (entries[0]["status"], entries[0]["detail"]))

    def test_세션이_넘긴_뒤_직접_reload했으면_compact_표식이어도_applied_by_session으로_끝낸다(self):
        """term_demo-a: 기록에 넘긴 뒤 성공한 reload가 있으면 compact로 다시 쓰인 표식과 함께 reload와 compact가 모두 끝나 applied_by_session이 된다."""
        # Given
        path = self.busy_session()
        entries = [self.entry(path, actions=["reload", "compact"])]
        with path.open("a") as stream:
            stream.write(json.dumps(RELOADED) + "\n")
        self.rewrite_marker(path, source="compact", root=self.other_root())

        # When
        fake, seen = self.follow(entries)

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual(("done", "applied_by_session"), (entries[0]["status"], entries[0]["detail"]))


if __name__ == "__main__":
    unittest.main()
