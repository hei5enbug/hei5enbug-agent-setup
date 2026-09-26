from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

ROOT_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(ROOT_SCRIPTS))
import orca_plugin_refresh as refresh
import session_lifecycle as lifecycle
from orca_refresh_fixture import OrcaRefreshFixture
from session_lifecycle import registry_lock

REAL_TERMINAL_HAS_DRAFT = refresh.terminal_has_draft
ACCEPTED_SEND = {"result": {"send": {"accepted": True, "prompt": {"stages": ["input_accepted", "turn_started"]}}}}


def orca_result(payload: dict[str, object], returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["orca"], returncode, stdout=json.dumps(payload), stderr="")


def shown_terminal(identity: str | None, *, connected: bool = True, exit_cause: str | None = None) -> subprocess.CompletedProcess[str]:
    terminal: dict[str, object] = {"handle": "term-x", "agentIdentity": identity, "connected": connected}
    if exit_cause:
        terminal["exitCause"] = {"kind": exit_cause}
    return orca_result({"ok": True, "result": {"terminal": terminal}})


class OrcaTerminalProbeTest(OrcaRefreshFixture):
    def setUp(self):
        super().setUp()
        orca = patch.object(refresh, "orca_command", return_value=["orca"])
        orca.start()
        self.addCleanup(orca.stop)

    def test_셸만_남고_agent가_사라지면_agent가_끝난_것으로_본다(self):
        """agent가 끝나고 셸만 남은 터미널은 살아 있어도 agent 종료로 확인한다."""
        # Given
        response = shown_terminal(None)

        # When
        with patch.object(refresh, "run_command", return_value=response):
            running = refresh.terminal_agent_running("term-x", "claude")

        # Then
        self.assertFalse(running)

    def test_같은_agent가_남아_있으면_아직_실행_중으로_본다(self):
        """터미널의 agent가 계획한 host와 같으면 아직 종료되지 않았다."""
        # Given
        response = shown_terminal("claude")

        # When
        with patch.object(refresh, "run_command", return_value=response):
            running = refresh.terminal_agent_running("term-x", "claude")

        # Then
        self.assertTrue(running)

    def test_터미널이_끝났거나_Orca에서_사라졌으면_agent가_끝난_것으로_본다(self):
        """셸까지 끝났거나 handle이 사라진 터미널에는 실행 중인 agent가 없다."""
        # Given
        exited = shown_terminal("codex", connected=False, exit_cause="process_exit")
        stale = orca_result({"ok": False, "error": {"code": "terminal_handle_stale"}}, returncode=1)

        # When
        with patch.object(refresh, "run_command", side_effect=[exited, stale]):
            observed = [refresh.terminal_agent_running("term-x", "codex") for _ in range(2)]

        # Then
        self.assertEqual(observed, [False, False])

    def test_Orca가_다른_이유로_거부하면_agent_종료로_추측하지_않는다(self):
        """handle이 사라졌다는 응답이 아니면 agent 상태를 알 수 없다고 보고 중단한다."""
        # Given
        rejected = orca_result({"ok": False, "error": {"code": "runtime_unavailable"}}, returncode=1)

        # When
        with patch.object(refresh, "run_command", return_value=rejected):
            with self.assertRaises(refresh.RefreshError) as caught:
                refresh.terminal_agent_running("term-x", "codex")

        # Then
        self.assertEqual(caught.exception.code, "orca_rejected")

    def test_Orca_응답의_입력_초안을_해석한다(self):
        """보내지 않은 입력이 있으면 참, 비어 있으면 거짓, 정보가 없으면 알 수 없음으로 본다."""
        # Given
        responses = [
            {"result": {"terminal": {"draft": "1번으로 가"}}},
            {"result": {"terminal": {"draft": None}}},
            {"result": {"terminal": {"draft": {"unexpected": "input"}}}},
            {"result": {"terminal": {"tail": []}}},
        ]

        # When
        with patch.object(refresh, "run_json", side_effect=responses):
            observed = [REAL_TERMINAL_HAS_DRAFT("term-x") for _ in responses]

        # Then
        self.assertEqual(observed, [True, False, None, None])


