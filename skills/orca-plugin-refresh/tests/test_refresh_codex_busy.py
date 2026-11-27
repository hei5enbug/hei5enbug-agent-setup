from __future__ import annotations

import contextlib
import json
import os
import shlex
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import test_orca_plugin_refresh as base
import test_refresh_resume as resume_base
from test_orca_plugin_refresh import CODEX_EMPTY, FakeCli, FakeOrca, refresh, rollout_event, terminal, write_rollout

import refresh_codex_session
import refresh_core
import refresh_follow
import refresh_install
import refresh_interrupt
import refresh_resume

SESSION = "term_demo-a"
OTHER = "term_demo-b"
ESC = "\x1b"
OLD_VERSION, NEW_VERSION = "1.0.0", "1.1.0"
INSTALL_MARKER = ".codex-marketplace-install.json"


def setUpModule():
    base.setUpModule()


def tearDownModule():
    base.tearDownModule()


class LoggedCli(FakeCli):
    """The fake plugin commands, noting each Codex install command in the shared event list."""

    def __init__(self, events):
        super().__init__()
        self.events = events

    def __call__(self, argv, **kwargs):
        if list(argv)[:3] in (["codex", "plugin", "add"], ["codex", "plugin", "marketplace"]) and "list" not in argv:
            self.events.append(("install", " ".join(argv[:4])))
        return super().__call__(argv, **kwargs)

    def codex_installs(self):
        return [command for command in self.installs() if command[0] == "codex"]


