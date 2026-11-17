"""Tests of the per-request caps on delegated runs and retries, and of the parallel limit computed from the machine."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import threading
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import approval_state_store as store  # noqa: E402
import request_budget as budget  # noqa: E402
import role_runner  # noqa: E402
from role_runner_config import EXIT_CAPPED  # noqa: E402

COUNTER_PATH = REPO_ROOT / "evals" / "request-budget" / "count_requests.py"
RECORD_PATH = REPO_ROOT / "evals" / "request-budget" / "distribution.json"
E2E_RECORD_PATH = REPO_ROOT / "evals" / "e2e" / "records" / "97.json"
SESSION = "session-main"
OWNER = ("claude", SESSION)
GIB = 1024
PLUGIN_AGENT = "hei5enbug-agent-setup:scout"


def machine(cpus=12, gib=20.0, load=1.0, fraction=0.5):
    return budget.Machine(cpus, None if gib is None else int(gib * GIB), load, fraction)


def load_counter():
    spec = importlib.util.spec_from_file_location("count_requests", COUNTER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BudgetCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        environment = {
            "XDG_STATE_HOME": str(self.home / "state"), "HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / "claude"),
            "HEI5ENBUG_REQUEST_RUN_CAP": "0", "HEI5ENBUG_REQUEST_RETRY_CAP": "0", "CLAUDE_PLUGIN_OPTION_REQUEST_RUN_CAP": "0",
            "CLAUDE_PLUGIN_OPTION_REQUEST_RETRY_CAP": "0",
        }
        patcher = mock.patch.dict(os.environ, environment)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("HEI5ENBUG_PARENT_SESSION", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CODEX_SESSION_ID",
                     budget.CEILING_ENV):
            os.environ.pop(name, None)
        os.environ["HEI5ENBUG_MACHINE_COUNTERS_FOR_TESTS"] = "1.0,12,0.5,0.5"
        os.environ[budget.MEMORY_MB_ENV] = str(20 * GIB)
        self.ids = iter(range(1, 10_000))

    def caps(self, runs: int, retries: int = 0) -> None:
        os.environ["HEI5ENBUG_REQUEST_RUN_CAP"] = os.environ["CLAUDE_PLUGIN_OPTION_REQUEST_RUN_CAP"] = str(runs)
        os.environ["HEI5ENBUG_REQUEST_RETRY_CAP"] = os.environ["CLAUDE_PLUGIN_OPTION_REQUEST_RETRY_CAP"] = str(retries)

    def admit(self, key="worker", owner=OWNER, pid=None, limit=64, run_id=None):
        return budget.admit(
            owner, key, os.getpid() if pid is None else pid, run_id or f"id-{next(self.ids)}", machine(), limit_of_host=limit,
        )

    def delegated(self, owner=OWNER) -> dict:
        return store._read(store.state_dir() / f"{owner[0]}-{owner[1]}.json")["delegated"]

    def spawn_event(self, agent=PLUGIN_AGENT, tool="Agent", session=SESSION) -> dict:
        return {"hook_event_name": "PreToolUse", "session_id": session, "tool_name": tool, "tool_use_id": f"toolu-{next(self.ids)}",
                "tool_input": {"subagent_type": agent}}


class ParallelLimitTest(unittest.TestCase):
    def test_사양이_알려진_기계는_CPU_메모리_호스트_한도_중_가장_낮은_값에서_하나를_빼거나_내린다(self):
        """CPU 12개·여유 메모리 20GiB·호스트 한도 16은 11이고, 3GiB는 3, 0.8GiB는 최소 1이다."""
        # Given
        cases = {(12, 20.0, 16): 11, (12, 3.0, 16): 3, (12, 0.8, 16): 1}

        # When
        limits = {case: budget.parallel_limit(machine(case[0], case[1]), case[2]) for case in cases}

        # Then
        self.assertEqual(limits, cases)

    def test_부하가_CPU의_두_배_이상이거나_메모리가_10퍼센트_미만이면_한도는_하나이다(self):
        """12개 CPU에서 부하 24, 그리고 CPU를 읽지 못해도 여유 메모리 비율이 10% 미만이면 1이다."""
        # Given
        loaded = machine(12, 20.0, load=24.0)
        unreadable_cpu_short_memory = machine(None, 3.0, load=None, fraction=0.05)

        # When
        limits = (budget.parallel_limit(loaded, 16), budget.parallel_limit(unreadable_cpu_short_memory, 16))

        # Then
        self.assertEqual(limits, (1, 1))

    def test_읽을_수_없는_항목은_빼고_결과를_여섯으로_막으며_알려진_호스트_한도는_계속_적용한다(self):
        """CPU를 못 읽고 3GiB면 3, 20GiB에 호스트 16이면 6, 둘 다 못 읽고 호스트 4면 4이다."""
        # Given
        unreadable = machine(None, 3.0, load=None)

        # When
        limits = (
            budget.parallel_limit(unreadable),
            budget.parallel_limit(machine(None, 20.0, load=None), 16),
            budget.parallel_limit(machine(None, None, load=None, fraction=None), 4),
        )

        # Then
        self.assertEqual(limits, (3, 6, 4))

    def test_측정으로_정해지는_상한은_계산한_한도를_넘지_못하게_막는다(self):
        """상한 6을 주면 11이 6이 되고, 상한이 없으면 11 그대로이다."""
        # Given
        spare = machine(12, 20.0)

        # When
        capped, free = budget.parallel_limit(spare, 16, 6), budget.parallel_limit(spare, 16, None)

        # Then
        self.assertEqual((capped, free), (6, 11))


class RequestCapTest(BudgetCase):
    def test_실행_상한이_10이면_열_번째는_허용하고_열한_번째는_상한과_횟수와_보고_지시가_담긴_메시지로_거부한다(self):
        """열한 번째 시작은 거부되고 메시지에 상한 10, 횟수 10, 진행 중 작업 완료 허용, 중단 보고 지시가 있다."""
        # Given
        self.caps(10)
        first_ten = [self.admit().allowed for _ in range(10)]

        # When
        eleventh = self.admit()

        # Then
        self.assertTrue(all(first_ten))
        self.assertFalse(eleventh.allowed)
        for fragment in ("cap of 10", "(10 counted)", "may finish", "report the request as stopped", "never as done"):
            self.assertIn(fragment, eleventh.message)

    def test_상한이_0이면_아무것도_거부하지_않는다(self):
        """실행과 재시도 상한이 0이면 60번 시작해도 모두 허용된다."""
        # Given
        self.caps(0, 0)

        # When
        verdicts = []
        for _ in range(60):
            verdicts.append(self.admit(run_id="run"))
            budget.finish(OWNER, "run")

        # Then
        self.assertTrue(all(verdict.allowed for verdict in verdicts))

    def test_훅의_에이전트_시작과_실행기_실행은_같은_요청의_한_횟수에_더해진다(self):
        """상한 2에서 에이전트 시작 하나와 실행기 실행 하나 뒤의 세 번째 시작은 거부된다."""
        # Given
        self.caps(2)
        owner = ("claude", SESSION)
        with mock.patch.dict(os.environ, {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": SESSION}):
            from_hook = budget.pre_spawn(self.spawn_event(), "claude")
            from_runner = budget.acquire(budget.environment_owner(), "scout", "runner:1")

            # When
            third = budget.pre_spawn(self.spawn_event(), "claude")

        # Then
        self.assertIsNone(from_hook)
        self.assertIsNone(from_runner)
        self.assertEqual(self.delegated(owner)["runs"], 2)
        self.assertIn("cap of 2", third)

    def test_실행기_자식이_시작한_실행은_프롬프트를_받은_세션의_횟수에_더해진다(self):
        """부모 세션 변수가 있는 자식 프로세스의 훅 시작은 자식 세션이 아니라 부모 세션의 횟수를 올린다."""
        # Given
        with mock.patch.dict(os.environ, {"HEI5ENBUG_PARENT_SESSION": f"claude:{SESSION}"}):
            # When
            denial = budget.pre_spawn(self.spawn_event(session="session-child"), "claude")

        # Then
        self.assertIsNone(denial)
        self.assertEqual(self.delegated()["runs"], 1)
        self.assertEqual(self.delegated(("claude", "session-child"))["runs"], 0)

    def test_다음_프롬프트가_오면_횟수가_0이고_실행기_자식의_프롬프트는_부모_횟수를_지우지_않는다(self):
        """사용자 프롬프트는 횟수를 0으로 되돌리고, 부모 세션 변수가 있는 프롬프트는 되돌리지 않는다."""
        # Given
        self.admit()
        self.admit()
        prompt = {"hook_event_name": "UserPromptSubmit", "session_id": SESSION, "prompt": "next"}
        with mock.patch.dict(os.environ, {"HEI5ENBUG_PARENT_SESSION": f"claude:{SESSION}"}):
            budget.handle(prompt, "claude")
        kept = self.delegated()["runs"]

        # When
        budget.handle(prompt, "claude")

        # Then
        self.assertEqual((kept, self.delegated()["runs"]), (2, 0))

    def test_상한보다_하나_적은_횟수에서_동시에_시작한_둘은_정확히_하나만_허용된다(self):
        """상한 10에서 아홉 번째까지 센 뒤 여섯 스레드가 함께 시작하면 허용은 하나이다."""
        # Given
        self.caps(10)
        for _ in range(9):
            self.admit()
        barrier = threading.Barrier(6)
        results: list[bool] = []

        def launch() -> None:
            barrier.wait()
            results.append(self.admit().allowed)

        threads = [threading.Thread(target=launch) for _ in range(6)]

        # When
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Then
        self.assertEqual(results.count(True), 1)
        self.assertEqual(self.delegated()["runs"], 10)

    def test_같은_종류의_실행이_오류로_끝난_뒤_다시_시작하면_재시도로_세고_재시도_상한에서_멈춘다(self):
        """재시도 상한 2에서 오류로 끝난 worker를 두 번 다시 시작하면 세 번째 재시작이 거부되고 그 뒤로도 거부된다."""
        # Given
        self.caps(0, 2)
        verdicts = []

        # When
        for _ in range(4):
            verdict = self.admit("worker", run_id="run")
            verdicts.append(verdict.allowed)
            if verdict.allowed:
                budget.finish(OWNER, "run", failed=True)
        after_denial = self.admit("worker")

        # Then
        self.assertEqual(verdicts, [True, True, True, False])
        self.assertEqual(self.delegated()["retries"], 2)
        self.assertFalse(after_denial.allowed)
        self.assertIn("2 retries", after_denial.message)

    def test_다른_종류의_실행이_성공한_뒤_시작은_재시도가_아니다(self):
        """worker가 오류로 끝난 뒤 scout를 시작하거나 worker가 성공한 뒤 다시 시작해도 재시도 횟수는 0이다."""
        # Given
        self.caps(0, 1)
        self.admit("worker", run_id="a")
        budget.finish(OWNER, "a", failed=True)

        # When
        self.admit("scout", run_id="b")
        budget.finish(OWNER, "b", failed=False)
        self.admit("scout")

        # Then
        self.assertEqual(self.delegated()["retries"], 0)

    def test_Agent_호출이_오류로_끝났다는_훅은_그_종류의_다음_시작을_재시도로_만든다(self):
        """PostToolUseFailure를 받은 scout의 다음 시작은 재시도 1이고 Bash의 실패 훅은 아무 표시도 남기지 않는다."""
        # Given
        self.caps(0, 5)
        event = self.spawn_event()
        budget.pre_spawn(event, "claude")
        bash_failure = {"hook_event_name": "PostToolUseFailure", "session_id": SESSION, "tool_name": "Bash", "tool_use_id": "other"}
        failure = {**bash_failure, "tool_name": "Agent", "tool_use_id": event["tool_use_id"]}

        # When
        budget.handle(bash_failure, "claude")
        kept = self.delegated()["failed"]
        budget.handle(failure, "claude")
        budget.pre_spawn(self.spawn_event(), "claude")

        # Then
        self.assertEqual(kept, [])
        self.assertEqual(self.delegated()["retries"], 1)

    def test_숨겨진_내장_에이전트와_Agent가_아닌_도구는_세지_않는다(self):
        """내장 general-purpose 시작과 Bash 호출은 횟수를 올리지 않는다."""
        # Given
        self.caps(1)
        bash = {**self.spawn_event(), "tool_name": "Bash"}

        # When
        budget.pre_spawn(self.spawn_event("general-purpose"), "claude")
        budget.pre_spawn(bash, "claude")

        # Then
        self.assertEqual(self.delegated()["runs"], 0)

    def test_세션_ID가_없는_호출은_세지도_거부하지도_않는다(self):
        """세션 ID가 비어 있으면 기억할 곳이 없으므로 상한 1에서도 항상 허용한다."""
        # Given
        self.caps(1)

        # When
        results = [budget.pre_spawn(self.spawn_event(session=""), "claude") for _ in range(3)]

        # Then
        self.assertEqual(results, [None, None, None])


class DefaultCapTest(unittest.TestCase):
    def test_가장_큰_횟수가_30이면_실행_상한은_40이고_재시도_상한은_가장_큰_횟수에_하나를_더한다(self):
        """분포의 가장 큰 실행 30은 상한 40, 가장 큰 재시도 2는 상한 3이다."""
        # Given
        record = {"requests_with_a_delegated_run": 5, "largest_runs": 30, "largest_retries": 2}

        # When
        caps = load_counter().default_caps(record)

        # Then
        self.assertEqual(caps, (40, 3))

    def test_위임_실행이_있는_요청이_없으면_두_상한은_0이다(self):
        """위임 실행이 없는 기록은 두 상한을 0으로 내보낸다."""
        # Given
        record = {"requests_with_a_delegated_run": 0, "largest_runs": 0, "largest_retries": 0}

        # When
        caps = load_counter().default_caps(record)

        # Then
        self.assertEqual(caps, (0, 0))

    def test_커밋한_기록의_가장_큰_횟수는_기본_상한에_걸리지_않고_기본값은_기록에서_나온다(self):
        """모듈의 기본 상한은 기록의 규칙값이고, 기록의 어떤 요청도 그 상한에서 거부되지 않는다."""
        # Given
        record = json.loads(RECORD_PATH.read_text(encoding="utf-8"))

        # When
        derived = load_counter().default_caps(record)

        # Then
        self.assertEqual((budget.DEFAULT_RUN_CAP, budget.DEFAULT_RETRY_CAP), derived)
        self.assertLess(record["largest_runs"], budget.DEFAULT_RUN_CAP)
        self.assertLess(record["largest_retries"], budget.DEFAULT_RETRY_CAP)
        manifest = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["userConfig"]
        self.assertEqual(
            (manifest["request_run_cap"]["default"], manifest["request_retry_cap"]["default"]),
            (str(budget.DEFAULT_RUN_CAP), str(budget.DEFAULT_RETRY_CAP)),
        )


class RunningLimitTest(BudgetCase):
    def dead_pid(self) -> int:
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        return child.pid

    def test_한도_3에서_이_세션이_하나_다른_세션이_둘이면_이_세션의_시작은_거부되고_하나가_끝나면_허용된다(self):
        """실행 셋이 돌고 있으면 이 세션의 넷째 시작은 한도 메시지로 거부되고, 이 세션의 실행이 끝나면 허용된다."""
        # Given
        other = ("claude", "session-other")
        self.admit("a", pid=os.getpid(), run_id="mine", limit=3)
        self.admit("b", owner=other, run_id="o1", limit=3)
        self.admit("c", owner=other, run_id="o2", limit=3)

        # When
        denied = self.admit("d", run_id="mine-2", limit=3)
        budget.finish(OWNER, "mine")
        allowed = self.admit("d", run_id="mine-2", limit=3)

        # Then
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason, "limit")
        self.assertIn("do not poll", denied.message)
        self.assertTrue(allowed.allowed)

    def test_실행이_없는_세션은_한도가_차_있어도_하나를_시작할_수_있다(self):
        """다른 세션이 한도를 채워도 실행이 없는 세 번째 세션은 하나를 시작한다."""
        # Given
        for index in range(3):
            self.admit("a", owner=("claude", f"busy-{index}"), run_id=f"b{index}", limit=3)

        # When
        verdict = self.admit("a", owner=("claude", "idle"), run_id="idle-1", limit=3)

        # Then
        self.assertTrue(verdict.allowed)

    def test_프로세스가_사라진_기록은_세지_않고_다음_읽기에서_버려진다(self):
        """죽은 프로세스의 실행은 한도에 들어가지 않아 같은 세션의 다음 시작이 허용된다."""
        # Given
        self.admit("a", pid=self.dead_pid(), run_id="gone", limit=1)
        self.admit("a", run_id="alive", limit=1)

        # When
        verdict = self.admit("a", run_id="next", limit=2)

        # Then
        self.assertTrue(verdict.allowed)
        self.assertEqual([entry["id"] for entry in budget.read_runs()], ["alive", "next"])

    def test_서브에이전트_종료_훅은_같은_종류의_가장_오래된_에이전트_실행을_끝내고_실행기_실행은_건드리지_않는다(self):
        """scout 둘과 실행기 하나가 도는 중 scout 종료 훅 하나는 먼저 시작한 scout만 지우고, 모르는 종류의 종료는 가장 오래된 에이전트를 지운다."""
        # Given
        self.admit("scout", run_id="toolu-1")
        self.admit("worker", run_id="toolu-2")
        self.admit("scout", run_id="runner:1")
        stop = {"hook_event_name": "SubagentStop", "session_id": SESSION, "agent_type": "scout"}

        # When
        budget.handle(stop, "claude")
        after_scout = [entry["id"] for entry in budget.read_runs()]
        budget.handle({**stop, "agent_type": "unknown"}, "claude")

        # Then
        self.assertEqual(after_scout, ["toolu-2", "runner:1"])
        self.assertEqual([entry["id"] for entry in budget.read_runs()], ["runner:1"])
        self.assertEqual(self.delegated()["failed"], [])


class RunnerLaunchTest(BudgetCase):
    def test_한도가_막고_있는_실행은_기다렸다가_이_세션의_실행이_끝나면_시작한다(self):
        """한도 1에서 이 세션의 실행이 있으면 acquire는 기다리고, 그 실행이 끝난 뒤 통과한다."""
        # Given
        budget.admit(OWNER, "scout", os.getpid(), "first", machine(2, 20.0), limit_of_host=1)
        waits: list[float] = []

        def sleep(seconds: float) -> None:
            waits.append(seconds)
            budget.finish(OWNER, "first")

        # When
        with mock.patch.object(budget, "host_limit", return_value=1), \
                mock.patch.object(budget, "read_machine", return_value=machine(2, 20.0)):
            denial = budget.acquire(OWNER, "scout", "second", sleep=sleep)

        # Then
        self.assertIsNone(denial)
        self.assertEqual(len(waits), 1)

    def test_상한에_닿은_요청의_실행기_쌍은_자식을_시작하지_않고_종료_코드_5와_중단_보고_문장으로_끝난다(self):
        """상한 1에서 두 번째 쌍은 자식 프로세스 없이 종료 코드 5의 상태 줄과 오류 문장을 돌려준다."""
        # Given
        self.caps(1)
        self.admit("scout", run_id="earlier")
        args = role_runner.build_parser().parse_args(["scout", "--assignment", "a.md", "--result", "r.md"])
        run = mock.Mock(agent=None, role="scout", capability=None, target="scout")

        # When
        with mock.patch.dict(os.environ, {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": SESSION}), \
                mock.patch.object(role_runner, "execute", side_effect=AssertionError("a capped pair started a child")), \
                mock.patch.object(role_runner, "status", return_value="{}"):
            code, _, error = role_runner.run_pair(args, run, REPO_ROOT, os.getcwd(), "a.md", "r.md")

        # Then
        self.assertEqual(code, EXIT_CAPPED)
        self.assertIn("report the request as stopped", error)

    def test_실행기_쌍이_비정상으로_끝나면_같은_역할의_다음_시작은_재시도로_센다(self):
        """실패한 scout 쌍 뒤에 같은 scout를 시작하면 재시도 횟수가 1이다."""
        # Given
        self.caps(0, 5)
        args = role_runner.build_parser().parse_args(["scout", "--assignment", "a.md", "--result", "r.md"])
        run = mock.Mock(agent=None, role="scout", capability=None, target="scout", writing=True)
        failure = role_runner.RunnerError(3, "child failed")

        # When
        with mock.patch.dict(os.environ, {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": SESSION}), \
                mock.patch.object(role_runner, "execute", side_effect=failure), \
                mock.patch.object(role_runner, "status", return_value="{}"):
            role_runner.run_pair(args, run, REPO_ROOT, os.getcwd(), "a.md", "r.md")
            role_runner.run_pair(args, run, REPO_ROOT, os.getcwd(), "a.md", "r.md")

        # Then
        self.assertEqual(self.delegated()["retries"], 1)


class CodexHookTest(BudgetCase):
    def run_guard(self, event: dict, **options: str) -> dict | None:
        environment = {
            **os.environ, "PLUGIN_ROOT": str(REPO_ROOT), "CODEX_HOME": str(self.home / "codex"), **options,
        }
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "agent_guard.py")], input=json.dumps(event), capture_output=True, text=True,
            env=environment, cwd=REPO_ROOT, check=True, timeout=60,
        )
        return json.loads(result.stdout) if result.stdout.strip() else None

    def test_Codex_에이전트_가드는_허용한_spawn_agent를_세고_상한에서_같은_형식으로_거부한다(self):
        """상한 1에서 첫 scout 시작은 출력이 없고 둘째는 상한과 중단 보고 지시가 담긴 거부 JSON이다."""
        # Given
        role = (REPO_ROOT / ".codex" / "agents" / "scout.toml").read_text(encoding="utf-8")
        settings = tomllib.loads(role)
        event = {
            "hook_event_name": "PreToolUse", "session_id": "codex-session", "tool_name": "spawn_agent", "cwd": str(REPO_ROOT),
            "tool_use_id": "call-1",
            "tool_input": {"agent_type": "scout", "model": settings["model"], "reasoning_effort": settings["model_reasoning_effort"]},
        }
        options = {"HEI5ENBUG_REQUEST_RUN_CAP": "1", "CLAUDE_PLUGIN_OPTION_REQUEST_RUN_CAP": "1"}

        # When
        first = self.run_guard(event, **options)
        second = self.run_guard({**event, "tool_use_id": "call-2"}, **options)

        # Then
        self.assertIsNone(first)
        output = second["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("report the request as stopped", output["permissionDecisionReason"])


class ClaudeHookTest(BudgetCase):
    def run_hook(self, event: dict) -> dict | None:
        environment = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)}
        environment.pop("PLUGIN_ROOT", None)
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "request_budget.py")], input=json.dumps(event), capture_output=True,
            text=True, env=environment, cwd=self.home, check=True, timeout=60,
        )
        return json.loads(result.stdout) if result.stdout.strip() else None

    def test_Claude_Agent_훅_스크립트는_상한에_닿은_요청의_다음_시작을_거부_JSON으로_답한다(self):
        """상한 1에서 첫 Agent 시작은 출력이 없고 둘째는 deny 결정과 중단 보고 지시를 JSON으로 낸다."""
        # Given
        self.caps(1)

        # When
        first = self.run_hook(self.spawn_event())
        second = self.run_hook(self.spawn_event())

        # Then
        self.assertIsNone(first)
        decision = second["hookSpecificOutput"]
        self.assertEqual((decision["hookEventName"], decision["permissionDecision"]), ("PreToolUse", "deny"))
        self.assertIn("never as done", decision["permissionDecisionReason"])


class ParallelCeilingRecordTest(unittest.TestCase):
    @staticmethod
    def case_passed(record: dict, case: str) -> bool:
        return any(
            entry.get("case") == case and entry.get("measure") == "claim" and entry.get("verdict") == "accept"
            for entry in record.get("verdicts", [])
        )

    def test_계산한_한도는_측정_사례_P가_통과했을_때만_여섯_상한이_풀린다(self):
        """측정 기록이 없거나 P의 개선 주장이 받아들여지지 않았으면 상한 6이고, 받아들여졌으면 상한이 없다."""
        # Given
        expected = 6
        if E2E_RECORD_PATH.is_file():
            record = json.loads(E2E_RECORD_PATH.read_text(encoding="utf-8"))
            expected = None if self.case_passed(record, "T54") else 6

        # When
        actual = budget.PARALLEL_CEILING

        # Then
        self.assertEqual(actual, expected)

    def test_P_통과_판정은_개선_주장의_accept_항목만_통과로_본다(self):
        """reject나 second pair 항목, 다른 사례의 accept는 P의 통과가 아니다."""
        # Given
        accepted = {"verdicts": [{"case": "T54", "measure": "claim", "verdict": "accept"}]}
        others = {"verdicts": [
            {"case": "T54", "measure": "claim", "verdict": "reject"},
            {"case": "T54", "measure": "claim", "verdict": "second pair"},
            {"case": "T05", "measure": "claim", "verdict": "accept"},
        ]}

        # When
        outcomes = (self.case_passed(accepted, "T54"), self.case_passed(others, "T54"))

        # Then
        self.assertEqual(outcomes, (True, False))


if __name__ == "__main__":
    unittest.main()
