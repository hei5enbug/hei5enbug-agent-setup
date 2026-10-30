from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import test_orca_plugin_refresh as base
from test_orca_plugin_refresh import (CLAUDE_EMPTY, CODEX_EMPTY, FINISHED_TURN, RUNNING_TURN, FakeOrca, assistant_record,
                                      refresh, result_record, setUpModule, terminal, tool_use, tearDownModule, turn_end,
                                      user_record, write_records)

import refresh_core
import refresh_follow
import refresh_orca
import refresh_orphans
import refresh_sessions

HOUR = 3600.0
DAY = 24 * HOUR
CLAUDE = "term_claude_orphan"
CODEX = "term_codex_orphan"
BACKGROUND_TURN = [user_record("질문"), assistant_record(tool_use("Bash", command="sleep 600", run_in_background=True)),
                   result_record("Command running in background with ID: bg1"), assistant_record(), turn_end()]
CODEX_IDLE = [base.rollout_event("task_complete")]
CODEX_BUSY = [base.rollout_event("agent_message")]


def orphan(handle, host, **changes):
    return {**terminal(handle, host), "orphaned": True, "title": None, "lastOutputAt": None, **changes}


class OrphanFake(FakeOrca):
    """A fake Orca that also closes terminals: a closed terminal leaves the list."""

    def __init__(self, *args, keep_on_close=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed: list[str] = []
        self.keep_on_close = keep_on_close

    def close(self, handle):
        self.closed.append(handle)
        if not self.keep_on_close:
            self.list = [item for item in self.list if item["handle"] != handle]


class OrphanCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {"ORCA_USER_DATA_PATH": self.temp.name, "XDG_STATE_HOME": self.temp.name,
                                      "ORCA_TERMINAL_HANDLE": "term_self"})
        env.start()
        self.addCleanup(env.stop)
        for module, name, value in ((refresh_sessions, "POLL_SECONDS", 0), (refresh_sessions, "DRAFT_STABLE_SECONDS", 0),
                                    (refresh_sessions, "PROBE_RECHECK_SECONDS", 0), (refresh_sessions, "CLEAR_SETTLE_SECONDS", 0),
                                    (refresh_sessions, "TYPE_CONFIRM_SECONDS", 0), (refresh_follow, "IDLE_CONFIRM_SECONDS", 0),
                                    (refresh_orphans, "READY_TIMEOUT", 0.05)):
            patcher = patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.state = {"hosts": {"claude": {"digest": "d", "root": self.temp.name}, "codex": {"digest": "d", "root": self.temp.name}},
                      "sessions": {}}
        self.run_id = "c" * 32
        refresh.save_json(refresh.run_path(self.run_id), {**self.state, "run_id": self.run_id})

    def session(self, handle, host, records, *, digest="d", age=2 * DAY):
        """A marker plus a transcript or rollout whose last write was `age` seconds ago; returns the transcript path."""
        path = Path(self.temp.name) / f"{handle}.jsonl"
        write_records(path, records)
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
        directory = refresh.SESSION_CONTEXT.marker_directory()
        directory.mkdir(parents=True, exist_ok=True)
        payload = {"schema": 1, "host": host, "root": self.temp.name, "digest": digest, "written_at": refresh.now(),
                   "transcript_path": str(path)}
        (directory / f"{handle}.json").write_text(json.dumps(payload))
        return path

    def simulate(self, fake, handle, text):
        if text == "/reload-plugins":
            fake.show(handle, "  ⎿  Reloaded: 7 plugins · 28 skills")
        elif text == "/compact" and handle.startswith("term_claude"):
            self.session(handle, "claude", FINISHED_TURN, age=0)
        elif text == "/compact":
            fake.show(handle, "• Context compacted · 7s")

    def apply(self, fake, mode="auto", seconds=0.3):
        spawned: list[str] = []
        with patch.object(refresh, "Orca", return_value=fake):
            result = refresh.command_apply(self.run_id, mode, [], seconds, spawn=lambda run: spawned.append(run) or 1)
        return result, spawned

    def listing(self, fake):
        with patch.object(refresh_orphans, "Orca", return_value=fake):
            return refresh_orphans.run_orphans(self.run_id, sleep=lambda seconds: None)

    def close(self, fake, handles):
        with patch.object(refresh_orphans, "Orca", return_value=fake):
            return refresh_orphans.run_close(self.run_id, handles, sleep=lambda seconds: None)

    @staticmethod
    def by_handle(report):
        return {item["handle"]: item for item in report["orphans"]}


