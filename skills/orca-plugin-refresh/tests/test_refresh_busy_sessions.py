from __future__ import annotations

import contextlib
import io
import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import test_orca_plugin_refresh as base
from test_orca_plugin_refresh import (CLAUDE_EMPTY, FINISHED_TURN, RUNNING_TURN, FakeOrca, assistant_record, refresh, result_record,
                                      terminal, tool_use, turn_end, user_record, write_records)
import test_refresh_resume as resume_base

import refresh_follow
import refresh_interrupt
import refresh_sessions
from refresh_core import RefreshError

HANDLE = "term_demo-a"
RELOADED = {"type": "system", "subtype": "local_command", "content": "<local-command-stdout>Reloaded: 7 plugins</local-command-stdout>"}
REFUSED = {"type": "system", "subtype": "local_command",
           "content": "<local-command-stdout>This reload changes MCP tools. Run /reload-plugins --force to apply it.</local-command-stdout>"}
INTERRUPTED = user_record("[Request interrupted by user for tool use]")
BACKGROUND_TURN = [*FINISHED_TURN, user_record("빌드"), assistant_record(tool_use("Bash", command="sleep 600", run_in_background=True)),
                   result_record("Command running in background with ID: bg1"), assistant_record()]
PERMISSION = ["Bash command", "  rm -rf demo", "Do you want to proceed?", "❯ 1. Yes", "  2. No, and tell Claude what to do differently"]
PLACEHOLDER = "[Pasted text #1 +20 lines]"
ESC = "\x1b"
CHOICES = ["wait", "interrupt", "skip"]
ORPHANS = {"ok": True, "run_id": "a" * 32, "orphans": [], "recommended": []}


def setUpModule():
    base.setUpModule()


def tearDownModule():
    base.tearDownModule()


def forced(fake) -> list[str]:
    return [text for _, text in [*fake.sent, *fake.keystrokes] if "--force" in text]


class BusyCase(unittest.TestCase):
    setUp = base.DriveTest.setUp
    write_marker = base.DriveTest.write_marker

    def tearDown(self):
        for fake in getattr(self, "fakes", []):
            self.assertEqual([], forced(fake), "no answer or default may pass --force")

    def orca(self, *args, **kwargs) -> FakeOrca:
        fake = FakeOrca(*args, **kwargs)
        self.fakes = [*getattr(self, "fakes", []), fake]
        return fake

    def running(self, records=RUNNING_TURN, digest="d", handle=HANDLE, partial=""):
        path = write_records(Path(self.temp.name) / f"{handle}.jsonl", records, partial)
        self.write_marker(handle, "claude", digest=digest, transcript=path)
        return path

    def save_run(self, **extra):
        run_id = "a" * 32
        refresh.save_json(refresh.run_path(run_id), {**self.state, "run_id": run_id, **extra})
        return run_id

    def apply(self, fake, run_id=None, seconds=0.3, sleep=lambda seconds: time.sleep(0.01), mode="auto", spawned=None):
        run_id = run_id or self.save_run()
        spawned = [] if spawned is None else spawned
        with patch.object(refresh, "Orca", return_value=fake):
            return refresh.command_apply(run_id, mode, [], seconds, spawn=lambda run: spawned.append(run) or 4242, sleep=sleep)

    def decide(self, fake, run_id, *answers, **kwargs):
        with patch.object(refresh, "Orca", return_value=fake):
            return refresh.command_decide(run_id, list(answers), spawn=kwargs.pop("spawn", lambda run: 4242), **kwargs)

    def helper(self, fake, run_id, sleep=lambda seconds: time.sleep(0.01)):
        with patch.object(refresh, "Orca", return_value=fake):
            refresh.command_self_apply(run_id, sleep=sleep)
        return refresh.command_status(run_id)

    def queued_entry(self, path, queued, actions=None, **extra):
        now = time.time()
        return {"handle": HANDLE, "host": "claude", "actions": list(actions or queued), "queued": list(queued), "status": "pending",
                "detail": "commands_queued", "deadline": now + 0.3, "deferred_at": now, "queued_at": now,
                "queue_transcript": str(path), "queue_offset": path.stat().st_size, "handoff_transcript": str(path),
                "handoff_offset": path.stat().st_size, **extra}

    def follow(self, fake, entries, sleep=lambda seconds: time.sleep(0.01)):
        refresh.follow_up(fake, entries, self.state, sleep=sleep)

    def append(self, path, *records):
        with path.open("a") as stream:
            for record in records:
                stream.write(json.dumps(record) + "\n")

    def assert_asked(self, result, fake, reason):
        asked = result["sessions"][0]
        self.assertEqual(("awaiting_answer", reason), (asked["status"], asked["detail"]))
        self.assertEqual([], fake.sent)
        self.assertEqual([], fake.keystrokes)
        self.assertEqual(1, len(result["questions"]))
        question = result["questions"][0]
        self.assertEqual((reason, CHOICES), (question["reason"], [option["choice"] for option in question["options"]]))
        self.assertTrue(all(option["effect"] for option in question["options"]))
        self.assertTrue(result["ok"])
        return question


