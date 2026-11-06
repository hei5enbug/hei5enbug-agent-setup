from __future__ import annotations

import json
import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_orca_plugin_refresh as base
from test_orca_plugin_refresh import FakeOrca, refresh, terminal

import refresh_orca
import refresh_sessions

HANDLE = "term_claude"
OTHER = "term_other"
UNKNOWN_COMMAND = {"ok": False, "error": {"code": "invalid_argument", "message": "Unknown command: orchestration inbox"}}


def message(to_handle, read=0):
    return {"id": f"msg_{to_handle}", "to_handle": to_handle, "read": read}


def inbox(*messages):
    return {"ok": True, "result": {"messages": list(messages)}}


def run_show(coordinator):
    return {"ok": True, "result": {"run": {"id": "run_x", "coordinator_handle": coordinator}}}


def worker_list(*workers, cursor=None):
    return {"ok": True, "result": {"workers": list(workers), "nextCursor": cursor}}


def run_list(*ids, cursor=None):
    return {"ok": True, "result": {"runs": [{"id": item} for item in ids], "nextCursor": cursor}}


class MailPendingTest(unittest.TestCase):
    """`Orca.mail_pending` against the orchestration CLI's JSON shapes, with every Orca call answered from a table."""

    def ask(self, answers, handle=HANDLE):
        calls = []

        def answer(argv, **kwargs):
            calls.append(argv[2:-1])
            reply = answers[argv[2]]
            if callable(reply):
                reply = reply(argv)
            if isinstance(reply, Exception):
                raise reply
            return SimpleNamespace(stdout=reply if isinstance(reply, str) else json.dumps(reply), returncode=0)

        with patch.dict(os.environ, {"ORCA_CLI_COMMAND": "orca"}), patch.object(refresh_orca.core, "run", side_effect=answer):
            return refresh_orca.Orca().mail_pending(handle), calls

    def test_받은_편지함이_비어_있으면_호출_한_번으로_메일_없음이다(self):
        """안 읽은 메일이 없으면 수신자를 풀지 않고 inbox만 한 번 부른다."""
        # Given
        answers = {"inbox": inbox(message(HANDLE, read=1))}

        # When
        pending, calls = self.ask(answers)

        # Then
        self.assertFalse(pending)
        self.assertEqual([["inbox", "--limit", "100000", "--full"]], calls)

    def test_터미널_핸들로_온_안_읽은_메일은_그_터미널만_막는다(self):
        """to_handle이 터미널 핸들이면 그 터미널만 대기 중이고 다른 터미널은 막지 않는다."""
        # Given
        answers = {"inbox": inbox(message(OTHER))}

        # When
        mine, _ = self.ask(answers)
        theirs, _ = self.ask(answers, handle=OTHER)

        # Then
        self.assertEqual((False, True), (mine, theirs))

    def test_run_수신자는_코디네이터_터미널로_풀어_막는다(self):
        """run:<id>로 온 안 읽은 메일은 run-show의 coordinator_handle 터미널을 막고, 같은 run은 한 번만 푼다."""
        # Given
        answers = {"inbox": inbox(message("run:run_x"), message("run:run_x")), "run-show": run_show(HANDLE)}

        # When
        pending, calls = self.ask(answers)
        elsewhere, _ = self.ask(answers, handle=OTHER)

        # Then
        self.assertEqual((True, False), (pending, elsewhere))
        self.assertEqual([["inbox", "--limit", "100000", "--full"], ["run-show", "--id", "run_x", "--full"]], calls)

    def test_dispatch_수신자는_모든_run의_작업자_터미널로_풀어_막는다(self):
        """dispatch:<id>는 호출자 run에 묶이지 않도록 run-list의 모든 run과 worker-list의 모든 쪽을 따라 terminal을 찾는다."""
        # Given
        pages = {("run_a", None): worker_list({"dispatchId": "ctx_other", "terminal": OTHER}, cursor="next_a"),
                 ("run_a", "next_a"): worker_list({"dispatchId": "ctx_filler", "terminal": "term_filler"}),
                 ("run_b", None): worker_list({"dispatchId": "ctx_x", "terminal": HANDLE})}

        def workers(argv):
            cursor = argv[argv.index("--cursor") + 1] if "--cursor" in argv else None
            return pages[(argv[argv.index("--run") + 1], cursor)]

        answers = {"inbox": inbox(message("dispatch:ctx_x")), "run-list": run_list("run_a", "run_b"), "worker-list": workers}

        # When
        mine, calls = self.ask(answers)
        theirs, _ = self.ask(answers, handle=OTHER)

        # Then
        self.assertEqual((True, False), (mine, theirs))
        self.assertEqual([["inbox", "--limit", "100000", "--full"], ["run-list"], ["worker-list", "--run", "run_a", "--limit", "100"],
                          ["worker-list", "--run", "run_a", "--limit", "100", "--cursor", "next_a"],
                          ["worker-list", "--run", "run_b", "--limit", "100"]], calls)

    def test_어느_run에도_없는_dispatch로_온_메일은_막지_않고_조회_실패는_막는다(self):
        """worker-list 어디에도 없는 dispatch는 받을 터미널이 없어 막지 않고, run-list나 worker-list가 실패하면 보수적으로 막는다."""
        # Given
        base_answers = {"inbox": inbox(message("dispatch:ctx_gone")), "run-list": run_list("run_a"),
                        "worker-list": worker_list({"dispatchId": "ctx_x", "terminal": OTHER})}
        failing = {"run-list": {**base_answers, "run-list": {"ok": False, "error": {"code": "runtime_unavailable", "message": "down"}}},
                   "worker-list": {**base_answers, "worker-list": {"ok": False, "error": {"code": "runtime_unavailable", "message": "down"}}}}

        # When
        absent, _ = self.ask(base_answers)
        blocked = {name: self.ask(answers)[0] for name, answers in failing.items()}

        # Then
        self.assertFalse(absent)
        self.assertEqual({"run-list": True, "worker-list": True}, blocked)

    def test_받은_편지함이_창을_가득_채우면_안_읽은_메일을_알_수_없어_막는다(self):
        """inbox가 요청한 개수만큼 돌려주면 더 오래된 안 읽은 메일이 창 밖에 있을 수 있어 대기 중으로 본다."""
        # Given
        full = inbox(*[message(OTHER, read=1) for _ in range(refresh_orca.INBOX_LIMIT)])
        short = inbox(*[message(OTHER, read=1) for _ in range(refresh_orca.INBOX_LIMIT - 1)])

        # When
        overflow, _ = self.ask({"inbox": full})
        within, _ = self.ask({"inbox": short})

        # Then
        self.assertEqual((True, False), (overflow, within))

    def test_기록용_메일은_세지_않고_현재_배달_메일과_계약_표시가_없는_메일은_센다(self):
        """delivery_contract가 current_delivery가 아닌 문자열이면 알림이 되지 않으므로 막지 않고, 현재 배달이거나 표시가 없거나 문자열이 아니면 막는다."""
        # Given
        def mail(contract):
            return {"ok": True, "result": {"messages": [{**message(HANDLE), **({} if contract is ... else {"delivery_contract": contract})}]}}

        # When
        verdicts = {name: self.ask({"inbox": mail(contract)})[0]
                    for name, contract in {"audit_only": "audit_only", "legacy_direct": "legacy_direct", "current": "current_delivery",
                                           "absent": ..., "not_text": None}.items()}

        # Then
        self.assertEqual({"audit_only": False, "legacy_direct": False, "current": True, "absent": True, "not_text": True}, verdicts)

    def test_받을_터미널을_알_수_없는_안_읽은_메일은_어느_세션도_막지_않는다(self):
        """코디네이터가 없는 run이나 worker-list에 없는 dispatch의 메일은 어느 세션에도 세지 않는다."""
        # Given
        answers = {"inbox": inbox(message("run:run_x"), message("dispatch:ctx_gone")),
                   "run-show": run_show(None), "run-list": run_list("run_a"),
                   "worker-list": worker_list({"dispatchId": "ctx_x", "terminal": OTHER})}

        # When
        pending, _ = self.ask(answers)

        # Then
        self.assertFalse(pending)

    def test_수신자를_푸는_호출이_실패하면_보수적으로_막는다(self):
        """안 읽은 메일이 있는데 run-show가 실패하면 어느 터미널의 메일인지 몰라 대기 중으로 본다."""
        # Given
        answers = {"inbox": inbox(message("run:run_x")), "run-show": {"ok": False, "error": {"code": "not_found", "message": "gone"}}}

        # When
        pending, _ = self.ask(answers)

        # Then
        self.assertTrue(pending)

    def test_지워진_run으로_온_안_읽은_메일은_어느_세션도_막지_않는다(self):
        """run-show가 run_not_found를 돌려주면 알림을 받을 코디네이터가 없으므로 막지 않는다."""
        # Given
        answers = {"inbox": inbox(message("run:run_gone")), "run-show": {"ok": False, "error": {"code": "run_not_found", "message": "gone"}}}

        # When
        pending, _ = self.ask(answers)

        # Then
        self.assertFalse(pending)

    def test_inbox_호출이_실패하면_보수적으로_막는다(self):
        """시간 초과, 읽을 수 없는 JSON, ok:false, 예상 밖 모양은 모두 대기 중으로 본다."""
        # Given
        failures = {"timeout": refresh.RefreshError("command_timeout", "slow"), "invalid_json": "not json",
                    "rejected": {"ok": False, "error": {"code": "runtime_unavailable", "message": "down"}},
                    "messages_not_list": {"ok": True, "result": {"messages": "oops"}}, "message_not_dict": {"ok": True, "result": {"messages": [3]}},
                    "payload_not_dict": [1], "result_missing": {"ok": True}}
        for name, failure in failures.items():
            with self.subTest(failure=name):
                # When
                pending, _ = self.ask({"inbox": failure})

                # Then
                self.assertTrue(pending)

    def test_Orca가_orchestration_명령을_모르면_메일_없음으로_본다(self):
        """orchestration 명령을 모르는 Orca는 알림을 넣지 않으므로 Unknown command 거절은 막지 않는다."""
        # Given
        answers = {"inbox": UNKNOWN_COMMAND}

        # When
        pending, _ = self.ask(answers)

        # Then
        self.assertFalse(pending)


