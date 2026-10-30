from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

import test_orca_plugin_refresh as base
from test_orca_plugin_refresh import CODEX_EMPTY, FakeOrca, refresh, terminal

import refresh_core
import refresh_feed

RUN_ID = "a" * 32
WAIT_LIMIT = 15.0


def wait_until(check, limit=WAIT_LIMIT):
    deadline = time.time() + limit
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.01)
    return False


def sessions_lock_held() -> bool:
    try:
        with refresh_core.exclusive("sessions"):
            return False
    except refresh_core.RefreshError as error:
        return error.code == "already_running"


class AuditedOrca(FakeOrca):
    """A fake Orca that records every write to a session, whether the sessions lock was held, and how many overlapped."""

    def __init__(self, *args, slow=0.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.slow = slow
        self.unlocked: list[tuple[str, str]] = []
        self.active = 0
        self.most_active = 0
        self.guard = threading.Lock()

    def audited(self, handle, text, action):
        if not sessions_lock_held():
            self.unlocked.append((handle, text))
        with self.guard:
            self.active += 1
            self.most_active = max(self.most_active, self.active)
        try:
            time.sleep(self.slow)
            action()
        finally:
            with self.guard:
                self.active -= 1

    def send(self, handle, text):
        self.audited(handle, text, lambda: FakeOrca.send(self, handle, text))

    def keys(self, handle, text):
        self.audited(handle, text, lambda: FakeOrca.keys(self, handle, text))


class LockScopeTest(unittest.TestCase):
    drive_setup = base.DriveTest.setUp
    write_marker = base.DriveTest.write_marker
    simulate = base.DriveTest.simulate

    def setUp(self):
        self.drive_setup()
        self.threads: list[threading.Thread] = []
        self.failures: list[BaseException] = []
        self.addCleanup(self.join_helpers)

    def join_helpers(self):
        for thread in self.threads:
            thread.join(timeout=WAIT_LIMIT)

    def save_run(self, **extra):
        refresh.save_json(refresh.run_path(RUN_ID), {**self.state, "run_id": RUN_ID, **extra})

    def start_helper(self):
        def work():
            try:
                refresh.command_self_apply(RUN_ID, sleep=lambda seconds: time.sleep(0.01))
            except BaseException as error:
                self.failures.append(error)

        thread = threading.Thread(target=work, daemon=True)
        self.threads.append(thread)
        thread.start()
        return thread

    def deferred_item(self, handle, host="claude", actions=("reload",)):
        return {"handle": handle, "host": host, "actions": list(actions), "detail": "busy", "deferred_at": time.time()}

    def spawn_helper_thread(self, run_id):
        self.spawned.append(run_id)
        self.start_helper()
        return os.getpid()

    def test_도우미가_세션을_기다리는_동안에는_다른_세션을_대상으로_한_apply가_명령을_보낸다(self):
        """도우미가 바쁜 세션의 대기만 하고 있을 때는 잠금을 쥐지 않으므로, 다른 터미널을 지정한 apply가 거절되지 않고 명령을 보낸다."""
        # Given
        self.write_marker("term_codex", "codex")
        fake = AuditedOrca([terminal("term_busy", "claude"), terminal("term_codex", "codex")], busy={"term_busy": 10**6},
                           screens={"term_codex": CODEX_EMPTY}, on_send=self.simulate)
        fake.never_idle = {"term_busy"}
        self.save_run(follow_up=[self.deferred_item("term_busy")])
        with patch.object(refresh, "Orca", return_value=fake):
            helper = self.start_helper()
            self.assertTrue(wait_until(lambda: "term_busy" in getattr(fake, "waits", [])))
            held = sessions_lock_held()

            # When
            result = refresh.command_apply(RUN_ID, "always", ["term_codex"], 5, spawn=lambda run: 1)

        # Then
        self.assertFalse(held)
        self.assertTrue(helper.is_alive())
        self.assertEqual([("term_codex", "/compact")], [item for item in fake.sent if item[0] == "term_codex"])
        self.assertEqual("done", result["sessions"][0]["status"])
        self.assertEqual([], fake.unlocked)
        fake.list = [item for item in fake.list if item["handle"] != "term_busy"]

    def test_도우미와_apply는_같은_시각에_세션으로_보내지_않고_보낼_때마다_잠금을_쥐고_있다(self):
        """도우미와 apply가 동시에 돌아도 전송은 겹치지 않고, 모든 전송과 입력 시도 순간에 잠금이 잡혀 있다."""
        # Given
        self.write_marker("term_codex", "codex")
        fake = AuditedOrca([terminal("term_busy", "claude"), terminal("term_codex", "codex")], busy={"term_busy": 3},
                           screens={"term_codex": CODEX_EMPTY}, on_send=self.simulate, slow=0.03)
        self.save_run(follow_up=[self.deferred_item("term_busy")])
        results: list[dict] = []

        def apply_with_retry():
            deadline = time.time() + WAIT_LIMIT
            while time.time() < deadline:
                try:
                    results.append(refresh.command_apply(RUN_ID, "always", ["term_codex"], 5, spawn=lambda run: 1))
                    return
                except refresh.RefreshError as error:
                    if error.code != "already_running":
                        raise
                    time.sleep(0.01)

        # When
        with patch.object(refresh, "Orca", return_value=fake):
            helper = self.start_helper()
            applier = threading.Thread(target=apply_with_retry, daemon=True)
            applier.start()
            applier.join(timeout=WAIT_LIMIT)
            helper.join(timeout=WAIT_LIMIT)

        # Then
        self.assertEqual([], self.failures)
        self.assertEqual("done", results[0]["sessions"][0]["status"])
        self.assertIn(("term_busy", "/reload-plugins"), fake.sent)
        self.assertEqual([], fake.unlocked)
        self.assertEqual(1, fake.most_active)

    def test_새_apply가_미룬_세션은_이미_도는_도우미에_합류하고_도우미를_새로_시작하지_않는다(self):
        """도우미가 대기하는 동안 새 apply가 미룬 세션은 실행 기록에 덧붙고 같은 도우미가 이어받아 처리하며, 도우미는 한 번만 시작한다."""
        # Given
        self.spawned: list[str] = []
        fake = AuditedOrca([terminal("term_first", "claude"), terminal("term_second", "claude")],
                           busy={"term_first": 10**6, "term_second": 10**6}, on_send=self.simulate)
        fake.never_idle = {"term_first"}
        self.save_run()
        with patch.object(refresh, "Orca", return_value=fake):
            refresh.command_apply(RUN_ID, "never", ["term_first"], 1, spawn=self.spawn_helper_thread)
            self.assertTrue(wait_until(lambda: "term_first" in getattr(fake, "waits", [])))

            # When
            result = refresh.command_apply(RUN_ID, "never", ["term_second"], 1, spawn=self.spawn_helper_thread)
            joined = wait_until(lambda: ("term_second", "/reload-plugins") in fake.sent)
            fake.list = [item for item in fake.list if item["handle"] != "term_first"]
            self.join_helpers()

        # Then
        self.assertEqual("deferred", result["sessions"][0]["status"])
        self.assertEqual([RUN_ID], self.spawned)
        self.assertTrue(joined)
        self.assertEqual([], self.failures)
        saved = refresh.load_run(RUN_ID)
        self.assertEqual(["term_first", "term_second"], [item["handle"] for item in saved["follow_up"]])
        self.assertEqual("done", saved["sessions"]["term_second"]["status"])
        self.assertEqual([], fake.unlocked)

    def test_apply가_길게_도는_사이_도우미가_기록한_세션_결과를_apply가_덮어쓰지_않는다(self):
        """apply가 잠금을 쥐고 오래 도는 동안 도우미가 끝난 세션을 기록해도, apply의 저장이 그 결과를 되돌리지 않고 새 합류분만 더한다."""
        # Given
        fake = FakeOrca([terminal("term_old", "claude"), terminal("term_new", "claude")], busy={"term_new": 10**6})
        self.save_run(follow_up=[self.deferred_item("term_old")], sessions={"term_old": {"status": "deferred", "terminal": "…m_old"}},
                      helper={"pid": os.getpid(), "started_at": refresh.now()})
        real_drive = refresh.drive

        def drive_while_helper_records(*args, **kwargs):
            real_drive(*args, **kwargs)
            refresh_core.update_run(RUN_ID, lambda saved: {**saved, "sessions": {**saved["sessions"], "term_old": {"status": "done", "terminal": "…m_old"}}})

        # When
        with patch.object(refresh, "Orca", return_value=fake), patch.object(refresh, "drive", drive_while_helper_records):
            refresh.command_apply(RUN_ID, "never", ["term_old", "term_new"], 1, spawn=lambda run: 1)

        # Then
        saved = refresh.load_run(RUN_ID)
        self.assertEqual("done", saved["sessions"]["term_old"]["status"])
        self.assertEqual(["term_old", "term_new"], [item["handle"] for item in saved["follow_up"]])

    def test_도우미가_끝내기_직전에_합류한_항목은_놓치지_않고_넘겨받는다(self):
        """마감 확인은 새로 합류한 항목이 있으면 그것을 돌려주고 끝난 표시를 하지 않으며, 없을 때만 끝난 표시를 남긴다."""
        # Given
        self.save_run(follow_up=[self.deferred_item("term_one")])
        feed = refresh_feed.RunFeed(RUN_ID, follow_seconds=60, self_seconds=60)
        first = feed.poll()
        refresh_core.update_run(RUN_ID, lambda saved: {**saved, "follow_up": [*saved["follow_up"], self.deferred_item("term_two")]})

        # When
        closing = feed.close()
        final = feed.close()

        # Then
        self.assertEqual(["term_one"], [entry["handle"] for entry in first])
        self.assertEqual(["term_two"], [entry["handle"] for entry in closing])
        self.assertEqual([], final)
        self.assertIsNotNone(refresh.load_run(RUN_ID).get("helper_finished_at"))

    def test_잠금을_쥔_프로세스가_죽으면_운영체제가_잠금을_풀어_다음_실행이_바로_잠글_수_있다(self):
        """잠금을 쥔 채 강제 종료된 프로세스의 잠금은 남지 않아 이후 apply가 already_running 없이 잠금을 얻는다."""
        # Given
        path = refresh_core.state_root() / "sessions.lock"
        code = "import fcntl,sys,time;h=open(sys.argv[1],'a+');fcntl.flock(h,fcntl.LOCK_EX);print('locked',flush=True);time.sleep(60)"
        holder = subprocess.Popen([sys.executable, "-c", code, str(path)], stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.kill)
        holder.stdout.readline()
        refused = sessions_lock_held()

        # When
        holder.kill()
        holder.wait(timeout=10)
        released = not sessions_lock_held()

        # Then
        self.assertTrue(refused)
        self.assertTrue(released)