class QueueBusySessionTest(BusyCase):
    def test_지침이_낡은_바쁜_세션에는_Esc_없이_reload와_compact를_대기열에_넣는다(self):
        """term_demo-a: 차례가 진행 중이고 입력줄이 비었으며 지침이 낡았으면 첫 패스에서 /reload-plugins와 /compact를 Esc 없이 보내고 commands_queued인 deferred로 보고한다."""
        # Given
        self.running(digest="old")
        fake = self.orca([terminal(HANDLE, "claude")], busy={HANDLE: 10**6})

        # When
        result = self.apply(fake)

        # Then
        self.assertEqual([(HANDLE, "/reload-plugins"), (HANDLE, "/compact")], fake.sent)
        self.assertNotIn(ESC, [text for _, text in fake.keystrokes])
        view = result["sessions"][0]
        self.assertEqual(("deferred", "commands_queued", ["reload", "compact"]), (view["status"], view["detail"], view["queued"]))
        self.assertEqual([], result["questions"])

    def test_지침이_현재인_바쁜_세션에는_reload만_대기열에_넣는다(self):
        """term_demo-a: 표식 지침이 설치본과 같으면 바쁜 세션에도 /compact 없이 /reload-plugins만 보낸다."""
        # Given
        self.running(digest="d")
        fake = self.orca([terminal(HANDLE, "claude")], busy={HANDLE: 10**6})

        # When
        result = self.apply(fake)

        # Then
        self.assertEqual([(HANDLE, "/reload-plugins")], fake.sent)
        self.assertEqual(["reload"], result["sessions"][0]["queued"])

    def test_복원할_수_있는_입력은_명령을_넣은_뒤_apply가_돌아오기_전에_입력줄에_되돌린다(self):
        """term_demo-a: 입력줄에 복원 가능한 글 demo text가 있으면 명령을 대기열에 넣은 뒤 apply가 반환하기 전에 같은 글이 입력줄에 돌아와 있고 input이 restored이다."""
        # Given
        self.running()
        fake = self.orca([terminal(HANDLE, "claude")], typed={HANDLE: "demo text"})

        # When
        result = self.apply(fake, seconds=5, sleep=lambda seconds: None)

        # Then
        self.assertEqual([(HANDLE, "/reload-plugins")], fake.sent)
        self.assertEqual("demo text", fake.draft(HANDLE))
        view = result["sessions"][0]
        self.assertEqual(("deferred", "commands_queued", "restored"), (view["status"], view["detail"], view["input"]))

    def test_기록의_마지막_줄이_한_번만_덜_써졌다_완성되면_묻지_않고_대기열에_넣는다(self):
        """term_demo-a: 기록의 마지막 줄이 처음에만 덜 써져 있고 다음 폴링에 완성되면 질문 없이 명령을 대기열에 넣는다."""
        # Given
        path = self.running(partial='{"type": "assis')
        complete = Path(self.temp.name) / "complete.jsonl"
        write_records(complete, RUNNING_TURN)
        fake = self.orca([terminal(HANDLE, "claude")], busy={HANDLE: 10**6})
        calls = []

        def finish_line(seconds):
            calls.append(seconds)
            path.write_text(complete.read_text())

        # When
        result = self.apply(fake, seconds=5, sleep=finish_line)

        # Then
        self.assertEqual([(HANDLE, "/reload-plugins")], fake.sent)
        self.assertEqual(("deferred", "commands_queued"), (result["sessions"][0]["status"], result["sessions"][0]["detail"]))
        self.assertEqual([], result["questions"])

    def test_시작_세션은_차례가_진행_중이어도_queued_after_turn을_유지한다(self):
        """term_self: 스킬을 실행하는 세션은 바쁜 차례에도 명령을 입력하지 않고 queued_after_turn으로 도우미에 맡긴다."""
        # Given
        self.running(handle="term_self")
        fake = self.orca([terminal("term_self", "claude")], busy={"term_self": 10**6})

        # When
        result = self.apply(fake)

        # Then
        self.assertEqual(("queued_after_turn", "waits_for_this_turn_to_end"), (result["sessions"][0]["status"], result["sessions"][0]["detail"]))
        self.assertEqual(([], []), (fake.sent, fake.keystrokes))
        self.assertEqual([], result["questions"])


    def test_첫_명령을_넣은_뒤_대화상자가_열리면_두_번째_명령은_넣지_않고_보낸_명령만_queued로_보고한다(self):
        """term_demo-a: /reload-plugins를 넣은 직후 권한 대화상자가 열리면 /compact는 입력하지 않고, queued에는 보낸 reload만 담으며, 대화상자가 닫히고 차례가 끝난 뒤 도우미가 compact를 보통 경로로 한 번 보낸다."""
        # Given
        path = self.running(digest="old")

        def simulate(fake, handle, text):
            if text == "/reload-plugins":
                fake.screens[handle] = list(PERMISSION)
                self.append(path, RELOADED)
            else:
                self.write_marker(handle, "claude", digest="d", transcript=path)

        fake = self.orca([terminal(HANDLE, "claude")], busy={HANDLE: 10**6}, on_send=simulate)
        run_id = self.save_run()

        # When
        applied = self.apply(fake, run_id=run_id)
        fake.screens[HANDLE] = list(CLAUDE_EMPTY)
        self.append(path, turn_end())
        fake.busy[HANDLE] = 0
        status = self.helper(fake, run_id)

        # Then
        view = applied["sessions"][0]
        self.assertEqual(("deferred", "commands_queued", ["reload"]), (view["status"], view["detail"], view["queued"]))
        self.assertEqual([(HANDLE, "/reload-plugins"), (HANDLE, "/compact")], fake.sent)
        self.assertEqual(("done", ["reload", "compact"]), (status["sessions"][0]["status"], status["sessions"][0]["completed"]))

    def test_입력줄을_못_읽는_바쁜_세션은_예외_대신_state_unreadable로_묻는다(self):
        """term_demo-a: 차례가 진행 중인 것을 아는 세션의 화면을 읽다 예외가 나면 실패가 아니라 아무것도 보내지 않고 state_unreadable 질문을 돌려준다."""
        # Given
        self.running()
        fake = self.orca([terminal(HANDLE, "claude")])

        def unreadable(handle):
            raise RefreshError("orca_invalid", "screen unreadable")

        fake.screen = unreadable

        # When
        result = self.apply(fake)

        # Then
        question = self.assert_asked(result, fake, "state_unreadable")
        self.assertIs(False, question["background"])