class AgentStopTest(OrcaRefreshFixture):
    def test_셸에서_실행한_agent는_셸이_남아도_종료를_확인한다(self):
        """셸이 끝나기를 기다리지 않고 terminal의 agent가 사라지면 종료 대기를 마친다."""
        # Given
        states = iter([True, True, False])
        polls: list[str] = []

        def agent_running(handle, host):
            polls.append(handle)
            return next(states)

        # When
        with (
            patch.object(refresh, "run_json", return_value=ACCEPTED_SEND),
            patch.object(refresh, "terminal_agent_running", side_effect=agent_running),
            patch.object(refresh, "POLL_INTERVAL_SECONDS", 0),
        ):
            refresh._send_exit("term-other", "claude")

        # Then
        self.assertEqual(polls, ["term-other"] * 3)

    def test_agent가_끝나지_않으면_종료를_확인하지_못했다고_중단한다(self):
        """agent가 제한 시간 안에 사라지지 않으면 터미널을 닫지 않고 멈춘다."""
        # Given
        timeout = patch.object(refresh, "AGENT_EXIT_TIMEOUT_SECONDS", 0)

        # When
        with (
            timeout,
            patch.object(refresh, "run_json", return_value=ACCEPTED_SEND),
            patch.object(refresh, "terminal_agent_running", return_value=True),
            patch.object(refresh, "POLL_INTERVAL_SECONDS", 0),
        ):
            with self.assertRaises(refresh.RefreshError) as caught:
                refresh._send_exit("term-other", "claude")

        # Then
        self.assertEqual(caught.exception.code, "exit_unconfirmed")


class CodexThreadLockTest(OrcaRefreshFixture):
    def setUp(self):
        super().setUp()
        self.codex_home = self.root / "codex-home"
        (self.codex_home / "thread-writer-locks").mkdir(parents=True)
        env = patch.dict(os.environ, {"CODEX_HOME": str(self.codex_home)})
        env.start()
        self.addCleanup(env.stop)

    def lock_path(self, session_id):
        return self.codex_home / "thread-writer-locks" / f"{session_id}.lock"

    def test_잠금_파일이_없으면_대화가_닫힌_것으로_본다(self):
        """Codex가 대화를 내리면서 잠금 파일을 지운 상태는 닫힌 대화다."""
        # Given
        session_id = "thread-closed"

        # When
        state = refresh.codex_thread_lock_state(session_id)

        # Then
        self.assertEqual(state, "free")

    def test_다른_프로세스가_flock을_쥐고_있으면_대화가_열린_것으로_본다(self):
        """Codex 프로세스가 대화 잠금을 쥐고 있으면 그 대화는 아직 열려 있다."""
        # Given
        path = self.lock_path("thread-open")
        path.touch()
        holder = os.open(path, os.O_RDONLY)
        self.addCleanup(os.close, holder)
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)

        # When
        state = refresh.codex_thread_lock_state("thread-open")

        # Then
        self.assertEqual(state, "held")

    def test_잠금_파일만_남고_flock이_없으면_대화가_닫힌_것으로_본다(self):
        """잠금 파일이 남아 있어도 아무도 flock을 쥐지 않았으면 닫힌 대화다."""
        # Given
        self.lock_path("thread-stale").touch()

        # When
        state = refresh.codex_thread_lock_state("thread-stale")

        # Then
        self.assertEqual(state, "free")

    def test_CODEX_HOME이_상대_경로면_추측하지_않고_중단한다(self):
        """Codex 데이터 위치를 확정할 수 없으면 다른 위치의 잠금을 확인하지 않는다."""
        # Given
        relative = patch.dict(os.environ, {"CODEX_HOME": "relative-codex-home"})

        # When
        with relative:
            with self.assertRaises(refresh.RefreshError) as caught:
                refresh.codex_thread_lock_state("thread-open")

        # Then
        self.assertEqual(caught.exception.code, "codex_home_invalid")

    def test_데몬이_대화를_늦게_닫으면_닫힐_때까지_기다린다(self):
        """exit 뒤에도 Codex 데몬이 대화를 잡고 있으면 잠금이 풀릴 때까지 resume을 미룬다."""
        # Given
        states = iter(["held", "held", "free"])
        observed: list[str] = []

        def lock_state(session_id):
            observed.append(session_id)
            return next(states)

        # When
        with patch.object(refresh, "codex_thread_lock_state", side_effect=lock_state), patch.object(refresh, "POLL_INTERVAL_SECONDS", 0):
            refresh._wait_codex_thread_released("thread-open")

        # Then
        self.assertEqual(observed, ["thread-open"] * 3)

    def test_대화가_계속_열려_있으면_수동_재개가_필요하다고_중단한다(self):
        """제한 시간이 지나도 대화 잠금이 풀리지 않으면 새 Codex를 띄우지 않는다."""
        # Given
        timeout = patch.object(refresh, "CODEX_THREAD_RELEASE_TIMEOUT_SECONDS", 0)

        # When
        with timeout, patch.object(refresh, "codex_thread_lock_state", return_value="held"), patch.object(refresh, "POLL_INTERVAL_SECONDS", 0):
            with self.assertRaises(refresh.RefreshError) as caught:
                refresh._wait_codex_thread_released("thread-open")

        # Then
        self.assertEqual(caught.exception.code, "codex_thread_still_open")