class CodexCase(resume_base.ResumeCase):
    """Codex sessions in Orca terminals with a fake process table, rollout files, plugin trees, and a fake Codex CLI."""

    install = base.UpdateTest.install
    plugin_root = base.UpdateTest.plugin_root
    companion = base.UpdateTest.companion
    stage = base.UpdateTest.stage

    def setUp(self):
        super().setUp()
        self.base = Path(self.temp.name)
        env = patch.dict(os.environ, {"CODEX_HOME": str(self.base / "codex-home")})
        env.start()
        self.addCleanup(env.stop)
        for name in (*refresh.CODEX_TURN_ENV, refresh.COMPANION_ENV):
            os.environ.pop(name, None)
        for module, name, value in ((refresh_follow, "IDLE_CONFIRM_SECONDS", 0), (refresh_interrupt, "INTERRUPT_SECONDS", 0.05),
                                    (refresh_interrupt, "CONTINUE_SECONDS", 2.0)):
            patcher = patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        trust = patch.object(refresh, "trust_codex_hooks", return_value="automatic trust is off in these tests")
        trust.start()
        self.addCleanup(trust.stop)
        current = patch.object(refresh_follow, "install_current", return_value=True)
        current.start()
        self.addCleanup(current.stop)
        self.events: list[tuple] = []
        self.rollouts: dict[str, Path] = {}
        self.pids: dict[str, int] = {}
        self.processes.table.clear()
        self.processes.help_text = "  -m, --model <MODEL>\n      --no-alt-screen\n"
        self.system = replace(self.processes.system(), started_at=lambda pid: 100.0, which=lambda name: "/tmp/codex")
        for module in (refresh_codex_session, refresh_resume):
            patcher = patch.object(module, "ProcessOs", lambda: self.system)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.fake = FakeOrca([], on_send=self.on_send)
        self.fake.on_keys = self.on_keys
        self.fake.list = []
        self.state["hosts"]["codex"] = {"digest": "d", "root": self.temp.name, "installed_at": 200.0}
        refresh.save_json(refresh.run_path(self.run_id), {**self.state, "run_id": self.run_id})
        self.spawned: list[str] = []

    def add_session(self, handle, tail="task_complete"):
        """A running Codex session with its rollout, marker, process, and terminal; `tail` is the rollout's last event."""
        number = len(self.rollouts) + 1
        identity = f"{number:08d}-2222-3333-4444-555555555555"
        events = [{"type": "session_meta", "payload": {"id": identity, "cwd": "/tmp/work"}}, {"type": "turn_context", "payload": {}},
                  rollout_event("task_started"), *([rollout_event(tail)] if tail else [])]
        self.rollouts[handle] = write_rollout(self.base / "codex-home", f"demo-{number}-{handle}", events)
        self.write_codex_marker(handle, "startup")
        self.pids[handle] = self.processes.add(handle, ["codex", "-m", "demo-model", "--no-alt-screen"], "/tmp/codex", None,
                                               comm="codex", extra_env={"CODEX_HOME": "/tmp/profile"})
        self.fake.list.append(terminal(handle, "codex"))
        self.fake.screens[handle] = list(CODEX_EMPTY)

    def write_codex_marker(self, handle, source, written_at=None):
        target = refresh.load_run(self.run_id)["hosts"]["codex"]
        root = target.get("root") or self.temp.name
        digest = target.get("digest") or "d"
        if source == "startup":
            root, digest = self.temp.name, "d"
        directory = refresh.SESSION_CONTEXT.marker_directory()
        directory.mkdir(parents=True, exist_ok=True)
        payload = {"schema": 1, "host": "codex", "root": root, "digest": digest, "source": source,
                   "transcript_path": str(self.rollouts[handle]), "written_at": written_at or refresh.now()}
        (directory / f"{handle}.json").write_text(json.dumps(payload))

    def append(self, handle, kind):
        with self.rollouts[handle].open("a") as stream:
            stream.write(json.dumps(rollout_event(kind)) + "\n")

    def on_send(self, fake, handle, text):
        self.events.append(("send", "resume" if " resume " in text else text, handle))
        if text == "/exit":
            self.processes.table.pop(self.pids[handle], None)
            fake.screens[handle] = list(resume_base.SHELL_AFTER_EXIT)
        elif " resume " in text:
            self.pids[handle] = self.processes.add(handle, ["codex", *shlex.split(text)[2:]], "/tmp/codex", None, comm="codex",
                                                   extra_env={"CODEX_HOME": "/tmp/profile"})
            fake.screens[handle] = list(CODEX_EMPTY)
            self.write_codex_marker(handle, "resume", resume_base.LATER())

    def on_keys(self, fake, handle, text):
        self.events.append(("keys", text, handle))
        if text == ESC:
            fake.typed[handle] = ""
            if self.aborts:
                self.append(handle, "turn_aborted")

    aborts = True

    def orca(self):
        return patch.object(refresh, "Orca", return_value=self.fake)

    def apply(self, seconds=0.3):
        with self.orca():
            return refresh.command_apply(self.run_id, "auto", [], seconds, spawn=lambda run: self.spawned.append(run) or 4242,
                                         system=self.system, sleep=lambda seconds: None)

    def helper(self):
        with self.orca():
            refresh.command_self_apply(self.run_id, sleep=lambda seconds: time.sleep(0.02), system=self.system)
        return refresh.command_status(self.run_id)

    def after(self, seconds, action):
        timer = threading.Timer(seconds, action)
        timer.start()
        self.addCleanup(timer.cancel)

    def sent(self, handle=None):
        return [event[1] for event in self.events if event[0] == "send" and handle in (None, event[2])]

    def view(self, result, handle=SESSION):
        return next(item for item in result["sessions"] if item["terminal"] == f"…{handle[-6:]}")


class ReplacedFolderResumeTest(CodexCase):
    def setUp(self):
        super().setUp()
        self.add_session(SESSION)

    def test_교체된_폴더의_유휴_Codex_세션은_묻지_않고_exit와_재개_줄을_보내_done으로_끝낸다(self):
        """term_demo-a: 로드한 플러그인 폴더가 교체됐고 유휴이며 입력줄이 비어 있으면 apply가 /exit와 재개 줄을 보내고 done, resumed로 보고하며 resume_approval_needed는 없다."""
        # Given
        # When
        result = self.apply()

        # Then
        view = self.view(result)
        self.assertEqual(["/exit", "resume"], self.sent())
        self.assertEqual(("done", ["resumed"]), (view["status"], view["completed"]))
        self.assertNotIn("resume_approval_needed", view)
        self.assertTrue(result["ok"])

    def test_입력줄에_보내지_않은_글이_있으면_아무것도_보내지_않고_예전처럼_승인을_묻는다(self):
        """term_demo-a: 입력줄에 쓰던 글이 있으면 apply는 아무것도 보내지 않고 skipped, unsent_input의 resume_check와 resume_approval_needed로 보고한다."""
        # Given
        self.fake.screens[SESSION] = CODEX_EMPTY[:2] + ["› 쓰다 만 요청"] + CODEX_EMPTY[3:]

        # When
        result = self.apply()

        # Then
        view = self.view(result)
        self.assertEqual([], self.sent())
        self.assertEqual(("skipped", "unsent_input", True), (view["status"], view["resume_check"], view["resume_approval_needed"]))

    def test_차례가_진행_중이면_resume을_남기고_넘겨_도우미가_차례_종료_기록_뒤에_재개한다(self):
        """term_demo-a: 바쁜 세션은 deferred와 남은 동작 resume으로 도우미에 넘기고, 도우미는 롤아웃이 차례 끝을 기록한 뒤에만 exit와 재개 줄을 보낸다."""
        # Given
        self.append(SESSION, "agent_message")
        result = self.apply()
        deferred = self.view(result)
        ended = []

        def end_turn():
            self.append(SESSION, "task_complete")
            ended.append(len(self.events))

        # When
        self.after(0.3, end_turn)
        status = self.helper()

        # Then
        self.assertEqual(("deferred", ["resume"]), (deferred["status"], deferred["actions"]))
        self.assertEqual([], [event for event in self.events[:ended[0]] if event[0] == "send"])
        self.assertEqual(["/exit", "resume"], self.sent())
        final = self.view(status)
        self.assertEqual(("done", ["resumed"]), (final["status"], final["completed"]))
        self.assertNotIn("resume_approval_needed", final)