class AskBusySessionTest(BusyCase):
    def companion(self, *, declares=None, previous_exists=True):
        old, new = Path(self.temp.name) / "demo-plugin-1.0.0", Path(self.temp.name) / "demo-plugin-1.1.0"
        for folder in ([old] if previous_exists else []) + [new]:
            (folder / ".claude-plugin").mkdir(parents=True)
            (folder / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "demo-plugin", **(declares or {})}))
        plugin = {"plugin": "demo-plugin@demo-market", "status": "updated", "before_version": "1.0.0", "after_version": "1.1.0",
                  "previous_root": str(old), "root": str(new)}
        self.state["hosts"]["claude"]["plugins"] = [plugin]
        return new

    def test_권한_대화상자가_열린_바쁜_세션은_키를_보내지_않고_dialog_open으로_묻는다(self):
        """term_demo-a: 화면에 권한 요청이 열려 있으면 입력도 Esc도 보내지 않고 dialog_open 질문 하나를 세 선택지와 함께 돌려주며 Esc가 열린 요청을 거절한다고 알린다."""
        # Given
        self.running()
        fake = self.orca([terminal(HANDLE, "claude")], screens={HANDLE: PERMISSION})
        spawned: list[str] = []

        # When
        result = self.apply(fake, spawned=spawned)

        # Then
        question = self.assert_asked(result, fake, "dialog_open")
        self.assertIs(False, question["background"])
        interrupt = next(option for option in question["options"] if option["choice"] == "interrupt")["effect"]
        self.assertIn("declines the open prompt", interrupt)
        self.assertEqual([], spawned)
        self.assertNotIn("follow_up", refresh.load_run(result["run_id"]))

    def test_붙여넣기_자리표시자가_있는_초안은_지우지도_탐침도_하지_않고_input_not_restorable로_묻는다(self):
        """term_demo-a: 초안이 붙여넣기 자리표시자이면 탐침 글자도 지우기도 없이 input_not_restorable로 묻고 입력줄은 그대로다."""
        # Given
        self.running()
        fake = self.orca([terminal(HANDLE, "claude")], typed={HANDLE: PLACEHOLDER})

        # When
        result = self.apply(fake)

        # Then
        self.assert_asked(result, fake, "input_not_restorable")
        self.assertEqual(PLACEHOLDER, fake.draft(HANDLE))

    def test_읽지_않은_조율_메일이_있는_바쁜_세션은_입력_없이_orchestration_mail_pending으로_묻는다(self):
        """term_demo-a: Orca가 읽지 않은 조율 메일을 가진 세션에는 탐침 글자도 명령도 보내지 않고 orchestration_mail_pending으로 묻는다."""
        # Given
        self.running()
        fake = self.orca([terminal(HANDLE, "claude")], typed={HANDLE: "demo text"})
        fake.mail.add(HANDLE)

        # When
        result = self.apply(fake)

        # Then
        self.assert_asked(result, fake, "orchestration_mail_pending")

    def test_MCP_서버를_선언한_플러그인이_이번_실행에서_바뀌면_reload_needs_force로_묻는다(self):
        """term_demo-a: 이번 실행이 바꾼 동반 플러그인의 설치 폴더에 .mcp.json이 있으면 명령을 보내지 않고 reload_needs_force로 묻는다."""
        # Given
        (self.companion() / ".mcp.json").write_text("{}")
        self.running()
        fake = self.orca([terminal(HANDLE, "claude")])

        # When
        result = self.apply(fake)

        # Then
        self.assert_asked(result, fake, "reload_needs_force")

    def test_plugin_json에_mcpServers가_있는_플러그인이_바뀌어도_reload_needs_force로_묻는다(self):
        """term_demo-a: .mcp.json이 없어도 plugin.json의 mcpServers 키가 서버를 선언하면 reload_needs_force로 묻는다."""
        # Given
        self.companion(declares={"mcpServers": {"demo": {"command": "demo"}}})
        self.running()
        fake = self.orca([terminal(HANDLE, "claude")])

        # When
        result = self.apply(fake)

        # Then
        self.assert_asked(result, fake, "reload_needs_force")

    def test_옛_폴더를_읽을_수_없으면_알_수_없어_reload_needs_force로_묻는다(self):
        """term_demo-a: 바뀐 플러그인의 적재된 옛 폴더가 사라졌으면 예측할 수 없으므로 reload_needs_force로 묻는다."""
        # Given
        self.companion(previous_exists=False)
        self.running()
        fake = self.orca([terminal(HANDLE, "claude")])

        # When
        result = self.apply(fake)

        # Then
        self.assert_asked(result, fake, "reload_needs_force")

    def test_MCP_서버가_없는_플러그인이_바뀌면_묻지_않고_대기열에_넣는다(self):
        """term_demo-a: 바뀐 플러그인이 MCP 서버를 선언하지 않으면 질문 없이 명령을 대기열에 넣는다."""
        # Given
        self.companion()
        self.running()
        fake = self.orca([terminal(HANDLE, "claude")])

        # When
        result = self.apply(fake)

        # Then
        self.assertEqual([(HANDLE, "/reload-plugins")], fake.sent)
        self.assertEqual([], result["questions"])

    def test_기록의_마지막_줄이_끝까지_덜_써져_있으면_state_unreadable로_묻고_모른다고_알린다(self):
        """term_demo-a: 기록의 마지막 줄이 기한까지 덜 써진 채면 아무것도 보내지 않고 state_unreadable로 묻고 background는 null(모름)이다."""
        # Given
        self.running(partial='{"type": "assis')
        fake = self.orca([terminal(HANDLE, "claude")], busy={HANDLE: 10**9})

        # When
        result = self.apply(fake)

        # Then
        question = self.assert_asked(result, fake, "state_unreadable")
        self.assertIsNone(question["background"])

    def test_백그라운드_작업이_남은_세션의_질문은_background가_true이다(self):
        """term_demo-a: 대화 기록에 알림이 남은 백그라운드 명령이 있으면 질문의 background가 true이다."""
        # Given
        self.running(BACKGROUND_TURN)
        fake = self.orca([terminal(HANDLE, "claude")], screens={HANDLE: PERMISSION})

        # When
        result = self.apply(fake)

        # Then
        question = self.assert_asked(result, fake, "dialog_open")
        self.assertIs(True, question["background"])