class CodexSessionEndTest(OrcaRefreshFixture):
    def session(self):
        return {"host": "codex", "session_id": "session-leaf-init", "worktree_id": "repo-init::/tmp/init"}

    def test_잠금이_풀린_뒤_늦게_오는_SessionEnd_기록을_기다린다(self):
        """이전 대화의 SessionEnd가 새 registry 기록을 덮어쓰지 않도록 종료 기록을 먼저 기다린다."""
        # Given
        polls = {"count": 0}
        real_read = refresh._read_current_records

        def delayed_end(app_root):
            polls["count"] += 1
            if polls["count"] == 3:
                with registry_lock(self.app_root) as registry:
                    registry["sessions"]["codex:session-leaf-init"]["state"] = "ended"
            return real_read(app_root)

        # When
        with patch.object(refresh, "_read_current_records", side_effect=delayed_end), patch.object(refresh, "POLL_INTERVAL_SECONDS", 0):
            refresh._wait_codex_session_end(self.app_root, self.session())

        # Then
        self.assertEqual(polls["count"], 3)

    def test_SessionEnd가_끝내_기록되지_않아도_재개를_막지_않는다(self):
        """훅이 실행되지 않는 환경에서는 짧게 기다린 뒤 재개를 계속한다."""
        # Given
        grace = patch.object(refresh, "CODEX_SESSION_END_GRACE_SECONDS", 0)

        # When
        with grace, patch.object(refresh, "POLL_INTERVAL_SECONDS", 0):
            refresh._wait_codex_session_end(self.app_root, self.session())

        # Then
        record = refresh.registry_sessions(self.app_root)["codex:session-leaf-init"]
        self.assertEqual(record["state"], "idle")