class OrphanedRefreshTest(OrphanCase):
    def test_연결되고_쓸_수_있는_고아_Claude_세션은_reload와_compact를_받고_done이_된다(self):
        """고아 터미널이라도 연결되어 있고 쓸 수 있으며 기록이 유휴이고 입력창이 비었으면 reload와 compact를 보내고 done으로 끝나며 보고서에 orphaned가 표시된다."""
        # Given
        self.session(CLAUDE, "claude", FINISHED_TURN, digest="old", age=0)
        fake = FakeOrca([orphan(CLAUDE, "claude")], on_send=self.simulate)

        # When
        result, _ = self.apply(fake)

        # Then
        view = result["sessions"][0]
        self.assertEqual(["/reload-plugins", "/compact"], [text for _, text in fake.sent])
        self.assertEqual(("done", True), (view["status"], view["orphaned"]))
        self.assertEqual(["reload", "compact"], view["completed"])

    def test_agentIdentity가_없는_고아_Claude_세션도_표식과_화면으로_잡아_done이_된다(self):
        """Orca가 agentIdentity를 기록하지 않은 고아 터미널은 표식의 호스트와 화면의 입력창이 일치하면 같은 점검을 거쳐 done이 된다."""
        # Given
        self.session(CLAUDE, "claude", FINISHED_TURN, digest="old", age=0)
        fake = FakeOrca([orphan(CLAUDE, None, agentIdentity=None)], on_send=self.simulate)

        # When
        result, _ = self.apply(fake)

        # Then
        self.assertEqual(("done", True), (result["sessions"][0]["status"], result["sessions"][0]["orphaned"]))

    def test_고아_Codex_세션도_compact를_받고_done이_된다(self):
        """고아 Codex 세션도 롤아웃이 유휴이고 입력창이 비었으면 compact를 받고 done으로 끝나며 orphaned가 표시된다."""
        # Given
        self.session(CODEX, "codex", CODEX_IDLE, digest="old", age=0)
        fake = FakeOrca([orphan(CODEX, "codex")], screens={CODEX: CODEX_EMPTY}, on_send=self.simulate)

        # When
        result, _ = self.apply(fake)

        # Then
        view = result["sessions"][0]
        self.assertEqual([(CODEX, "/compact")], fake.sent)
        self.assertEqual(("done", True), (view["status"], view["orphaned"]))

    def test_Orca_유휴_신호가_없어도_호스트_기록이_유휴면_고아_세션에_보낸다(self):
        """고아 터미널은 Orca의 tui-idle 신호가 없을 수 있으므로 호스트 기록이 유휴이면 신호와 관계없이 보내고 ready_signal을 host_record로 남긴다."""
        # Given
        self.session(CLAUDE, "claude", FINISHED_TURN, digest="old", age=0)
        fake = FakeOrca([orphan(CLAUDE, "claude")], busy={CLAUDE: 10**6}, on_send=self.simulate)

        # When
        result, _ = self.apply(fake)

        # Then
        self.assertEqual(("done", "host_record"), (result["sessions"][0]["status"], result["sessions"][0]["ready_signal"]))

    def test_기록이_진행_중인_고아_세션은_보내지_않고_helper에_넘긴다(self):
        """고아 세션이어도 호스트 기록이 진행 중이면 보내지 않고 deferred로 넘기며 helper 항목에 orphaned가 남는다."""
        # Given
        self.session(CLAUDE, "claude", RUNNING_TURN, digest="old", age=0)
        fake = FakeOrca([orphan(CLAUDE, "claude")], on_send=self.simulate)

        # When
        result, spawned = self.apply(fake)

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual(("deferred", True), (result["sessions"][0]["status"], result["sessions"][0]["orphaned"]))
        self.assertEqual(1, len(spawned))
        self.assertTrue(refresh.load_run(self.run_id)["follow_up"][0]["orphaned"])

    def test_연결되지_않은_고아_터미널은_첫_패스에서_terminal_orphaned로_건너뛴다(self):
        """연결되지 않은 고아 터미널은 첫 패스에서 skipped와 terminal_orphaned로 끝나고 helper에 넘기지 않으며 아무것도 보내지 않는다."""
        # Given
        self.session(CLAUDE, "claude", FINISHED_TURN, digest="old", age=0)
        fake = FakeOrca([orphan(CLAUDE, "claude", connected=False)], on_send=self.simulate)

        # When
        result, spawned = self.apply(fake)

        # Then
        view = result["sessions"][0]
        self.assertEqual(("skipped", "terminal_orphaned", True), (view["status"], view["detail"], view["orphaned"]))
        self.assertEqual(([], []), (fake.sent, spawned))
        self.assertNotIn("follow_up", refresh.load_run(self.run_id))

    def test_쓸_수_없는_고아_터미널은_첫_패스에서_terminal_orphaned로_건너뛴다(self):
        """쓸 수 없는 고아 터미널은 첫 패스에서 skipped와 terminal_orphaned로 끝나고 helper에 넘기지 않는다."""
        # Given
        self.session(CODEX, "codex", CODEX_IDLE, digest="old", age=0)
        fake = FakeOrca([orphan(CODEX, "codex", writable=False)], screens={CODEX: CODEX_EMPTY})

        # When
        result, spawned = self.apply(fake)

        # Then
        view = result["sessions"][0]
        self.assertEqual(("skipped", "terminal_orphaned"), (view["status"], view["detail"]))
        self.assertEqual(([], []), (fake.sent, spawned))

    def test_고아가_아닌_연결_끊긴_터미널은_기존대로_terminal_unavailable로_넘긴다(self):
        """고아가 아닌 터미널이 연결되지 않았으면 terminal_orphaned가 아니라 기존처럼 terminal_unavailable로 deferred 된다."""
        # Given
        self.session(CLAUDE, "claude", FINISHED_TURN, digest="old", age=0)
        fake = FakeOrca([terminal(CLAUDE, "claude") | {"connected": False}])

        # When
        result, spawned = self.apply(fake)

        # Then
        view = result["sessions"][0]
        self.assertEqual(("deferred", "terminal_unavailable"), (view["status"], view["detail"]))
        self.assertNotIn("orphaned", view)
        self.assertEqual(1, len(spawned))

    def test_고아가_아닌_세션의_보고서에는_orphaned가_없다(self):
        """고아가 아닌 세션은 공개 보고서에 orphaned 키가 없다."""
        # Given
        entry = {"handle": "term_plain_0123456", "host": "claude", "status": "done", "orphaned": False}

        # When
        view = refresh.public(entry)

        # Then
        self.assertNotIn("orphaned", view)