class MailGateTest(base.DriveTest):
    def pending_session(self, fake):
        self.write_marker(HANDLE, "claude", digest="old")
        return refresh.plan_sessions(fake, self.state, "auto", [])

    def test_메일이_와_있는_동안은_추천_문구_탐침도_명령도_보내지_않고_읽은_뒤에_진행한다(self):
        """안 읽은 메일이 있으면 탐침 글자와 명령을 보내지 않고 orchestration_mail_pending으로 대기하다가, 읽힌 다음 폴링에서 평소처럼 보낸다."""
        # Given
        fake = FakeOrca([terminal(HANDLE, "claude")], ghosts={HANDLE: "추천 문구"}, on_send=self.simulate)
        fake.mail.add(HANDLE)
        sessions = self.pending_session(fake)
        polls = []

        def sleep(seconds):
            polls.append((list(fake.keystrokes), list(fake.sent), sessions[0]["status"], sessions[0]["detail"]))
            if len(polls) == 2:
                fake.mail.clear()

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 60, sleep=sleep)

        # Then
        self.assertEqual(([], [], "pending", "orchestration_mail_pending"), polls[0])
        self.assertEqual(([], [], "pending", "orchestration_mail_pending"), polls[1])
        self.assertEqual("done", sessions[0]["status"])
        self.assertEqual([(HANDLE, "/reload-plugins"), (HANDLE, "/compact")], fake.sent)
        self.assertEqual(refresh.PROBE_KEY, fake.keystrokes[0][1])

    def test_기한까지_메일이_남아_있으면_마지막_사유로_남기고_아무것도_보내지_않는다(self):
        """기한이 지나도 안 읽은 메일이 남아 있으면 건너뛰며 detail은 orchestration_mail_pending이고 입력창은 건드리지 않는다."""
        # Given
        fake = FakeOrca([terminal(HANDLE, "claude")], on_send=self.simulate)
        fake.mail.add(HANDLE)
        sessions = self.pending_session(fake)
        deadline = time.time() + 0.2

        # When
        refresh.drive(fake, sessions, self.state, deadline, sleep=lambda seconds: time.sleep(0.05))

        # Then
        self.assertEqual(("skipped", "orchestration_mail_pending"), (sessions[0]["status"], sessions[0]["detail"]))
        self.assertEqual(([], []), (fake.keystrokes, fake.sent))

    def test_바쁜_세션은_메일_확인_없이_busy로_기다린다(self):
        """호스트 기록이나 Orca가 바쁘다고 하는 세션은 메일 조회 전에 busy로 끝나 조회 비용이 들지 않는다."""
        # Given
        fake = FakeOrca([terminal(HANDLE, "claude")], busy={HANDLE: 10**6})
        fake.mail.add(HANDLE)
        sessions = self.pending_session(fake)

        # When
        refresh.drive(fake, sessions, self.state, time.time() + 0.1, sleep=lambda seconds: time.sleep(0.02))

        # Then
        self.assertEqual("busy", sessions[0]["detail"])

    def test_결과_확인_요청은_메일이_있는_동안_기다렸다가_읽힌_뒤에_보낸다(self):
        """안 읽은 메일이 있는 자기 세션에는 결과 확인 요청을 보내지 않고 기다리다가 메일이 읽힌 뒤에 보낸다."""
        # Given
        fake = FakeOrca([terminal(HANDLE, "claude")])
        fake.mail.add(HANDLE)
        entry = {"handle": HANDLE, "host": "claude"}
        slept = []

        def sleep(seconds):
            slept.append(list(fake.sent))
            if len(slept) == 2:
                fake.mail.clear()

        # When
        outcome = refresh.notify(fake, entry, "e" * 32, sleep=sleep)

        # Then
        self.assertEqual(("sent", [[], []]), (outcome, slept))
        self.assertEqual(1, len(fake.sent))

    def test_결과_확인_요청은_메일이_계속_있으면_보내지_않고_사유를_알린다(self):
        """메일이 끝까지 남으면 입력창에 아무것도 보내지 않고 not_sent:orchestration_mail_pending을 돌려준다."""
        # Given
        fake = FakeOrca([terminal(HANDLE, "claude")])
        fake.mail.add(HANDLE)
        entry = {"handle": HANDLE, "host": "claude"}

        # When
        with patch.object(refresh, "NOTIFY_SECONDS", 0.2):
            outcome = refresh.notify(fake, entry, "e" * 32, sleep=lambda seconds: time.sleep(0.05))

        # Then
        self.assertEqual("not_sent:orchestration_mail_pending", outcome)
        self.assertEqual(([], []), (fake.sent, fake.keystrokes))

    def held_entry(self, fake, left):
        fake.typed[HANDLE] = left
        refresh_sessions.HELD_INPUT[HANDLE] = "draft text"
        self.addCleanup(refresh_sessions.HELD_INPUT.clear)
        return {"handle": HANDLE, "host": "claude", "status": "done", "detail": "applied", "input_held": True}

    def test_복원은_메일이_있는_동안_글도_탐침도_치지_않고_읽힌_뒤에_되돌린다(self):
        """저장해 둔 글을 되돌릴 때 안 읽은 메일이 있으면 기다림 안에서는 키를 치지 않고 붙들고 있다가, 메일이 읽힌 뒤 글을 복원한다."""
        for left in ("", "draft "):
            with self.subTest(left=left):
                # Given
                fake = FakeOrca([terminal(HANDLE, "claude")])
                fake.mail.add(HANDLE)
                entry = self.held_entry(fake, left)

                # When
                waiting = [refresh_sessions.release_held(fake, entry) for _ in range(2)]
                typed_while_waiting = list(fake.keystrokes)
                fake.mail.clear()
                while refresh_sessions.release_held(fake, entry):
                    pass

                # Then
                self.assertEqual(([True, True], []), (waiting, typed_while_waiting))
                self.assertEqual("draft text", fake.draft(HANDLE))
                self.assertEqual(("done", "restored"), (entry["status"], entry["input"]))

    def test_복원은_기다림이_끝나면_메일이_있어도_글을_잃지_않도록_되돌린다(self):
        """메일이 계속 남아도 RESTORE_WAIT_SECONDS가 지나면 새 실패 경로 없이 이전처럼 글을 복원한다."""
        # Given
        fake = FakeOrca([terminal(HANDLE, "claude")])
        fake.mail.add(HANDLE)
        entry = self.held_entry(fake, "")
        entry.update(status="restoring", restore_started=time.time() - refresh_sessions.RESTORE_WAIT_SECONDS - 1,
                     outcome=("done", "applied"))

        # When
        refresh_sessions.release_held(fake, entry)

        # Then
        self.assertEqual("draft text", fake.draft(HANDLE))
        self.assertEqual(("done", "restored"), (entry["status"], entry["input"]))


if __name__ == "__main__":
    unittest.main()