class CodexResumeSettingsTest(OrcaRefreshFixture):
    def setUp(self):
        super().setUp()
        self.codex_home = self.root / "codex-home"
        env = patch.dict(os.environ, {"CODEX_HOME": str(self.codex_home)})
        env.start()
        self.addCleanup(env.stop)

    def write_rollout(self, session_id, entries):
        directory = self.codex_home / "sessions" / "2026" / "09" / "27"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"rollout-2026-09-27T00-06-26-{session_id}.jsonl"
        path.write_text("".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8")

    def test_가장_마지막에_적용된_모델과_추론_강도로_재개한다(self):
        """턴 없이 바꾼 모델 설정까지 포함해 대화 기록의 마지막 설정을 고른다."""
        # Given
        self.write_rollout("thread-a", [
            {"type": "session_meta", "payload": {"cwd": "/tmp/init"}},
            {"type": "turn_context", "payload": {"model": "gpt-6-sol", "effort": "high"}},
            {"type": "event_msg", "payload": {
                "type": "thread_settings_applied",
                "thread_settings": {"model": "gpt-6-astra", "reasoning_effort": "xhigh"},
            }},
        ])

        # When
        settings = refresh.codex_resume_settings("thread-a")

        # Then
        self.assertEqual(settings, {"resume_model": "gpt-6-astra", "resume_effort": "xhigh"})

    def test_대화_기록이_없으면_모델을_지정하지_않는다(self):
        """기록을 찾을 수 없으면 추측하지 않고 Codex 기본 설정으로 재개한다."""
        # Given
        session_id = "thread-missing"

        # When
        settings = refresh.codex_resume_settings(session_id)

        # Then
        self.assertEqual(settings, {})

    def test_명령에_쓸_수_없는_모델_값은_무시한다(self):
        """모델 이름 형식이 아닌 값은 resume 명령에 넣지 않는다."""
        # Given
        self.write_rollout("thread-b", [
            {"type": "turn_context", "payload": {"model": "gpt 6; touch /tmp/x", "effort": "high"}},
        ])

        # When
        settings = refresh.codex_resume_settings("thread-b")

        # Then
        self.assertEqual(settings, {})

    def test_재개_명령에_기록된_모델과_추론_강도를_넘긴다(self):
        """Codex resume 명령은 세션이 쓰던 모델과 추론 강도를 유지한다."""
        # Given
        session = {
            "host": "codex", "cwd": "/tmp/init", "session_id": "thread-a",
            "resume_model": "gpt-6-sol", "resume_effort": "high",
        }
        executable = patch.object(refresh, "executable", side_effect=lambda name: f"/bin/{name}")

        # When
        with executable:
            command = refresh._resume_command(session)

        # Then
        self.assertEqual(command, [
            "/bin/codex", "-C", "/tmp/init", "resume", "thread-a",
            "-m", "gpt-6-sol", "-c", 'model_reasoning_effort="high"',
        ])


class CodexResumeVerificationTest(OrcaRefreshFixture):
    def prepare_ended_codex(self, transaction_id):
        with registry_lock(self.app_root) as registry:
            record = registry["sessions"]["codex:session-leaf-init"]
            record["state"] = "ended"
            record["last_event"] = "SessionEnd"
            record["refresh_transaction_id"] = transaction_id
        session = {"host": "codex", "session_id": "session-leaf-init", "worktree_id": "repo-init::/tmp/init"}
        new_terminal = self.terminal("codex", "term-new-codex", "repo-init::/tmp/init", "/tmp/init", "tab-new", "leaf-new")
        return session, new_terminal

    def test_새_Codex가_같은_대화_잠금을_쥐면_재개를_확인하고_registry를_새_터미널로_옮긴다(self):
        """SessionStart가 다음 턴까지 미뤄져도 새 프로세스가 같은 대화를 열면 재개로 확인한다."""
        # Given
        transaction_id = "e" * 32
        session, new_terminal = self.prepare_ended_codex(transaction_id)

        # When
        with (
            patch.object(refresh, "terminal_agent_running", return_value=True),
            patch.object(refresh, "codex_thread_lock_state", return_value="held"),
        ):
            refresh._wait_codex_resume(self.app_root, session, new_terminal, "0.6.0", transaction_id)

        # Then
        records = refresh.registry_sessions(self.app_root)
        record = records["codex:session-leaf-init"]
        self.assertEqual(record["terminal_handle"], "term-new-codex")
        self.assertEqual(record["incarnation_id"], "incarnation-term-new-codex")
        self.assertEqual((record["tab_id"], record["leaf_id"]), ("tab-new", "leaf-new"))
        self.assertEqual((record["state"], record["last_event"]), ("idle", "RefreshResume"))
        self.assertEqual(record["plugin_version"], "0.6.0")
        self.assertEqual(session["plugin_registration"], "pending_next_turn")
        self.assertEqual(session["new_plugin_version"], "0.6.0")
        self.assertIsNone(refresh.session_record_for_terminal(new_terminal, records)[2])

    def test_새_Codex가_대화를_열지_못하면_재개를_확인하지_않는다(self):
        """대화 잠금을 쥔 프로세스가 없으면 registry를 옮기지 않고 실패로 남긴다."""
        # Given
        transaction_id = "e" * 32
        session, new_terminal = self.prepare_ended_codex(transaction_id)
        timeout = patch.object(refresh, "RESUME_LOCK_TIMEOUT_SECONDS", 0)

        # When
        with (
            timeout,
            patch.object(refresh, "terminal_agent_running", return_value=True),
            patch.object(refresh, "codex_thread_lock_state", return_value="free"),
            patch.object(refresh, "POLL_INTERVAL_SECONDS", 0),
        ):
            with self.assertRaises(refresh.RefreshError) as caught:
                refresh._wait_codex_resume(self.app_root, session, new_terminal, "0.6.0", transaction_id)

        # Then
        self.assertEqual(caught.exception.code, "resume_unverified")
        record = refresh.registry_sessions(self.app_root)["codex:session-leaf-init"]
        self.assertEqual((record["state"], record["terminal_handle"]), ("ended", "term-init"))


class DraftAndRegistrationPlanTest(OrcaRefreshFixture):
    def test_대기_세션에_보내지_않은_입력이_있으면_계획을_차단한다(self):
        """초안이 남은 세션을 종료하면 입력이 사라지므로 계획 단계에서 막는다."""
        # Given
        draft = patch.object(refresh, "terminal_has_draft", side_effect=lambda handle: handle == "term-other")

        # When
        with draft:
            plan = refresh.create_plan(self.app_root)

        # Then
        self.assertFalse(plan["eligible"])
        self.assertIn("session_has_draft", {item["code"] for item in plan["blockers"]})

    def test_승인_시점에_입력이_생기면_거래를_시작하지_않는다(self):
        """계획 뒤에 초안이 생긴 세션이 있으면 apply 확인에서 멈춘다."""
        # Given
        plan = refresh.create_plan(self.app_root)
        draft = patch.object(refresh, "terminal_has_draft", side_effect=lambda handle: handle == "term-other")

        # When
        with draft:
            with self.assertRaises(refresh.RefreshError) as caught:
                refresh._current_sessions_match_plan(self.app_root, plan, initiator_may_be_busy=True)

        # Then
        self.assertEqual(caught.exception.code, "session_has_draft")

    def test_종료_직전에_입력이_생기면_세션을_종료하지_않는다(self):
        """exit를 보내기 직전에 초안이 보이면 그 세션을 멈추지 않는다."""
        # Given
        plan = refresh.create_plan(self.app_root)
        transaction_id = "b" * 32
        sessions = refresh._current_sessions_match_plan(
            self.app_root, plan, initiator_may_be_busy=True, transaction_id=transaction_id,
        )
        refresh._set_leases(self.app_root, sessions, transaction_id)
        session = next(item for item in sessions if item["host"] == "claude")
        terminal = next(item for item in self.terminals if item["terminal_handle"] == "term-other")
        draft = patch.object(refresh, "terminal_has_draft", return_value=True)

        # When
        with draft:
            with self.assertRaises(refresh.RefreshError) as caught:
                refresh._confirm_exit_target(self.app_root, session, {"transaction_id": transaction_id}, dict(terminal))

        # Then
        self.assertEqual(caught.exception.code, "session_has_draft")

    def test_미등록_Codex는_첫_프롬프트에서_등록된다고_안내한다(self):
        """Codex는 첫 프롬프트에서 등록되므로 차단 사유에 해결 방법을 함께 보여준다."""
        # Given
        self.terminals.append(self.terminal("codex", "term-fresh", "repo-fresh::/tmp/fresh", "/tmp/fresh", "tab-fresh", "leaf-fresh"))

        # When
        plan = refresh.create_plan(self.app_root)

        # Then
        messages = [item["message"] for item in plan["blockers"] if item["code"] == "session_unregistered"]
        self.assertEqual(len(messages), 1)
        self.assertIn("first prompt", messages[0])


class CodexMarketplaceRevisionTest(OrcaRefreshFixture):
    def setUp(self):
        super().setUp()
        self.repo = self.root / "codex-git-marketplace"
        self.repo.mkdir()
        self.git("init", "-q")
        (self.repo / "plugin.json").write_text("{}\n", encoding="utf-8")
        self.git("add", "plugin.json")
        self.git("-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init")
        self.revision = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True).stdout

    def write_install_metadata(self, revision):
        payload = {"source_type": "git", "source": refresh.EXPECTED_REPO_URL, "revision": revision}
        (self.repo / refresh.CODEX_INSTALL_METADATA).write_text(json.dumps(payload), encoding="utf-8")

    def test_Codex_설치_기록만_추가된_복제본은_revision을_신뢰한다(self):
        """Codex upgrade가 남긴 설치 기록은 marketplace 내용 변경으로 보지 않는다."""
        # Given
        self.write_install_metadata(self.revision)

        # When
        result = refresh.git_revision(self.repo, install_metadata=refresh.CODEX_INSTALL_METADATA)

        # Then
        self.assertEqual(result, self.revision)

    def test_설치_기록의_revision이_HEAD와_다르면_신뢰하지_않는다(self):
        """설치 기록이 다른 revision을 가리키면 승인할 내용을 확정할 수 없다."""
        # Given
        self.write_install_metadata("0" * 40)

        # When
        result = refresh.git_revision(self.repo, install_metadata=refresh.CODEX_INSTALL_METADATA)

        # Then
        self.assertIsNone(result)

    def test_설치_기록_외에_추적하지_않는_파일이_있으면_신뢰하지_않는다(self):
        """설치 기록 말고 다른 파일이 추가되었으면 marketplace 내용이 바뀐 것으로 본다."""
        # Given
        self.write_install_metadata(self.revision)
        (self.repo / "extra.md").write_text("changed\n", encoding="utf-8")

        # When
        result = refresh.git_revision(self.repo, install_metadata=refresh.CODEX_INSTALL_METADATA)

        # Then
        self.assertIsNone(result)

    def test_Claude_복제본에는_Codex_설치_기록_예외를_적용하지_않는다(self):
        """예외는 Codex marketplace에만 적용하고 다른 복제본의 추가 파일은 그대로 막는다."""
        # Given
        self.write_install_metadata(self.revision)

        # When
        result = refresh.git_revision(self.repo)

        # Then
        self.assertIsNone(result)