class InstallCase(CodexCase):
    """A run made by `update` while Codex sessions had a turn in progress, with a fake Codex CLI ready to install."""

    def setUp(self):
        super().setUp()
        self.cli = LoggedCli(self.events)
        self.stage(self.cli)
        (self.plugin_root("codex", refresh.PLUGIN, refresh.MARKETPLACE, NEW_VERSION) / INSTALL_MARKER).write_text("{}")

    @contextlib.contextmanager
    def commands(self):
        with (patch.object(refresh_core, "run", side_effect=self.cli), patch.object(refresh_core, "executable", side_effect=lambda name: name),
              patch.object(refresh, "claude_unreleased_changes", return_value=([], None))):
            yield

    def update(self):
        with self.commands():
            result = refresh.command_update([])
        self.run_id = result["run_id"]
        return result

    def question(self, update, handle):
        return next(item for item in update["questions"] if item["terminal"] == f"…{handle[-6:]}")

    def decide(self, *answers):
        with self.orca(), self.commands():
            return refresh.command_decide(self.run_id, list(answers), spawn=lambda run: self.spawned.append(run) or 4242, system=self.system,
                                          sleep=lambda seconds: time.sleep(0.02))

    def helper(self):
        with self.commands():
            return super().helper()

    def installed_codex(self):
        return [event for event in self.events if event[0] == "install"]