class QuestionCommandsTest(BusyCase):
    def asked(self, fake=None, typed=None):
        self.running()
        fake = fake or self.orca([terminal(HANDLE, "claude")], screens={HANDLE: PERMISSION})
        return fake, self.apply(fake)

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = refresh.main(list(argv))
        return code, json.loads(out.getvalue())

    def test_refresh_출력과_status가_질문을_나열하고_다른_결과가_ok면_종료_코드_0이다(self):
        """term_demo-a: refresh는 apply의 질문을 최상위 questions에 담고 status도 같은 질문을 나열하며, 나머지가 ok이면 종료 코드는 0이다."""
        # Given
        self.running()
        fake = self.orca([terminal(HANDLE, "claude")], screens={HANDLE: PERMISSION})
        run_id = self.save_run()
        update = {"ok": True, "run_id": run_id, "hosts": {"claude": {"before_version": "1.0.0", "after_version": "1.0.0", "plugins": []}}}

        # When
        with patch.object(refresh, "command_update", return_value=update), patch.object(refresh, "run_orphans", return_value=ORPHANS), \
                patch.object(refresh, "Orca", return_value=fake):
            code, output = self.run_main("refresh", "--json")

        # Then
        self.assertEqual(0, code)
        self.assertTrue(output["ok"])
        self.assertEqual(["q1"], [question["id"] for question in output["questions"]])
        self.assertEqual(output["questions"], output["apply"]["questions"])
        status = refresh.command_status(run_id)
        self.assertEqual(["q1"], [question["id"] for question in status["questions"]])
        self.assertEqual(1, status["unanswered"])

    def test_알_수_없는_질문_id와_이미_답한_질문에_다른_선택을_하면_question_unknown이고_같은_선택은_무시한다(self):
        """term_demo-a: 없는 질문 id와 이미 답한 질문에 다른 선택을 하면 아무것도 하지 않고 question_unknown(종료 코드 2)이며, 같은 선택을 되풀이하면 오류 없이 무시하고 아무것도 보내지 않는다."""
        # Given
        fake, result = self.asked()
        run_id = result["run_id"]
        self.decide(fake, run_id, "q1=skip")

        # When
        with patch.object(refresh, "Orca", return_value=fake):
            unknown_code, unknown = self.run_main("decide", "--run-id", run_id, "--answer", "q9=skip", "--json")
            other_code, other = self.run_main("decide", "--run-id", run_id, "--answer", "q1=interrupt", "--json")
            same_code, same = self.run_main("decide", "--run-id", run_id, "--answer", "q1=skip", "--json")

        # Then
        self.assertEqual((2, "question_unknown"), (unknown_code, unknown["error"]["code"]))
        self.assertEqual((2, "question_unknown"), (other_code, other["error"]["code"]))
        self.assertEqual((0, [], ["q1"]), (same_code, same["sessions"], [question["id"] for question in same["questions"]]))
        self.assertEqual(([], []), (fake.sent, fake.keystrokes))

    def test_skip_답은_아무것도_보내지_않고_skipped_by_user로_끝낸다(self):
        """term_demo-a: skip을 고르면 키도 명령도 보내지 않고 skipped_by_user로 끝내며 질문에 답이 기록된다."""
        # Given
        fake, result = self.asked()

        # When
        decided = self.decide(fake, result["run_id"], "q1=skip")

        # Then
        self.assertEqual(("skipped", "skipped_by_user"), (decided["sessions"][0]["status"], decided["sessions"][0]["detail"]))
        self.assertEqual(([], []), (fake.sent, fake.keystrokes))
        self.assertTrue(decided["ok"])
        self.assertEqual("skip", refresh.load_run(result["run_id"])["questions"]["q1"]["answer"])

    def test_붙여넣기_자리표시자_세션에_wait를_답하면_도우미는_줄이_그대로인_동안_보내지도_지우지도_않는다(self):
        """term_demo-a: input_not_restorable 질문에 wait를 답하면 세션이 쉬어도 자리표시자가 줄에 있는 동안 도우미는 아무것도 보내거나 지우지 않고, 한도에 이르면 그 이유로 skipped가 된다."""
        # Given
        path = self.running()
        fake = self.orca([terminal(HANDLE, "claude")], typed={HANDLE: PLACEHOLDER})
        result = self.apply(fake)
        decided = self.decide(fake, result["run_id"], "q1=wait")
        self.append(path, assistant_record(), turn_end())

        # When
        with patch.object(refresh, "FOLLOW_UP_SECONDS", 0.5):
            status = self.helper(fake, result["run_id"])

        # Then
        self.assertEqual("deferred", decided["sessions"][0]["status"])
        self.assertTrue(refresh.load_run(result["run_id"])["follow_up"][0]["keep_unrestorable_input"])
        self.assertEqual(([], []), (fake.sent, fake.keystrokes))
        self.assertEqual(PLACEHOLDER, fake.draft(HANDLE))
        self.assertEqual(("skipped", "input_not_restorable"), (status["sessions"][0]["status"], status["sessions"][0]["detail"]))

    def test_자리표시자가_사라져_줄이_비면_wait로_맡긴_도우미가_그때_명령을_보낸다(self):
        """term_demo-a: input_not_restorable 질문에 wait를 답한 세션은 입력줄이 비면 도우미가 /reload-plugins를 한 번 보내 done으로 끝낸다."""
        # Given
        path = self.running()
        fake = self.orca([terminal(HANDLE, "claude")], typed={HANDLE: PLACEHOLDER},
                         on_send=lambda orca, handle, text: self.append(path, RELOADED))
        result = self.apply(fake)
        self.decide(fake, result["run_id"], "q1=wait")
        self.append(path, assistant_record(), turn_end())
        fake.typed[HANDLE] = ""

        # When
        status = self.helper(fake, result["run_id"])

        # Then
        self.assertEqual([(HANDLE, "/reload-plugins")], fake.sent)
        self.assertEqual("done", status["sessions"][0]["status"])


    def test_답이_없거나_skip인_세션은_같은_run에서_apply를_다시_해도_건드리지_않는다(self):
        """term_demo-a: 답을 기다리는 세션과 skip으로 답한 세션은 대화상자가 닫힌 뒤 같은 run에서 apply를 다시 해도 아무것도 보내지 않고, 기다리는 질문은 그대로 다시 돌려주며 skip은 skipped_by_user로 남는다."""
        # Given
        self.running()
        fake = self.orca([terminal(HANDLE, "claude")], screens={HANDLE: PERMISSION})
        run_id = self.save_run()
        self.apply(fake, run_id=run_id)
        fake.screens[HANDLE] = list(CLAUDE_EMPTY)

        # When
        waiting = self.apply(fake, run_id=run_id)
        self.decide(fake, run_id, "q1=skip")
        skipped = self.apply(fake, run_id=run_id)

        # Then
        self.assertEqual(("awaiting_answer", ["q1"]), (waiting["sessions"][0]["status"], [question["id"] for question in waiting["questions"]]))
        self.assertEqual(([], []), (fake.sent, fake.keystrokes))
        self.assertEqual(("skipped", "skipped_by_user", []), (skipped["sessions"][0]["status"], skipped["sessions"][0]["detail"], skipped["questions"]))
        self.assertTrue(skipped["ok"])

    def test_대화상자와_붙여넣기가_함께_있어도_wait를_답하면_도우미는_붙여넣은_글을_지우지_않는다(self):
        """term_demo-a: 권한 대화상자 때문에 묻는 세션의 줄에 붙여넣기 자리표시자가 있으면 wait를 답한 뒤 대화상자가 닫히고 차례가 끝나도 도우미는 아무것도 보내거나 지우지 않고, 한도에 이르면 input_not_restorable로 건너뛴다."""
        # Given
        path = self.running()
        fake = self.orca([terminal(HANDLE, "claude")], screens={HANDLE: PERMISSION}, typed={HANDLE: PLACEHOLDER})
        result = self.apply(fake)
        self.decide(fake, result["run_id"], "q1=wait")
        fake.screens[HANDLE] = list(CLAUDE_EMPTY)
        self.append(path, assistant_record(), turn_end())

        # When
        with patch.object(refresh, "FOLLOW_UP_SECONDS", 0.5):
            status = self.helper(fake, result["run_id"])

        # Then
        self.assertEqual("dialog_open", result["questions"][0]["reason"])
        self.assertEqual(([], []), (fake.sent, fake.keystrokes))
        self.assertEqual(PLACEHOLDER, fake.draft(HANDLE))
        self.assertEqual(("skipped", "input_not_restorable"), (status["sessions"][0]["status"], status["sessions"][0]["detail"]))

    def test_붙여넣기가_있어_wait한_세션은_차례가_진행_중이어도_줄이_비면_도우미가_바로_대기열에_넣는다(self):
        """term_demo-a: input_not_restorable에 wait를 답한 세션의 줄이 차례가 아직 진행 중일 때 비면 도우미는 쉬기를 기다리지 않고 /reload-plugins를 한 번 대기열에 넣는다."""
        # Given
        path = self.running()
        fake = self.orca([terminal(HANDLE, "claude")], typed={HANDLE: PLACEHOLDER}, on_send=lambda orca, handle, text: self.append(path, RELOADED))
        result = self.apply(fake)
        self.decide(fake, result["run_id"], "q1=wait")
        fake.typed[HANDLE] = ""
        fake.busy[HANDLE] = 10**6

        # When
        with patch.object(refresh, "FOLLOW_UP_SECONDS", 2):
            status = self.helper(fake, result["run_id"])

        # Then
        self.assertEqual([(HANDLE, "/reload-plugins")], fake.sent)
        self.assertEqual("done", status["sessions"][0]["status"])

    def test_두_번째_세션에서_decide가_실패해도_첫_답은_저장되어_다시_해도_첫_세션에_Esc를_다시_보내지_않는다(self):
        """term_demo-a, term_demo-b: 두 interrupt 답 가운데 두 번째 터미널이 Esc를 거부해 decide가 중간에 실패해도 첫 답과 결과는 저장되어, 같은 답으로 다시 해도 첫 세션에는 Esc가 한 번만 나가고 둘째가 처리된다."""
        # Given
        handles = ("term_demo-a", "term_demo-b")
        paths = {handle: self.running(handle=handle) for handle in handles}
        fake = self.orca([terminal(handle, "claude") for handle in handles], screens={handle: PERMISSION for handle in handles})
        rejected = [True]

        def on_keys(orca, handle, text):
            if text != ESC:
                return
            orca.typed[handle] = ""
            if handle == handles[1] and rejected:
                rejected.clear()
                raise RefreshError("orca_rejected", "Esc rejected")
            self.append(paths[handle], INTERRUPTED)
            orca.screens[handle] = list(CLAUDE_EMPTY)

        fake.on_keys = on_keys
        fake.on_send = lambda orca, handle, text: self.append(paths[handle], RELOADED) if text == "/reload-plugins" else None
        result = self.apply(fake)
        answers = ["q1=interrupt", "q2=interrupt"]

        # When
        with self.assertRaises(RefreshError):
            self.decide(fake, result["run_id"], *answers)
        retried = self.decide(fake, result["run_id"], *answers)

        # Then
        escapes = [handle for handle, text in fake.keystrokes if text == ESC]
        self.assertEqual({handles[0]: 1, handles[1]: 2}, {handle: escapes.count(handle) for handle in handles})
        self.assertEqual(["done"], [view["status"] for view in retried["sessions"]])
        self.assertEqual(0, refresh.command_status(result["run_id"])["unanswered"])