class WorkerRestartTest(OrcaRefreshFixture):
    def test_셸이_남는_두_host_세션을_같은_ID로_재개하고_Codex는_잠금으로_확인한다(self):
        """exit 뒤 셸이 남고 Codex 데몬이 대화를 늦게 닫아도 두 세션을 같은 ID로 재개한다."""
        # Given
        plan = refresh.create_plan(self.app_root)
        with patch.object(refresh.subprocess, "Popen"):
            queued = refresh.apply_plan(self.app_root, plan["plan_id"])
        transaction_id = queued["transaction_id"]
        installed = {"codex": "0.5.2", "claude": "0.5.2"}
        agent_alive = {"term-init": True, "term-other": True}
        codex_lock = {"state": "held", "release_polls": 2}
        created: list[list[str]] = []

        def fake_run_command(argv, *, timeout=30.0, check=True):
            command = list(argv)
            if command[:3] == ["claude", "plugin", "update"]:
                installed["claude"] = "0.6.0"
            elif command[:3] == ["codex", "plugin", "add"]:
                installed["codex"] = "0.6.0"
            elif command[1:3] == ["terminal", "close"]:
                handle = command[command.index("--terminal") + 1]
                self.terminals[:] = [item for item in self.terminals if item["terminal_handle"] != handle]
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        def fake_run_json(argv, *, timeout=30.0):
            command = list(argv)
            if command[1:3] == ["terminal", "send"]:
                handle = command[command.index("--terminal") + 1]
                if command[command.index("--text") + 1] == "/exit":
                    agent_alive[handle] = False
                return ACCEPTED_SEND
            if command[1:3] == ["terminal", "create"]:
                args = command[3:]
                created.append(args)
                worktree = args[args.index("--worktree") + 1].removeprefix("id:")
                title = args[args.index("--title") + 1]
                host = "claude" if "-claude-" in title else "codex"
                old = next(item for item in plan["sessions"] if item["host"] == host)
                new_handle = f"term-new-{host}"
                new_terminal = self.terminal(host, new_handle, worktree, old["worktree_path"], old["tab_id"], old["leaf_id"])
                new_terminal["title"] = title
                self.terminals.append(new_terminal)
                agent_alive[new_handle] = True
                if host == "codex":
                    codex_lock["state"] = "held"
                else:
                    hook_env = {
                        "ORCA_TERMINAL_HANDLE": new_handle,
                        "ORCA_WORKTREE_ID": worktree,
                        "ORCA_TAB_ID": old["tab_id"],
                        "ORCA_PANE_KEY": f"{old['tab_id']}:{old['leaf_id']}",
                    }
                    with patch.dict(os.environ, hook_env):
                        os.environ.pop("PLUGIN_ROOT", None)
                        lifecycle.handle_event({
                            "hook_event_name": "SessionStart", "source": "resume",
                            "session_id": old["session_id"], "cwd": old["cwd"],
                        })
                return {"result": {"terminal": {"handle": new_handle}}}
            self.fail(f"unexpected JSON CLI command: {command[:3]}")

        def fake_lock_state(session_id):
            if codex_lock["state"] == "held" and not agent_alive["term-init"] and "term-new-codex" not in agent_alive:
                codex_lock["release_polls"] -= 1
                if codex_lock["release_polls"] < 0:
                    codex_lock["state"] = "free"
                    with registry_lock(self.app_root) as registry:
                        record = registry["sessions"]["codex:session-leaf-init"]
                        record["state"] = "ended"
                        record["last_event"] = "SessionEnd"
            return codex_lock["state"]

        with (
            patch.object(refresh, "run_command", side_effect=fake_run_command),
            patch.object(refresh, "run_json", side_effect=fake_run_json),
            patch.object(refresh, "_installed_versions", side_effect=lambda: dict(installed)),
            patch.object(refresh, "_verify_installed_versions", side_effect=lambda targets: dict(installed)),
            patch.object(refresh, "terminal_inventory", side_effect=lambda: [dict(item) for item in self.terminals]),
            patch.object(refresh, "terminal_agent_running", side_effect=lambda handle, host: agent_alive.get(handle, False)),
            patch.object(refresh, "codex_thread_lock_state", side_effect=fake_lock_state),
            patch.object(refresh, "codex_resume_settings", return_value={"resume_model": "gpt-6-sol", "resume_effort": "high"}),
            patch.object(refresh, "wait_terminal", side_effect=lambda handle, condition, timeout: condition == "tui-idle"),
            patch.object(refresh, "POLL_INTERVAL_SECONDS", 0),
        ):
            with registry_lock(self.app_root) as registry:
                registry["sessions"]["codex:session-leaf-init"]["state"] = "idle"
                registry["sessions"]["codex:session-leaf-init"]["last_event"] = "Stop"
            # When
            result = refresh._run_worker(self.app_root, transaction_id)

        # Then
        receipt = refresh._load_receipt(self.app_root, transaction_id)
        self.assertEqual(result, 0, receipt)
        self.assertEqual(receipt["state"], "complete")
        records = refresh.registry_sessions(self.app_root)
        for host, session_id in (("codex", "session-leaf-init"), ("claude", "session-leaf-other")):
            record = records[f"{host}:{session_id}"]
            self.assertEqual(refresh.base_version(record["plugin_version"]), "0.6.0")
            self.assertEqual(record["terminal_handle"], f"term-new-{host}")
            self.assertEqual(record["state"], "idle")
            self.assertNotIn("refresh_transaction_id", record)
        self.assertEqual(records["codex:session-leaf-init"]["last_event"], "RefreshResume")
        codex_command = next(args for args in created if "-codex-" in args[args.index("--title") + 1])
        shell_command = codex_command[codex_command.index("--command") + 1]
        self.assertIn("resume session-leaf-init -m gpt-6-sol -c 'model_reasoning_effort=\"high\"'", shell_command)
        registrations = {item["host"]: item.get("plugin_registration") for item in refresh._public_receipt(receipt)["sessions"]}
        self.assertEqual(registrations, {"codex": "pending_next_turn", "claude": "confirmed"})
        self.assertEqual(codex_lock["release_polls"], -1)

    def test_Codex_대화가_계속_열려_있으면_수동_재개_명령을_남긴다(self):
        """이전 터미널을 닫은 뒤 대화 잠금이 풀리지 않으면 새 Codex 없이 수동 명령을 기록한다."""
        # Given
        session = {
            "host": "codex", "cwd": "/tmp/init", "session_id": "session-leaf-init",
            "previous_terminal_closed": True, "resume_model": "gpt-6-sol", "resume_effort": "high",
        }

        # When
        refresh._record_resume_recovery(session, "codex_thread_still_open")

        # Then
        self.assertIn("resume session-leaf-init -m gpt-6-sol", session["manual_resume_command"])
        self.assertFalse(session["manual_resume_requires_terminal_check"])