class InstallQuestionTest(InstallCase):
    def test_Orca_표식과_맞는_진행_중_롤아웃은_wait_interrupt_skip_질문_하나를_내고_Claude는_설치한다(self):
        """term_demo-a: 표식이 가리키는 진행 중 롤아웃이 있으면 update는 그 세션을 이름으로 한 질문 하나를 세 선택지와 함께 내고 Codex 설치 명령은 없으며 Claude Code는 설치한다."""
        # Given
        self.add_session(SESSION, tail=None)

        # When
        update = self.update()

        # Then
        self.assertEqual(1, len(update["questions"]))
        question = update["questions"][0]
        self.assertEqual((f"…{SESSION[-6:]}", "codex_install", "codex", ["wait", "interrupt", "skip"]),
                         (question["terminal"], question["reason"], question["host"], [item["choice"] for item in question["options"]]))
        self.assertEqual("codex_turn_in_progress", update["hosts"]["codex"]["error"]["code"])
        self.assertIn("recovery_command", update["hosts"]["codex"])
        self.assertEqual([], self.cli.codex_installs())
        self.assertIn(["claude", "plugin", "update", refresh.PLUGIN_ID], self.cli.installs())

    def test_Orca_표식이_없는_롤아웃은_outside_orca이고_wait와_skip만_묻는다(self):
        """진행 중 롤아웃에 맞는 표식이 없으면 질문은 outside_orca이며 선택지는 wait와 skip뿐이다."""
        # Given
        write_rollout(self.base / "codex-home", "outside", [{"type": "session_meta", "payload": {"cwd": "/tmp/work"}}, rollout_event("task_started")])

        # When
        update = self.update()

        # Then
        question = update["questions"][0]
        self.assertEqual((True, None, "/tmp/work", ["wait", "skip"]),
                         (question["outside_orca"], question["terminal"], question["worktree"], [item["choice"] for item in question["options"]]))

    def test_이_세션이_Codex_차례_안이면_이_세션_질문은_wait와_skip만_묻고_다른_세션은_따로_묻는다(self):
        """Codex 차례 안에서 실행하면 롤아웃이 이름 붙은 질문으로 보고되고, 이 세션 질문은 wait와 skip뿐이며 다른 진행 중 세션은 세 선택지로 따로 묻는다."""
        # Given
        self.add_session(OTHER, tail=None)
        own = write_rollout(self.base / "codex-home", "2026-thread-demo", [{"type": "session_meta", "payload": {"cwd": "/tmp/work"}}, rollout_event("task_started")])
        directory = refresh.SESSION_CONTEXT.marker_directory()
        (directory / f"{SESSION}.json").write_text(json.dumps({"schema": 1, "host": "codex", "transcript_path": str(own)}))

        # When
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "thread-demo", "ORCA_TERMINAL_HANDLE": SESSION}):
            update = self.update()

        # Then
        self.assertEqual("update_deferred_active_session", update["hosts"]["codex"]["error"]["code"])
        self.assertEqual(2, len(update["questions"]))
        mine, other = self.question(update, SESSION), self.question(update, OTHER)
        self.assertEqual((True, ["wait", "skip"]), (mine["own_session"], [item["choice"] for item in mine["options"]]))
        self.assertEqual(["wait", "interrupt", "skip"], [item["choice"] for item in other["options"]])

    def test_실행_도중_게이트가_진행_중으로_바뀌면_다시_실행하라는_안내_대신_질문을_낸다(self):
        """term_demo-a: 마켓플레이스 갱신 뒤 차례가 시작돼 게이트가 막히면 이후 Codex 설치는 하지 않고 recovery_command는 남기며 그 세션의 질문을 낸다."""
        # Given
        self.add_session(SESSION)
        real = refresh_install.install_gate
        market = ["codex", "plugin", "marketplace", "upgrade", refresh.MARKETPLACE]

        def gate(host, **kwargs):
            if host == "codex" and market in self.cli.commands:
                self.append(SESSION, "agent_message")
            return real(host, **kwargs)

        # When
        with patch.object(refresh_install, "install_gate", side_effect=gate):
            update = self.update()

        # Then
        self.assertEqual("codex_turn_in_progress", update["hosts"]["codex"]["error"]["code"])
        self.assertIn("recovery_command", update["hosts"]["codex"])
        self.assertEqual([f"…{SESSION[-6:]}"], [item["terminal"] for item in update["questions"]])
        self.assertEqual([], [command for command in self.cli.codex_installs() if command[:3] == ["codex", "plugin", "add"]])

    def test_게이트는_진행_중인_롤아웃을_모두_이름으로_알리고_호출_환경_변수만_무시할_수_있다(self):
        """진행 중 롤아웃이 둘이면 details에 둘 다 담고, ignore_env는 Codex 차례 환경 변수만 무시하며 롤아웃 검사는 그대로 한다."""
        # Given
        paths = {str(write_rollout(self.base / "codex-home", name, [rollout_event("task_started")])) for name in ("one", "two")}
        write_rollout(self.base / "codex-home", "done", [rollout_event("task_complete")])

        # When
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "thread-demo"}):
            active = refresh.install_gate("codex")
            ignored = refresh.install_gate("codex", ignore_env=True)

        # Then
        self.assertEqual(("update_deferred_active_session", paths), (active.code, set(active.details["rollouts"])))
        self.assertEqual(("codex_turn_in_progress", paths), (ignored.code, set(ignored.details["rollouts"])))