class OrphanListingTest(OrphanCase):
    def test_고아_에이전트_터미널을_호스트_작업_트리_유휴_시간과_함께_나열한다(self):
        """고아가 아닌 터미널은 빼고, 고아 에이전트 터미널은 호스트, 작업 트리, 마지막 기록 이후 유휴 시간과 함께 나열한다."""
        # Given
        self.session(CLAUDE, "claude", FINISHED_TURN, age=30 * HOUR)
        self.session(CODEX, "codex", CODEX_IDLE, age=50 * HOUR)
        fake = OrphanFake([orphan(CLAUDE, "claude"), orphan(CODEX, "codex", worktreePath="/tmp/other"),
                           terminal("term_live", "claude"), orphan("term_shell", None)], screens={CODEX: CODEX_EMPTY})

        # When
        report = self.listing(fake)

        # Then
        items = self.by_handle(report)
        self.assertEqual({CLAUDE, CODEX}, set(items))
        self.assertEqual(("claude", "/tmp/work"), (items[CLAUDE]["host"], items[CLAUDE]["worktree"]))
        self.assertEqual(("codex", "/tmp/other"), (items[CODEX]["host"], items[CODEX]["worktree"]))
        self.assertAlmostEqual(30 * HOUR, items[CLAUDE]["idle_seconds"], delta=60)
        self.assertAlmostEqual(50 * HOUR, items[CODEX]["idle_seconds"], delta=60)

    def test_모든_점검을_통과한_고아_터미널만_닫기를_권한다(self):
        """기록이 유휴이고 입력창이 비었고 대기 중인 작업이 없고 24시간 이상 활동이 없는 고아 터미널은 추천하고 실패한 점검은 없다."""
        # Given
        self.session(CLAUDE, "claude", FINISHED_TURN)
        self.session(CODEX, "codex", CODEX_IDLE)
        fake = OrphanFake([orphan(CLAUDE, "claude"), orphan(CODEX, "codex")], screens={CODEX: CODEX_EMPTY})

        # When
        report = self.listing(fake)

        # Then
        self.assertEqual({CLAUDE, CODEX}, set(report["recommended"]))
        self.assertEqual([None, None], [item["failed_check"] for item in report["orphans"]])

    def test_진행_중인_턴은_turn_busy로_추천하지_않는다(self):
        """호스트 기록이 진행 중인 고아 터미널은 나열하되 turn_busy를 실패한 점검으로 이름 붙이고 추천하지 않는다."""
        # Given
        self.session(CLAUDE, "claude", RUNNING_TURN)
        fake = OrphanFake([orphan(CLAUDE, "claude")])

        # When
        report = self.listing(fake)

        # Then
        item = self.by_handle(report)[CLAUDE]
        self.assertEqual(("turn_busy", False), (item["failed_check"], item["recommended"]))
        self.assertEqual([], report["recommended"])

    def test_기록을_읽을_수_없으면_turn_record_unavailable로_추천하지_않는다(self):
        """표식에 기록 경로가 없거나 파일이 없으면 유휴를 확신할 수 없으므로 turn_record_unavailable로 추천하지 않는다."""
        # Given
        path = self.session(CLAUDE, "claude", FINISHED_TURN)
        path.unlink()
        fake = OrphanFake([orphan(CLAUDE, "claude")])

        # When
        report = self.listing(fake)

        # Then
        self.assertEqual("turn_record_unavailable", self.by_handle(report)[CLAUDE]["failed_check"])

    def test_백그라운드_작업이_남은_세션은_background_task_pending으로_추천하지_않는다(self):
        """턴이 끝났어도 백그라운드 작업이 알림을 남긴 세션은 background_task_pending으로 나열만 한다."""
        # Given
        self.session(CLAUDE, "claude", BACKGROUND_TURN)
        fake = OrphanFake([orphan(CLAUDE, "claude")])

        # When
        report = self.listing(fake)

        # Then
        self.assertEqual("background_task_pending", self.by_handle(report)[CLAUDE]["failed_check"])

    def test_24시간_미만이면_recently_active이고_정확히_24시간이면_추천한다(self):
        """마지막 기록이 24시간보다 최근이면 recently_active로 추천하지 않고, 24시간 이상이면 추천한다."""
        # Given
        recent, old = "term_claude_recent", "term_claude_old"
        self.session(recent, "claude", FINISHED_TURN, age=DAY - 600)
        self.session(old, "claude", FINISHED_TURN, age=DAY + 5)
        fake = OrphanFake([orphan(recent, "claude"), orphan(old, "claude")])

        # When
        report = self.listing(fake)

        # Then
        items = self.by_handle(report)
        self.assertEqual(("recently_active", None), (items[recent]["failed_check"], items[old]["failed_check"]))

    def test_입력창에_글이_있으면_input_not_empty로_추천하지_않는다(self):
        """입력창에 입력 중인 글이 있는 고아 터미널은 input_not_empty로 나열만 하고 입력은 그대로 남긴다."""
        # Given
        self.session(CLAUDE, "claude", FINISHED_TURN)
        fake = OrphanFake([orphan(CLAUDE, "claude")], typed={CLAUDE: "쓰던 글"})

        # When
        report = self.listing(fake)

        # Then
        self.assertEqual("input_not_empty", self.by_handle(report)[CLAUDE]["failed_check"])
        self.assertEqual("쓰던 글", fake.typed[CLAUDE])

    def test_연결되지_않은_고아는_terminal_unreachable로_추천하지_않는다(self):
        """연결되지 않았거나 쓸 수 없는 고아는 화면을 읽지 못하므로 terminal_unreachable로 나열만 한다."""
        # Given
        self.session(CLAUDE, "claude", FINISHED_TURN)
        fake = OrphanFake([orphan(CLAUDE, "claude", connected=False)])

        # When
        report = self.listing(fake)

        # Then
        self.assertEqual("terminal_unreachable", self.by_handle(report)[CLAUDE]["failed_check"])

    def test_나열은_터미널을_닫지_않는다(self):
        """추천 목록이 있어도 나열과 apply는 어떤 터미널도 닫지 않고 기록 파일도 그대로 둔다."""
        # Given
        path = self.session(CLAUDE, "claude", FINISHED_TURN)
        fake = OrphanFake([orphan(CLAUDE, "claude")])

        # When
        report = self.listing(fake)

        # Then
        self.assertEqual([CLAUDE], report["recommended"])
        self.assertEqual([], fake.closed)
        self.assertEqual([CLAUDE], [item["handle"] for item in fake.terminals()])
        self.assertTrue(path.is_file())

    def test_apply는_유휴_고아_터미널을_닫지_않는다(self):
        """24시간 넘게 쓰지 않은 고아 세션도 apply가 새로고침만 하고 닫지는 않는다."""
        # Given
        self.session(CLAUDE, "claude", FINISHED_TURN, digest="old")
        fake = OrphanFake([orphan(CLAUDE, "claude")], on_send=self.simulate)

        # When
        self.apply(fake)

        # Then
        self.assertEqual([], fake.closed)