class HelperQueuedTest(BusyCase):
    def test_차례가_진행_중이면_도우미는_대기열의_명령이_실행되기_전까지_아무것도_보내지_않는다(self):
        """term_demo-a: 대기열 항목의 차례가 아직 진행 중이면 도우미는 아무것도 보내지 않고, 한 시간 한도에 이르면 queued_unconfirmed로 건너뛴다."""
        # Given
        path = self.running(digest="old")
        entries = [self.queued_entry(path, ["reload", "compact"])]
        fake = self.orca([terminal(HANDLE, "claude")], busy={HANDLE: 10**9})

        # When
        self.follow(fake, entries)

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual(("skipped", "queued_unconfirmed"), (entries[0]["status"], entries[0]["detail"]))

    def test_기록에_reload_결과가_있고_표식이_다시_쓰이면_도우미가_두_동작을_다시_보내지_않고_done으로_끝낸다(self):
        """term_demo-a: 대기열에 넣은 뒤 기록에 reload 결과가 생기고 표식이 새 지침으로 다시 쓰이면 두 동작이 확인되어 done이 되고 아무 명령도 다시 보내지 않는다."""
        # Given
        path = self.running(digest="old")
        entries = [self.queued_entry(path, ["reload", "compact"])]
        entries[0]["deadline"] = time.time() + 10
        fake = self.orca([terminal(HANDLE, "claude")], busy={HANDLE: 10**9})
        calls = []

        def evidence(seconds):
            time.sleep(0.01)
            calls.append(seconds)
            if len(calls) == 3:
                self.append(path, RELOADED)
            if len(calls) == 6:
                self.write_marker(HANDLE, "claude", digest="d", transcript=path)

        # When
        self.follow(fake, entries, sleep=evidence)

        # Then
        self.assertEqual([], fake.sent)
        self.assertEqual(("done", ["reload", "compact"], []), (entries[0]["status"], entries[0]["completed"], entries[0]["queued"]))

    def test_대기열에_넣은_reload가_MCP_도구_거절을_받으면_reload_needs_force로_실패한다(self):
        """term_demo-a: 대기열의 reload에 Claude Code가 MCP 도구 변경 거절로 답하면 failed와 reload_needs_force로 끝내고 --force는 보내지 않는다."""
        # Given
        path = self.running()
        entries = [self.queued_entry(path, ["reload"])]
        self.append(path, REFUSED)
        fake = self.orca([terminal(HANDLE, "claude")])

        # When
        self.follow(fake, entries)

        # Then
        self.assertEqual(("failed", "reload_needs_force"), (entries[0]["status"], entries[0]["detail"]))
        self.assertEqual([], fake.sent)

    def test_차례가_끝나고_시간제한이_지나도_증거가_없으면_남은_동작을_한_번씩_보통_경로로_보낸다(self):
        """term_demo-a: 차례가 끝난 뒤 reload와 compact의 시간제한이 증거 없이 지나면 대기열을 버리고 남은 동작 각각을 한 번만 보내 done으로 끝낸다."""
        # Given
        path = self.running(FINISHED_TURN, digest="old")
        entries = [self.queued_entry(path, ["reload", "compact"])]
        entries[0]["deadline"] = time.time() + 30

        def simulate(fake, handle, text):
            if text == "/reload-plugins":
                self.append(path, RELOADED)
            else:
                self.write_marker(handle, "claude", digest="d", transcript=path)

        fake = self.orca([terminal(HANDLE, "claude")], on_send=simulate)

        # When
        with patch.object(refresh_sessions, "RELOAD_TIMEOUT", 0.05), patch.object(refresh_sessions, "COMPACT_TIMEOUT", 0.05):
            self.follow(fake, entries)

        # Then
        self.assertEqual([(HANDLE, "/reload-plugins"), (HANDLE, "/compact")], fake.sent)
        self.assertEqual(("done", []), (entries[0]["status"], entries[0]["queued"]))

    def test_점검과_전송_사이에_차례가_끝나도_같은_명령이_나가고_도우미가_done으로_확인한다(self):
        """term_demo-a: 점검과 전송 사이에 차례가 끝나 명령이 보통 명령으로 실행되어도 같은 두 명령이 한 번씩 나가고, 도우미가 기록과 표식으로 done을 확인한다."""
        # Given
        path = self.running(digest="old")

        def simulate(fake, handle, text):
            if text == "/reload-plugins":
                self.append(path, turn_end(), RELOADED)
            else:
                self.write_marker(handle, "claude", digest="d", transcript=path)

        fake = self.orca([terminal(HANDLE, "claude")], busy={HANDLE: 10**6}, on_send=simulate)
        run_id = self.save_run()
        applied = self.apply(fake, run_id=run_id)

        # When
        status = self.helper(fake, run_id)

        # Then
        self.assertEqual("commands_queued", applied["sessions"][0]["detail"])
        self.assertEqual([(HANDLE, "/reload-plugins"), (HANDLE, "/compact")], fake.sent)
        self.assertEqual(("done", ["reload", "compact"]), (status["sessions"][0]["status"], status["sessions"][0]["completed"]))