class DecideTest(InstallCase):
    def asked(self, *handles):
        for handle in handles:
            self.add_session(handle, tail=None)
        return self.update()

    def test_wait를_답하면_롤아웃이_바쁜_동안_설치하지_않고_차례_종료_뒤_설치하고_재개한다(self):
        """term_demo-a: wait 답은 키 입력 없이 도우미에 맡기고, 도우미는 롤아웃이 바쁜 동안 Codex 설치 명령을 내지 않다가 차례 종료 기록 뒤 설치하고 호스트 오류 없이 그 세션을 재개한다."""
        # Given
        update = self.asked(SESSION)
        installed_while_busy = []

        def end_turn():
            installed_while_busy.append(len(self.installed_codex()))
            self.append(SESSION, "task_complete")

        # When
        decided = self.decide(f"{update['questions'][0]['id']}=wait")
        before_helper = list(self.events)
        self.after(0.3, end_turn)
        status = self.helper()

        # Then
        self.assertEqual(("pending", []), (decided["codex_install"]["status"], before_helper))
        self.assertEqual([self.run_id], self.spawned)
        self.assertEqual([0], installed_while_busy)
        self.assertIn(["codex", "plugin", "add", refresh.PLUGIN_ID], self.cli.codex_installs())
        self.assertNotIn("error", status["hosts"]["codex"])
        self.assertEqual("done", status["codex_install"]["status"])
        self.assertEqual(["/exit", "resume"], self.sent())
        resumed = self.view(status)
        self.assertEqual(("done", ["resumed"]), (resumed["status"], resumed["completed"]))
        self.assertTrue(status["script"])

    def test_interrupt를_답하면_Esc_차례_중단_기록_설치_재개_이어서_작업하라는_문장_순서로_진행한다(self):
        """term_demo-a: interrupt 답은 Esc 한 번, 기록된 차례 중단, Codex 설치, exit와 재개, 이어서 작업하라는 고정 문장을 이 순서로 보내고 decide가 끝나기 전에 마친다."""
        # Given
        update = self.asked(SESSION)

        # When
        decided = self.decide(f"{update['questions'][0]['id']}=interrupt")

        # Then
        names = [event[1] if event[0] != "install" else "install" for event in self.events]
        self.assertEqual([ESC, "install", "install", "/exit", "resume", refresh_interrupt.CONTINUE_PROMPT], names)
        self.assertEqual("done", decided["codex_install"]["status"])
        self.assertTrue(decided["script"])
        self.assertEqual([], self.spawned)
        status = refresh.command_status(self.run_id)
        resumed = self.view(status)
        self.assertEqual(("done", "sent"), (resumed["status"], resumed["continue_prompt"]))
        self.assertNotIn("error", status["hosts"]["codex"])

    def test_차례_중단이_기록되지_않으면_그_세션에_더_보내지_않고_기다림으로_바꿔_도우미에_맡긴다(self):
        """term_demo-a: Esc 뒤 15초 안에 차례 중단 기록이 없으면 다른 키나 명령 없이 설치하지 않고, 그 세션을 wait처럼 보고 도우미에 맡긴다."""
        # Given
        self.aborts = False
        update = self.asked(SESSION)

        # When
        decided = self.decide(f"{update['questions'][0]['id']}=interrupt")

        # Then
        self.assertEqual([("keys", ESC, SESSION)], self.events)
        self.assertEqual("pending", decided["codex_install"]["status"])
        self.assertEqual([{"terminal": f"…{SESSION[-6:]}", "state": "unconfirmed"}], decided["codex_install"]["interrupts"])
        self.assertEqual([self.run_id], self.spawned)
        self.assertEqual([], self.installed_codex())

    def test_skip을_답하면_Codex_설치_명령도_세션_입력도_없고_이번_실행은_건너뛴다고_알린다(self):
        """term_demo-a: skip 답은 Codex 설치 명령이나 어떤 세션 입력도 만들지 않고, 호스트 결과의 decision과 codex_install 상태로 건너뜀을 알린다."""
        # Given
        update = self.asked(SESSION)

        # When
        decided = self.decide(f"{update['questions'][0]['id']}=skip")

        # Then
        self.assertEqual(([], []), (self.events, self.spawned))
        self.assertEqual("skipped_by_user", decided["codex_install"]["status"])
        self.assertEqual("skip", refresh.command_status(self.run_id)["hosts"]["codex"]["decision"])
        self.assertTrue(decided["ok"])

    def test_interrupt와_wait가_함께_있으면_기다리는_세션의_차례가_끝나기_전에는_Esc를_보내지_않는다(self):
        """term_demo-a와 term_demo-b: 한 세션에 interrupt, 다른 세션에 wait를 답하면 기다리는 세션이 차례를 끝내기 전에는 Esc가 나가지 않고 그 뒤에 Esc, 설치, 재개 순서로 진행한다."""
        # Given
        update = self.asked(SESSION, OTHER)

        def end_other_turn():
            self.events.append(("ended", OTHER))
            self.append(OTHER, "task_complete")

        # When
        self.decide(f"{self.question(update, SESSION)['id']}=interrupt", f"{self.question(update, OTHER)['id']}=wait")
        self.after(0.3, end_other_turn)
        status = self.helper()

        # Then
        kinds = [event[0] for event in self.events]
        self.assertEqual(1, kinds.count("keys"))
        self.assertLess(self.events.index(("ended", OTHER)), kinds.index("keys"))
        self.assertLess(kinds.index("keys"), kinds.index("install"))
        self.assertEqual("done", status["codex_install"]["status"])
        self.assertEqual({SESSION, OTHER}, {event[2] for event in self.events if event[:2] == ("send", "resume")})

    def test_한_시간_한도까지_wait_세션이_바쁘면_설치하지_않고_이유를_보고한다(self):
        """term_demo-a: 도우미의 한도가 지날 때까지 wait 세션의 차례가 끝나지 않으면 Codex 설치 명령도 세션 입력도 없이 not_idle_before_deadline로 끝낸다."""
        # Given
        update = self.asked(SESSION)

        # When
        with patch.object(refresh, "FOLLOW_UP_SECONDS", 0.3):
            self.decide(f"{update['questions'][0]['id']}=wait")
        status = self.helper()

        # Then
        self.assertEqual("not_idle_before_deadline", status["codex_install"]["status"])
        self.assertEqual([], self.events)
        self.assertIn("error", status["hosts"]["codex"])

    def test_이_세션이_wait를_답하면_차례가_끝난_뒤_설치하고_이_세션도_교체된_폴더_세션으로_재개한다(self):
        """term_demo-a가 스킬을 실행하는 세션일 때: Codex 차례 안에서 wait를 답하면 도우미가 호출 환경 변수를 무시하고 차례 종료 뒤 설치하고 이 세션도 재개한다."""
        # Given
        self.add_session(SESSION, tail=None)
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "thread-demo", "ORCA_TERMINAL_HANDLE": SESSION}):
            update = self.update()
            mine = update["questions"][0]
            decided = self.decide(f"{mine['id']}=wait")
            self.after(0.3, lambda: self.append(SESSION, "task_complete"))

            # When
            status = self.helper()

        # Then
        self.assertEqual("update_deferred_active_session", update["hosts"]["codex"]["error"]["code"])
        self.assertEqual("pending", decided["codex_install"]["status"])
        self.assertEqual("done", status["codex_install"]["status"])
        self.assertEqual(["/exit", "resume"], self.sent())
        self.assertEqual("done", self.view(status)["status"])

    def test_제공하지_않은_선택지와_일부만_답한_Codex_질문은_아무것도_하지_않고_거부한다(self):
        """세션 밖 롤아웃 질문에 interrupt를 답하거나 Codex 질문 일부만 답하면 answer_invalid나 answers_incomplete로 거부하고 상태를 바꾸지 않는다."""
        # Given
        self.add_session(SESSION, tail=None)
        write_rollout(self.base / "codex-home", "outside", [{"type": "session_meta", "payload": {"cwd": "/tmp/work"}}, rollout_event("task_started")])
        update = self.update()
        outside = next(item for item in update["questions"] if item.get("outside_orca"))
        named = self.question(update, SESSION)

        # When
        with self.assertRaises(refresh.RefreshError) as invalid:
            self.decide(f"{outside['id']}=interrupt", f"{named['id']}=wait")
        with self.assertRaises(refresh.RefreshError) as incomplete:
            self.decide(f"{named['id']}=wait")

        # Then
        self.assertEqual(("answer_invalid", "answers_incomplete"), (invalid.exception.code, incomplete.exception.code))
        self.assertEqual(2, refresh.command_status(self.run_id)["unanswered"])
        self.assertEqual(([], []), (self.events, self.spawned))

    def test_저장된_스크립트_경로가_있으면_결과_알림_명령이_그_경로를_쓴다(self):
        """Codex 설치가 옛 설치본을 지운 뒤에는 상태 명령이 저장된 새 스크립트 경로를 가리킨다."""
        # When
        command = refresh.status_command("a" * 32, "/home/test/new/orca_plugin_refresh.py")

        # Then
        self.assertIn("python3 /home/test/new/orca_plugin_refresh.py status --run-id " + "a" * 32, command)


if __name__ == "__main__":
    unittest.main()