class OrphanCloseTest(OrphanCase):
    def test_승인된_터미널만_닫고_Orca_목록에서_사라진다(self):
        """승인한 핸들만 Orca로 닫아 closed로 보고하고, 승인하지 않은 추천 터미널은 열려 있으며 닫은 터미널은 목록에서 사라진다."""
        # Given
        other = "term_claude_other"
        self.session(CLAUDE, "claude", FINISHED_TURN)
        self.session(other, "claude", FINISHED_TURN)
        fake = OrphanFake([orphan(CLAUDE, "claude"), orphan(other, "claude")])

        # When
        report = self.close(fake, [CLAUDE])

        # Then
        self.assertEqual([CLAUDE], fake.closed)
        self.assertEqual(["closed"], [item["status"] for item in report["sessions"]])
        self.assertEqual([other], [item["handle"] for item in fake.terminals()])
        self.assertTrue(report["ok"])

    def test_닫기_직전에_바빠진_터미널은_닫지_않고_이유를_보고한다(self):
        """나열 뒤 새 턴이 시작된 터미널은 닫기 직전 재점검에서 turn_busy로 걸러 닫지 않고 skipped로 보고한다."""
        # Given
        path = self.session(CLAUDE, "claude", FINISHED_TURN)
        fake = OrphanFake([orphan(CLAUDE, "claude")])
        self.assertEqual([CLAUDE], self.listing(fake)["recommended"])
        write_records(path, RUNNING_TURN)
        stamp = time.time() - 2 * DAY
        os.utime(path, (stamp, stamp))

        # When
        report = self.close(fake, [CLAUDE])

        # Then
        self.assertEqual([], fake.closed)
        self.assertEqual(("skipped", "turn_busy"), (report["sessions"][0]["status"], report["sessions"][0]["detail"]))
        self.assertEqual([CLAUDE], [item["handle"] for item in fake.terminals()])
        self.assertFalse(report["ok"])

    def test_닫기_직전에_다시_활동한_터미널은_recently_active로_닫지_않는다(self):
        """나열 뒤 기록이 새로 쓰인 터미널은 닫지 않고 recently_active로 남긴다."""
        # Given
        path = self.session(CLAUDE, "claude", FINISHED_TURN)
        fake = OrphanFake([orphan(CLAUDE, "claude")])
        os.utime(path, None)

        # When
        report = self.close(fake, [CLAUDE])

        # Then
        self.assertEqual([], fake.closed)
        self.assertEqual("recently_active", report["sessions"][0]["detail"])

    def test_닫기_직전에_입력이_생긴_터미널은_닫지_않는다(self):
        """나열 뒤 입력창에 글이 생긴 터미널은 닫지 않고 input_not_empty로 남긴다."""
        # Given
        self.session(CLAUDE, "claude", FINISHED_TURN)
        fake = OrphanFake([orphan(CLAUDE, "claude")], typed={CLAUDE: "새 글"})

        # When
        report = self.close(fake, [CLAUDE])

        # Then
        self.assertEqual([], fake.closed)
        self.assertEqual("input_not_empty", report["sessions"][0]["detail"])

    def test_고아가_아닌_터미널은_승인해도_닫지_않는다(self):
        """고아가 아닌 살아 있는 터미널의 핸들이 넘어와도 닫지 않고 not_orphaned로 보고한다."""
        # Given
        self.session("term_live", "claude", FINISHED_TURN)
        fake = OrphanFake([terminal("term_live", "claude")])

        # When
        report = self.close(fake, ["term_live"])

        # Then
        self.assertEqual([], fake.closed)
        self.assertEqual(("skipped", "not_orphaned"), (report["sessions"][0]["status"], report["sessions"][0]["detail"]))

    def test_목록에_없는_터미널은_terminal_not_found로_건너뛴다(self):
        """이미 사라졌거나 없는 핸들은 닫기를 시도하지 않고 terminal_not_found로 보고한다."""
        # Given
        fake = OrphanFake([])

        # When
        report = self.close(fake, ["term_missing"])

        # Then
        self.assertEqual([], fake.closed)
        self.assertEqual("terminal_not_found", report["sessions"][0]["detail"])

    def test_에이전트가_아닌_고아_터미널은_닫지_않는다(self):
        """에이전트 세션으로 식별되지 않는 고아 셸은 닫지 않고 not_an_agent_session으로 보고한다."""
        # Given
        fake = OrphanFake([orphan("term_shell", None)])

        # When
        report = self.close(fake, ["term_shell"])

        # Then
        self.assertEqual([], fake.closed)
        self.assertEqual("not_an_agent_session", report["sessions"][0]["detail"])

    def test_닫은_터미널과_남긴_터미널을_이유와_함께_각각_보고한다(self):
        """여러 터미널을 승인하면 통과한 터미널은 closed, 걸린 터미널은 skipped와 이유로 각각 보고하고 실행 상태에 저장한다."""
        # Given
        busy = "term_claude_busy"
        self.session(CLAUDE, "claude", FINISHED_TURN)
        self.session(busy, "claude", RUNNING_TURN)
        fake = OrphanFake([orphan(CLAUDE, "claude"), orphan(busy, "claude")])

        # When
        report = self.close(fake, [CLAUDE, busy])

        # Then
        self.assertEqual([("closed", None), ("skipped", "turn_busy")],
                         [(item["status"], item.get("detail")) for item in report["sessions"]])
        self.assertEqual({CLAUDE, busy}, set(refresh.load_run(self.run_id)["closed"]))

    def test_닫기가_목록에_반영되지_않으면_close_unconfirmed로_실패한다(self):
        """닫기를 요청했는데 터미널이 목록에 남아 있으면 closed로 보고하지 않고 close_unconfirmed로 실패한다."""
        # Given
        self.session(CLAUDE, "claude", FINISHED_TURN)
        fake = OrphanFake([orphan(CLAUDE, "claude")], keep_on_close=True)

        # When
        report = self.close(fake, [CLAUDE])

        # Then
        self.assertEqual(("failed", "close_unconfirmed"), (report["sessions"][0]["status"], report["sessions"][0]["detail"]))

    def test_닫아도_기록_파일과_작업_트리는_지우지_않는다(self):
        """닫기는 터미널만 닫고 기록 파일, 표식, 작업 트리 폴더를 지우지 않는다."""
        # Given
        worktree = Path(self.temp.name) / "worktree"
        worktree.mkdir()
        path = self.session(CLAUDE, "claude", FINISHED_TURN)
        fake = OrphanFake([orphan(CLAUDE, "claude", worktreePath=str(worktree))])

        # When
        self.close(fake, [CLAUDE])

        # Then
        self.assertTrue(path.is_file() and worktree.is_dir())
        self.assertTrue((refresh.SESSION_CONTEXT.marker_directory() / f"{CLAUDE}.json").is_file())

    def test_잘못된_핸들이나_빈_목록은_아무것도_닫지_않고_오류를_낸다(self):
        """유효하지 않은 핸들이거나 핸들이 없으면 terminal_invalid로 거부하고 어떤 터미널도 닫지 않는다."""
        # Given
        fake = OrphanFake([orphan(CLAUDE, "claude")])

        # When
        with self.assertRaises(refresh_core.RefreshError) as raised:
            self.close(fake, ["../escape"])

        # Then
        self.assertEqual("terminal_invalid", raised.exception.code)
        self.assertEqual([], fake.closed)

    def test_close_부속_명령은_run_id_없이는_실행되지_않는다(self):
        """close는 --run-id와 --terminal이 모두 필요해서 하나라도 없으면 사용법 오류로 끝나고 실행하지 않는다."""
        # Given
        argv = ["close", "--terminal", CLAUDE]

        # When
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            refresh.main(argv)

        # Then
        self.assertEqual(2, raised.exception.code)


