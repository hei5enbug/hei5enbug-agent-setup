"""Tests of the delegation depth rule: main session, area coordinator, and the workers it starts."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import approval_state_store as store  # noqa: E402
import delegation_depth as depth  # noqa: E402
import request_budget as budget  # noqa: E402
import role_runner  # noqa: E402
import role_runner_child  # noqa: E402
import role_runner_command  # noqa: E402
import role_runner_config as config  # noqa: E402
import role_runner_evidence as evidence  # noqa: E402

MAIN_SESSION = "session-main"
PREFIX = "hei5enbug-agent-setup:"
COORDINATOR_ENV = {
    depth.LAYER_ENV: depth.COORDINATOR, depth.ASSIGNED_ROLE_ENV: depth.COORDINATOR_ROLE,
    depth.PARENT_SESSION_ENV: f"claude:{MAIN_SESSION}",
}
WORKER_ENV = {depth.LAYER_ENV: depth.WORKER, depth.ASSIGNED_ROLE_ENV: "worker", depth.PARENT_SESSION_ENV: f"claude:{MAIN_SESSION}"}
CLEARED = (
    depth.LAYER_ENV, depth.ASSIGNED_ROLE_ENV, depth.PARENT_SESSION_ENV, "CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID",
    "CODEX_SESSION_ID", role_runner_child.SUBAGENT_DEPTH_ENV,
)


class DepthCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        environment = {
            "XDG_STATE_HOME": str(self.home / "state"), "HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / "claude"),
            "HEI5ENBUG_REQUEST_RUN_CAP": "0", "HEI5ENBUG_REQUEST_RETRY_CAP": "0", "CLAUDE_PLUGIN_OPTION_REQUEST_RUN_CAP": "0",
            "CLAUDE_PLUGIN_OPTION_REQUEST_RETRY_CAP": "0", "HEI5ENBUG_MACHINE_COUNTERS_FOR_TESTS": "1.0,12,0.5,0.5",
            budget.MEMORY_MB_ENV: str(20 * 1024),
        }
        patcher = mock.patch.dict(os.environ, environment)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in (*CLEARED, budget.CEILING_ENV):
            os.environ.pop(name, None)
        self.count = 0

    def spawn(self, agent: str, session: str = "session-child", agent_id: str | None = None) -> dict:
        self.count += 1
        event = {"hook_event_name": "PreToolUse", "session_id": session, "tool_name": "Agent", "tool_use_id": f"toolu-{self.count}",
                 "tool_input": {"subagent_type": agent}}
        return {**event, "agent_id": agent_id} if agent_id else event

    def main_runs(self) -> int:
        return store._read(store.state_dir() / f"claude-{MAIN_SESSION}.json")["delegated"]["runs"]

    def plan(self, *arguments: str):
        assignment, result = self.home / "assignment.md", self.home / "result.md"
        assignment.write_text("task", encoding="utf-8")
        return role_runner.plan(role_runner.build_parser().parse_args(
            [*arguments, "--assignment", str(assignment), "--result", str(result)]))


class AgentLaunchTest(DepthCase):
    def test_코디네이터_아래_서브에이전트_워커의_에이전트_시작은_거부되고_세지_않는다(self):
        """코디네이터 세션 환경에서 agent_id가 붙은 이벤트의 구현 워커 시작도 거부하고 메인 세션의 횟수를 올리지 않는다."""
        # Given
        event = self.spawn(f"{PREFIX}sonnet-worker", agent_id="agent-1")

        # When
        with mock.patch.dict(os.environ, COORDINATOR_ENV):
            denial = budget.pre_spawn(event, "claude")

        # Then
        self.assertIn("a worker under an area coordinator starts nothing", denial)
        self.assertEqual(self.main_runs(), 0)

    def test_코디네이터가_시작한_러너_자식_워커는_에이전트_시작이_모두_거부된다(self):
        """워커 층 환경의 프로세스는 에이전트 유형과 관계없이 시작을 거부당한다."""
        # Given
        agents = (f"{PREFIX}worker", "worker", "general-purpose")

        # When
        with mock.patch.dict(os.environ, WORKER_ENV):
            denials = [budget.pre_spawn(self.spawn(agent), "claude") for agent in agents]

        # Then
        self.assertTrue(all("starts nothing" in denial for denial in denials), denials)

    def test_코디네이터는_구현_워커만_시작하고_그_밖의_유형과_다른_코디네이터는_거부된다(self):
        """코디네이터 환경에서 두 워커 유형은 허용하고 리뷰어, 스카우트, 일반 에이전트, 코디네이터 유형은 거부한다."""
        # Given
        allowed = (f"{PREFIX}worker", f"{PREFIX}sonnet-worker", "worker")
        denied = (f"{PREFIX}reviewer", f"{PREFIX}scout", f"{PREFIX}designer", "general-purpose", depth.COORDINATOR_ROLE)

        # When
        with mock.patch.dict(os.environ, COORDINATOR_ENV):
            allowed_results = [budget.pre_spawn(self.spawn(agent), "claude") for agent in allowed]
            denied_results = [budget.pre_spawn(self.spawn(agent), "claude") for agent in denied]

        # Then
        self.assertEqual(allowed_results, [None, None, None])
        self.assertTrue(all(result and "Denied" in result for result in denied_results), denied_results)

    def test_코디네이터가_시작한_워커는_프롬프트를_받은_메인_세션의_요청_횟수에_더해진다(self):
        """코디네이터 환경의 워커 시작은 코디네이터 세션이 아니라 부모 변수가 가리키는 메인 세션의 횟수를 올린다."""
        # Given
        event = self.spawn(f"{PREFIX}sonnet-worker", session="session-coordinator")

        # When
        with mock.patch.dict(os.environ, COORDINATOR_ENV):
            denial = budget.pre_spawn(event, "claude")

        # Then
        self.assertIsNone(denial)
        self.assertEqual(self.main_runs(), 1)
        coordinator = store._read(store.state_dir() / "claude-session-coordinator.json")["delegated"]["runs"]
        self.assertEqual(coordinator, 0)

    def test_계층_표시가_없는_자식과_메인_세션은_기존_규칙대로_리뷰어와_스카우트를_시작한다(self):
        """코디네이터와 무관한 자식과 메인 세션의 에이전트 시작은 깊이 규칙에 걸리지 않는다."""
        # Given
        child = {depth.ASSIGNED_ROLE_ENV: "reviewer", depth.PARENT_SESSION_ENV: f"claude:{MAIN_SESSION}"}

        # When
        main = budget.pre_spawn(self.spawn(f"{PREFIX}reviewer", session=MAIN_SESSION), "claude")
        with mock.patch.dict(os.environ, child):
            other = budget.pre_spawn(self.spawn(f"{PREFIX}scout"), "claude")

        # Then
        self.assertEqual((main, other), (None, None))


class RunnerLaunchTest(DepthCase):
    def test_메인_세션은_코디네이터를_시작할_수_있다(self):
        """계층 표시가 없는 환경에서 area-coordinator 역할 호출은 쓰기 가능한 Claude 실행으로 풀린다."""
        # Given
        folder = str(self.home)

        # When
        run = self.plan(depth.COORDINATOR_ROLE, "--host", "claude", "--add-dir", folder)

        # Then
        self.assertEqual((run.role, run.writing, run.add_dirs), (depth.COORDINATOR_ROLE, True, (folder,)))

    def test_코디네이터는_다른_코디네이터와_구현_워커_밖의_역할_능력_에이전트를_시작하지_못한다(self):
        """코디네이터 환경의 러너 호출은 area-coordinator, reviewer, 능력 design, 리뷰 에이전트를 종료 코드 2의 사용 오류로 거부한다."""
        # Given
        folder = str(self.home)
        calls = (
            (depth.COORDINATOR_ROLE, "--add-dir", folder), ("reviewer",), ("scout",),
            ("agent", "--name", f"{PREFIX}reviewer", "--fallback", "--host", "claude"),
        )

        # When
        with mock.patch.dict(os.environ, COORDINATOR_ENV):
            messages = []
            for arguments in calls:
                with self.assertRaises(config.UsageError) as raised:
                    self.plan(*arguments)
                messages.append(str(raised.exception))

        # Then
        self.assertTrue(all(message.startswith("Denied:") for message in messages), messages)

    def test_코디네이터는_worker_역할과_구현_에이전트를_시작할_수_있다(self):
        """코디네이터 환경에서 worker 역할과 worker 에이전트 이름의 러너 호출은 풀린다."""
        # Given
        folder = str(self.home)

        # When
        with mock.patch.dict(os.environ, COORDINATOR_ENV):
            worker = self.plan("worker", "--add-dir", folder)
            agent = self.plan("agent", "--name", "worker", "--fallback", "--host", "codex", "--add-dir", folder)

        # Then
        self.assertEqual((worker.role, agent.agent), ("worker", "worker"))

    def test_워커_층의_러너_호출은_워커_역할이어도_거부된다(self):
        """코디네이터가 시작한 자식은 러너로도 아무것도 시작하지 못한다."""
        # Given
        folder = str(self.home)

        # When
        with mock.patch.dict(os.environ, WORKER_ENV), self.assertRaises(config.UsageError) as raised:
            self.plan("worker", "--add-dir", folder)

        # Then
        self.assertIn("starts nothing", str(raised.exception))

    def test_코디네이터가_아닌_자식은_코디네이터를_시작하지_못한다(self):
        """계층 표시 없이 역할이나 부모 세션만 가진 자식도 area-coordinator 호출은 거부된다."""
        # Given
        child = {depth.ASSIGNED_ROLE_ENV: "worker", depth.PARENT_SESSION_ENV: f"claude:{MAIN_SESSION}"}

        # When
        with mock.patch.dict(os.environ, child), self.assertRaises(config.UsageError) as raised:
            self.plan(depth.COORDINATOR_ROLE, "--add-dir", str(self.home))

        # Then
        self.assertIn("only the main session starts an area coordinator", str(raised.exception))


class ChildEnvironmentTest(DepthCase):
    def test_러너는_코디네이터_자식에_계층과_서브에이전트_깊이_1을_주고_그_아래_자식은_워커_계층이다(self):
        """area-coordinator 자식은 coordinator 계층과 CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1을, 코디네이터가 시작한 자식은 worker 계층을 받는다."""
        # Given
        ordinary = role_runner_child.child_environment("worker")

        # When
        coordinator = role_runner_child.child_environment(depth.COORDINATOR_ROLE)
        with mock.patch.dict(os.environ, COORDINATOR_ENV):
            under = role_runner_child.child_environment("worker")

        # Then
        self.assertNotIn(depth.LAYER_ENV, ordinary)
        self.assertEqual(coordinator[depth.LAYER_ENV], depth.COORDINATOR)
        self.assertEqual(coordinator[role_runner_child.SUBAGENT_DEPTH_ENV], "1")
        self.assertEqual(under[depth.LAYER_ENV], depth.WORKER)
        self.assertNotIn(role_runner_child.SUBAGENT_DEPTH_ENV, under)


class CoordinatorRunTest(DepthCase):
    def test_코디네이터의_모델과_effort는_호스트별_상한_안_주력_모델의_high이고_등록_항목이_있으면_그것을_따른다(self):
        """Claude Code에서는 claude-opus-5-5 high, Codex에서는 gpt-6.1-sol high이며 레지스트리의 area_coordinator 항목이 우선한다."""
        # Given
        folder = str(self.home)
        registered = {"area_coordinator": {"claude": {"model": "claude-sonnet-5-5", "effort": "medium"}}}

        # When
        claude = self.plan(depth.COORDINATOR_ROLE, "--host", "claude", "--add-dir", folder)
        codex = self.plan(depth.COORDINATOR_ROLE, "--host", "codex", "--add-dir", folder)
        with mock.patch.dict(config.REGISTRY["runner"], registered):
            override = self.plan(depth.COORDINATOR_ROLE, "--host", "claude", "--add-dir", folder)

        # Then
        self.assertEqual((claude.model, claude.effort, claude.runner), ("claude-opus-5-5", "high", "claude"))
        self.assertEqual((codex.model, codex.effort, codex.runner), ("gpt-6.1-sol", "high", "codex"))
        self.assertEqual((override.model, override.effort), ("claude-sonnet-5-5", "medium"))

    def test_Claude_코디네이터는_Agent_도구를_받고_다른_쓰기_역할은_받지_않는다(self):
        """코디네이터의 claude 명령은 Agent와 Bash와 편집 규칙을 허용하고 worker 역할 명령에는 Agent가 없다."""
        # Given
        folder = str(self.home)
        coordinator = self.plan(depth.COORDINATOR_ROLE, "--host", "claude", "--add-dir", folder)
        worker = self.plan("worker", "--add-dir", folder)

        # When
        coordinator_tools = role_runner_command.claude_command(coordinator, folder)
        worker_tools = role_runner_command.claude_command(worker, folder)

        # Then
        tools = coordinator_tools[coordinator_tools.index("--tools") + 1 :]
        self.assertIn("Agent", tools[: tools.index("--strict-mcp-config")])
        self.assertIn("Bash", coordinator_tools)
        self.assertNotIn("Agent", worker_tools)

    def test_modelUsage는_코디네이터_모델에_구현_워커_모델이_더해질_때만_통과하고_워커_모델을_증거에_남긴다(self):
        """extra_models에 든 모델만 더 허용하고, 목록 밖 모델이나 코디네이터 모델이 없는 사용은 종료 코드 4이다."""
        # Given
        home = self.home / "claude"
        transcript = home / "projects" / "p" / "s1.jsonl"
        transcript.parent.mkdir(parents=True)
        entry = {"type": "assistant", "effort": "high", "message": {"model": "claude-opus-5-5"}}
        transcript.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        workers = frozenset({"claude-sonnet-5-5"})

        def result(*models: str) -> dict:
            return {"session_id": "s1", "modelUsage": {model: {} for model in models}}

        # When
        passed = evidence.verify_claude(result("claude-opus-5-5", "claude-sonnet-5-5"), "claude-opus-5-5", "high", extra_models=workers)
        errors = []
        for usage in (("claude-opus-5-5", "claude-haiku-5-5"), ("claude-sonnet-5-5",)):
            with self.assertRaises(config.RunnerError) as raised:
                evidence.verify_claude(result(*usage), "claude-opus-5-5", "high", extra_models=workers)
            errors.append(raised.exception.code)
        with self.assertRaises(config.RunnerError):
            evidence.verify_claude(result("claude-opus-5-5", "claude-sonnet-5-5"), "claude-opus-5-5", "high")

        # Then
        self.assertEqual(passed["worker_models"], ["claude-sonnet-5-5"])
        self.assertEqual(errors, [config.EXIT_EVIDENCE, config.EXIT_EVIDENCE])


if __name__ == "__main__":
    unittest.main()