class InterruptTest(resume_base.ResumeCase):
    """Answer `interrupt` with the process table and resume fixtures of the resume tests."""

    def setUp(self):
        super().setUp()
        for module, name, value in ((refresh_interrupt, "INTERRUPT_SECONDS", 0.05), (refresh_interrupt, "CONTINUE_SECONDS", 2.0)):
            patcher = patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.log: list[tuple[str, str]] = []
        self.stops_turn = True
        self.fake.on_keys = self.on_keys
        self.fake.on_send = self.record_send
        self.fake.screens[resume_base.HANDLE] = list(PERMISSION)

    def mark(self, digest):
        marker = refresh.SESSION_CONTEXT.marker_directory() / f"{resume_base.HANDLE}.json"
        marker.write_text(json.dumps({**json.loads(marker.read_text()), "digest": digest}))

    def on_keys(self, fake, handle, text):
        self.log.append(("keys", text))
        if text == ESC:
            fake.typed[handle] = ""
            if self.stops_turn:
                with self.transcript.open("a") as stream:
                    stream.write(json.dumps(INTERRUPTED) + "\n")
                fake.screens[handle] = list(CLAUDE_EMPTY)

    def record_send(self, fake, handle, text):
        self.log.append(("send", "resume" if "--resume" in text else text))
        if text == "/compact":
            self.write_marker("compact", written_at=resume_base.LATER())
        else:
            self.simulate(fake, handle, text)

    def asked(self, records, digest="old"):
        write_records(self.transcript, records)
        self.mark(digest)
        with patch.object(refresh, "Orca", return_value=self.fake):
            return refresh.command_apply(self.run_id, "auto", [], 0.3, spawn=lambda run: 1, sleep=lambda seconds: None)

    def interrupt(self):
        with patch.object(refresh, "Orca", return_value=self.fake):
            return refresh.command_decide(self.run_id, ["q1=interrupt"], spawn=lambda run: 1, sleep=lambda seconds: None)

    def tearDown(self):
        self.assertEqual([], forced(self.fake))

    def test_남은_백그라운드_작업이_없으면_Esc_한_번_뒤_종료와_재개를_하고_compact_없이_이어서_작업하라고_보낸다(self):
        """term_claude: interrupt를 답하면 Esc 한 번, /exit, 재개 줄, 이어서 작업하라는 고정 문장 순서로만 나가고 /compact는 보내지 않는다."""
        # Given
        result = self.asked(RUNNING_TURN)

        # When
        decided = self.interrupt()

        # Then
        self.assertEqual("dialog_open", result["questions"][0]["reason"])
        self.assertEqual([("keys", ESC), ("send", "/exit"), ("send", "resume"), ("send", refresh_interrupt.CONTINUE_PROMPT)], self.log)
        view = decided["sessions"][0]
        self.assertEqual(("done", "resumed_without_compaction", "sent"), (view["status"], view["note"], view["continue_prompt"]))

    def test_백그라운드_작업이_남았으면_종료_없이_reload와_compact_뒤_이어서_작업하라고_보낸다(self):
        """term_claude: 남은 백그라운드 작업이 있으면 Esc 한 번 뒤 종료하지 않고 /reload-plugins와 /compact를 보낸 다음 이어서 작업하라는 문장을 보낸다."""
        # Given
        result = self.asked(BACKGROUND_TURN)

        # When
        decided = self.interrupt()

        # Then
        self.assertIs(True, result["questions"][0]["background"])
        self.assertEqual([("keys", ESC), ("send", "/reload-plugins"), ("send", "/compact"), ("send", refresh_interrupt.CONTINUE_PROMPT)], self.log)
        self.assertEqual("done", decided["sessions"][0]["status"])

    def test_차례가_멈추지_않으면_Esc만_보내고_interrupt_unconfirmed로_실패한다(self):
        """term_claude: Esc 뒤 15초 안에 차례 기록이 바쁨을 벗어나지 않으면 두 번째 Esc나 다른 명령 없이 interrupt_unconfirmed로 실패한다."""
        # Given
        self.asked(RUNNING_TURN)
        self.stops_turn = False

        # When
        decided = self.interrupt()

        # Then
        self.assertEqual([("keys", ESC)], self.log)
        self.assertEqual(([], "failed", "interrupt_unconfirmed"), (self.fake.sent, decided["sessions"][0]["status"], decided["sessions"][0]["detail"]))
        self.assertFalse(decided["ok"])

    def test_답하기_전에_쉬게_된_세션은_Esc도_이어서_작업하라는_문장도_없이_보통으로_적용한다(self):
        """term_claude: 질문 뒤 차례가 끝난 세션에 interrupt를 답하면 Esc를 보내지 않고 보통 경로로 적용하며 이어서 작업하라는 문장을 보내지 않는다."""
        # Given
        self.asked(RUNNING_TURN, digest="d")
        with self.transcript.open("a") as stream:
            stream.write(json.dumps(turn_end()) + "\n")
        self.fake.screens[resume_base.HANDLE] = list(CLAUDE_EMPTY)

        # When
        decided = self.interrupt()

        # Then
        self.assertEqual([("send", "/reload-plugins")], self.log)
        self.assertEqual(("done", None), (decided["sessions"][0]["status"], decided["sessions"][0].get("continue_prompt")))


    def test_질문_뒤_터미널의_대화가_바뀌었으면_interrupt를_답해도_아무것도_보내지_않고_session_replaced로_실패한다(self):
        """term_claude: 질문을 한 뒤 같은 터미널에서 다른 대화(다른 기록 파일)가 시작됐으면 interrupt 답은 Esc도 종료도 재개도 보내지 않고 session_replaced로 실패한다."""
        # Given
        self.asked(RUNNING_TURN)
        other = "99999999-8888-7777-6666-555555555555"
        write_records(Path(self.temp.name) / f"{other}.jsonl", RUNNING_TURN)
        self.write_marker("startup", session=other)

        # When
        decided = self.interrupt()

        # Then
        self.assertEqual(([], []), (self.log, self.fake.sent))
        self.assertEqual(("failed", "session_replaced"), (decided["sessions"][0]["status"], decided["sessions"][0]["detail"]))
        self.assertFalse(decided["ok"])

    def test_종료와_재개_점검이_막으면_compact_없이_reload만_보내고_이어서_작업하라고_하며_점검_결과를_메모로_남긴다(self):
        """term_claude: 남은 백그라운드 작업이 없는데 실행 인자를 몰라 재개 점검이 건너뛰어지면 /compact 없이 /reload-plugins만 보낸 뒤 이어서 작업하라는 문장을 보내고 점검 결과를 note로 알린다."""
        # Given
        self.processes.table[self.pid]["argv"] = ["claude", "--brand-new-option", "value"]
        self.asked(RUNNING_TURN, digest="old")

        # When
        decided = self.interrupt()

        # Then
        self.assertEqual([("keys", ESC), ("send", "/reload-plugins"), ("send", refresh_interrupt.CONTINUE_PROMPT)], self.log)
        view = decided["sessions"][0]
        self.assertEqual(("done", "resume_check_skipped:launch_arguments_unknown", "sent"), (view["status"], view["note"], view["continue_prompt"]))

    def test_도우미에게_넘긴_interrupt_세션도_동작이_끝나면_도우미가_이어서_작업하라고_보낸다(self):
        """term_claude: interrupt 뒤 조율 메일 때문에 도우미에게 넘어간 세션은 compact_while_owing과 이어서 작업할 의무를 지켜, 도우미가 reload와 compact를 확인한 다음 이어서 작업하라는 문장을 보내고 done으로 끝낸다."""
        # Given
        self.asked(BACKGROUND_TURN)
        self.fake.mail.add(resume_base.HANDLE)

        # When
        with patch.object(refresh_interrupt, "APPLY_SECONDS", 0.3):
            deferred = self.interrupt()
        self.fake.mail.clear()
        with patch.object(refresh_follow, "install_current", return_value=True), patch.object(refresh, "Orca", return_value=self.fake), \
                patch.object(refresh, "FOLLOW_UP_SECONDS", 5):
            refresh.command_self_apply(self.run_id, sleep=lambda seconds: None)
        status = refresh.command_status(self.run_id)

        # Then
        self.assertEqual("deferred", deferred["sessions"][0]["status"])
        self.assertEqual([("keys", ESC), ("send", "/reload-plugins"), ("send", "/compact"), ("send", refresh_interrupt.CONTINUE_PROMPT)], self.log)
        self.assertEqual(("done", "sent"), (status["sessions"][0]["status"], status["sessions"][0]["continue_prompt"]))


if __name__ == "__main__":
    unittest.main()