class OrphanCommandTest(OrphanCase):
    def run_main(self, fake, argv):
        output = io.StringIO()
        with patch.object(refresh_orphans, "Orca", return_value=fake), contextlib.redirect_stdout(output):
            code = refresh.main(argv)
        return code, json.loads(output.getvalue())

    def test_orphans_명령은_JSON으로_나열한다(self):
        """orphans --run-id는 고아 터미널과 추천 핸들을 JSON으로 출력하고 아무것도 닫지 않는다."""
        # Given
        self.session(CLAUDE, "claude", FINISHED_TURN)
        fake = OrphanFake([orphan(CLAUDE, "claude")])

        # When
        code, output = self.run_main(fake, ["orphans", "--run-id", self.run_id, "--json"])

        # Then
        self.assertEqual((0, [CLAUDE], []), (code, output["recommended"], fake.closed))

    def test_close_명령은_승인한_터미널만_닫는다(self):
        """close --run-id --terminal은 반복한 핸들만 재점검해 닫고 JSON으로 보고한다."""
        # Given
        other = "term_claude_other"
        self.session(CLAUDE, "claude", FINISHED_TURN)
        self.session(other, "claude", FINISHED_TURN)
        fake = OrphanFake([orphan(CLAUDE, "claude"), orphan(other, "claude")])

        # When
        code, output = self.run_main(fake, ["close", "--run-id", self.run_id, "--terminal", CLAUDE, "--json"])

        # Then
        self.assertEqual((0, [CLAUDE]), (code, fake.closed))
        self.assertEqual(["closed"], [item["status"] for item in output["sessions"]])

    def test_Orca_close는_terminal_close를_해당_핸들로_호출한다(self):
        """Orca.close는 `orca terminal close --terminal <handle> --json`만 호출하고 탭 전체를 닫는 옵션은 붙이지 않는다."""
        # Given
        calls: list[list[str]] = []
        with patch.dict(os.environ, {"ORCA_CLI_COMMAND": "orca"}), \
                patch.object(refresh_orca, "run_json", side_effect=lambda argv, timeout=30.0: calls.append(argv) or {"ok": True, "result": {}}):
            orca = refresh_orca.Orca()

            # When
            orca.close("term_demo")

        # Then
        self.assertEqual([["orca", "terminal", "close", "--terminal", "term_demo", "--json"]], calls)


if __name__ == "__main__":
    unittest.main()
