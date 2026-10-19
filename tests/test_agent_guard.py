from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD = REPO_ROOT / "scripts/agent_guard.py"
HOOKS = json.loads((REPO_ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]


class AgentGuardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.claude_home = self.base / "claude"
        self.codex_home = self.base / "codex"
        self.project = self.base / "project"
        self.project.mkdir()

    def decide(self, host: str, tool_input, event_name: str = "PreToolUse", **extra_env: str) -> str | None:
        output = self.output(host, tool_input, event_name, **extra_env)
        return None if output is None else output["permissionDecision"]

    def output(self, host: str, tool_input, event_name: str = "PreToolUse", **extra_env: str) -> dict | None:
        env = {"PATH": os.environ.get("PATH", ""), "CLAUDE_CONFIG_DIR": str(self.claude_home),
               "CODEX_HOME": str(self.codex_home), "CLAUDE_PROJECT_DIR": str(self.project), **extra_env}
        if host == "codex":
            env["PLUGIN_ROOT"] = str(REPO_ROOT)
        event = {"hook_event_name": event_name, "tool_name": "Agent", "cwd": str(self.project), "tool_input": tool_input}
        result = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event), env=env,
                                capture_output=True, text=True, check=True)
        if not result.stdout.strip():
            return None
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual("PreToolUse", output["hookEventName"])
        return output

    def write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_Claude에서는_어떤_에이전트_호출도_출력하지_않는다(self):
        """Claude의 내장 에이전트 차단은 Mod가 맡으므로 훅 스크립트는 내장·플러그인·사용자 에이전트와 빈 종류 모두에 출력이 없다."""
        # Given
        names = ("general-purpose", "Explore", "Plan", "claude", "fork", "claude-code-guide",
                 "hei5enbug-agent-setup:scout", "reviewer")

        # When
        decisions = {name: self.decide("claude", {"subagent_type": name, "prompt": "x"}) for name in names}
        omitted = self.decide("claude", {"prompt": "x"})

        # Then
        self.assertEqual({name: None for name in names}, decisions)
        self.assertIsNone(omitted)

    def test_Codex_내장_에이전트와_종류를_비운_호출은_거부한다(self):
        """default로 실행되는 빈 종류, default, explorer, 역할 파일이 없는 worker는 거부한다."""
        # Given
        self.write(self.codex_home / "agents" / "explorer.toml", 'name = "explorer"\n')

        # When
        decisions = [self.decide("codex", {"message": "x"})] + [
            self.decide("codex", {"agent_type": name, "message": "x"}) for name in ("default", "explorer", "worker", "scout")
        ]

        # Then
        self.assertEqual(["deny"] * 5, decisions)

    def test_Codex_설치_역할은_고정된_모델과_effort를_넘기면_허용하고_다른_쌍은_거부한다(self):
        """고정된 역할은 레지스트리의 모델과 effort를 넘기고, 정의만 있는 사용자 에이전트는 그대로 허용한다. 레지스트리와 다른 쌍을 넘긴 designer는 거부한다."""
        # Given
        self.write(self.codex_home / "agents" / "scout.toml", (REPO_ROOT / "standalone-agents/codex-scout.toml").read_text())
        self.write(self.codex_home / "agents" / "worker.toml", (REPO_ROOT / "standalone-agents/codex-worker.toml").read_text())
        self.write(self.codex_home / "agents" / "designer.toml", (REPO_ROOT / "standalone-agents/codex-designer.toml").read_text())
        self.write(
            self.codex_home / "agents" / "reviewer.toml",
            (REPO_ROOT / "standalone-agents/codex-reviewer.toml").read_text(),
        )
        self.write(self.project / ".codex" / "agents" / "pr-code-reviewer.toml", 'name = "pr_code_reviewer"\n')
        pinned = {
            "scout": ("gpt-5.6-luna", "xhigh"),
            "worker": ("gpt-5.6-luna", "xhigh"),
            "designer": ("gpt-6-astra", "xhigh"),
            "reviewer": ("gpt-6.1-sol", "xhigh"),
        }

        # When
        decisions = [
            self.decide("codex", {"agent_type": name, "model": pinned[name][0], "reasoning_effort": pinned[name][1]})
            for name in pinned
        ] + [
            self.decide("codex", {"agent_type": "pr_code_reviewer"}),
            self.decide("codex", {"agent_type": "designer", "model": "gpt-6.1-sol", "reasoning_effort": "medium"}),
        ]

        # Then
        self.assertEqual([None] * 5 + ["deny"], decisions)

    def test_Codex_토글이_꺼짐_값이면_내장_에이전트도_출력하지_않는다(self):
        """HEI5ENBUG_AGENT_GUARD가 false, 0, off, no(대소문자 무시)이면 거부 대상 호출에도 출력이 없다."""
        # Given
        values = ("false", "0", "off", "no", "OFF", "False")

        # When
        decisions = {value: self.decide("codex", {"agent_type": "default"}, HEI5ENBUG_AGENT_GUARD=value) for value in values}

        # Then
        self.assertEqual({value: None for value in values}, decisions)

    def test_Luna는_사용자가_고정한_버전과_high_또는_xhigh만_명시할_수_있다(self):
        """정의된 역할이 다른 Luna 버전이나 medium을 지정하면 거부하고 고정 모델의 high와 xhigh만 허용한다."""
        # Given
        self.write(self.codex_home / "agents" / "custom.toml", 'name = "custom"\n')
        inputs = [
            {"agent_type": "custom", "model": "gpt-6-luna", "reasoning_effort": "xhigh"},
            {"agent_type": "custom", "model": "gpt-5.6-luna", "reasoning_effort": "medium"},
            {"agent_type": "custom", "model": "gpt-5.6-luna", "reasoning_effort": "high"},
            {"agent_type": "custom", "model": "gpt-5.6-luna", "reasoning_effort": "xhigh"},
        ]

        # When
        decisions = [self.decide("codex", value) for value in inputs]

        # Then
        self.assertEqual(["deny", "deny", None, None], decisions)

    def test_Codex_고정된_역할은_레지스트리의_모델과_effort_쌍만_허용하고_나머지는_거부한다(self):
        """scout은 기본 쌍 gpt-5.6-luna와 xhigh만 허용하고, 레지스트리의 대체 쌍 claude-sonnet-5-5와 medium을 포함해 모델이나 effort를 빼거나 다른 쌍이면 거부하며, 거부 이유에 러너 대체 명령을 적는다."""
        # Given
        self.write(self.codex_home / "agents" / "scout.toml", 'name = "scout"\n')
        inputs = [
            {"agent_type": "scout"},
            {"agent_type": "scout", "model": "gpt-5.6-luna"},
            {"agent_type": "scout", "model": "gpt-5.6-luna", "reasoning_effort": "high"},
            {"agent_type": "scout", "model": "gpt-5.6-luna", "reasoning_effort": "xhigh"},
            {"agent_type": "scout", "model": "claude-sonnet-5-5", "reasoning_effort": "medium"},
            {"agent_type": "scout", "model": "gpt-6.1-sol", "reasoning_effort": "xhigh"},
        ]

        # When
        decisions = [self.decide("codex", value) for value in inputs]

        # Then
        self.assertEqual(["deny", "deny", "deny", None, "deny", "deny"], decisions)

    def test_Codex_선언된_역할_파일의_고정_쌍만_허용한다(self):
        """플러그인 캐시의 model-roles.json에 선언된 역할은 선언된 모델과 effort만 허용한다."""
        # Given
        self.write(self.codex_home / "agents" / "example_scout.toml", 'name = "example_scout"\n')
        self.write(
            self.codex_home / "plugins/cache/market/example-plugin/1.0.0/.codex-plugin/model-roles.json",
            json.dumps({"version": 1, "agents": {"example_scout": {"model": "gpt-6.1-sol", "effort": "xhigh"}}}),
        )

        # When
        allowed = self.decide("codex", {"agent_type": "example_scout", "model": "gpt-6.1-sol", "reasoning_effort": "xhigh"})
        denied = self.decide("codex", {"agent_type": "example_scout", "model": "gpt-6.1-sol", "reasoning_effort": "high"})

        # Then
        self.assertIsNone(allowed)
        self.assertEqual("deny", denied)

    def test_Codex_대체_쌍은_선언된_역할과_레지스트리_역할_모두_거부하고_러너_대체_명령을_알린다(self):
        """선언된 역할과 레지스트리 역할의 대체 쌍은 Codex에서 띄울 수 없으므로 거부하고, 거부 이유에 role_runner agent 대체 명령을 적는다."""
        # Given
        self.write(self.codex_home / "agents" / "example_scout.toml", 'name = "example_scout"\n')
        self.write(self.codex_home / "agents" / "scout.toml", (REPO_ROOT / "standalone-agents/codex-scout.toml").read_text())
        self.write(
            self.codex_home / "plugins/cache/market/example-plugin/1.0.0/.codex-plugin/model-roles.json",
            json.dumps({"version": 1, "agents": {"example_scout": {
                "model": "gpt-6.1-sol", "effort": "xhigh", "fallback": {"model": "claude-opus-5-5", "effort": "high"},
            }}}),
        )

        # When
        declared_primary = self.decide("codex", {"agent_type": "example_scout", "model": "gpt-6.1-sol", "reasoning_effort": "xhigh"})
        declared_fallback = self.output("codex", {"agent_type": "example_scout", "model": "claude-opus-5-5", "reasoning_effort": "high"})
        registry_fallback = self.output("codex", {"agent_type": "scout", "model": "claude-sonnet-5-5", "reasoning_effort": "medium"})

        # Then
        self.assertIsNone(declared_primary)
        self.assertEqual("deny", declared_fallback["permissionDecision"])
        self.assertIn(f"{REPO_ROOT}/scripts/role_runner.py agent --name example_scout --fallback", declared_fallback["permissionDecisionReason"])
        self.assertEqual("deny", registry_fallback["permissionDecision"])
        self.assertIn(f"{REPO_ROOT}/scripts/role_runner.py agent --name scout --fallback", registry_fallback["permissionDecisionReason"])

    def test_Codex_유효하지_않은_선언_파일은_그_역할을_모두_거부한다(self):
        """모델이 고정값이 아닌 선언 파일은 파일이 이름 붙인 역할을 모두 거부하고, 다른 역할은 영향받지 않는다."""
        # Given
        self.write(self.codex_home / "agents" / "example_scout.toml", 'name = "example_scout"\n')
        self.write(self.codex_home / "agents" / "example_worker.toml", 'name = "example_worker"\n')
        self.write(
            self.codex_home / "plugins/cache/market/example-plugin/1.0.0/.codex-plugin/model-roles.json",
            json.dumps({
                "version": 1,
                "agents": {
                    "example_scout": {"model": "gpt-6.1-sol", "effort": "xhigh"},
                    "example_worker": {"model": "gpt-4.1-mini", "effort": "xhigh"},
                },
            }),
        )

        # When
        scout = self.decide("codex", {"agent_type": "example_scout", "model": "gpt-6.1-sol", "reasoning_effort": "xhigh"})
        worker = self.decide("codex", {"agent_type": "example_worker", "model": "gpt-4.1-mini", "reasoning_effort": "xhigh"})
        custom = self.decide("codex", {"agent_type": "example_scout", "model": "gpt-6.1-sol"})

        # Then
        self.assertEqual("deny", scout)
        self.assertEqual("deny", worker)
        self.assertEqual("deny", custom)

    def test_Codex_레지스트리에_등록된_역할은_선언_파일이_고정값을_바꾸지_못한다(self):
        """worker는 레지스트리의 gpt-5.6-luna와 xhigh만 허용하고, 플러그인 선언이 다른 쌍을 주더라도 무시한다."""
        # Given
        self.write(self.codex_home / "agents" / "worker.toml", 'name = "worker"\n')
        self.write(
            self.codex_home / "plugins/cache/market/example-plugin/1.0.0/.codex-plugin/model-roles.json",
            json.dumps({"version": 1, "agents": {"worker": {"model": "gpt-6.1-sol", "effort": "high"}}}),
        )

        # When
        registry_pair = self.decide("codex", {"agent_type": "worker", "model": "gpt-5.6-luna", "reasoning_effort": "xhigh"})
        declared_pair = self.decide("codex", {"agent_type": "worker", "model": "gpt-6.1-sol", "reasoning_effort": "high"})

        # Then
        self.assertIsNone(registry_pair)
        self.assertEqual("deny", declared_pair)

    def test_Codex_읽을_수_없거나_JSON이_깨진_역할_파일이_있으면_선언되지_않은_역할도_거부하고_그_파일을_이유에_적는다(self):
        """파일이 깨지면 어떤 역할이 고정되어야 하는지 알 수 없으므로, 정의만 있는 역할도 거부하고 깨진 파일 경로를 이유에 적는다."""
        # Given
        self.write(self.codex_home / "agents" / "custom.toml", 'name = "custom"\n')
        broken = self.codex_home / "plugins/cache/market/broken-plugin/1.0.0/.codex-plugin/model-roles.json"
        self.write(broken, "{not json")

        # When
        output = self.output("codex", {"agent_type": "custom"})

        # Then
        self.assertEqual("deny", output["permissionDecision"])
        self.assertIn(f"`{broken}` is not valid JSON", output["permissionDecisionReason"])

    def test_Codex_구조가_맞지_않거나_읽을_수_없는_역할_파일이_여럿이면_모두_이유에_적는다(self):
        """버전이 다른 파일과 파일 자리에 디렉터리가 있어 읽을 수 없는 파일을 모두 이유에 적고, 등록되지 않은 역할을 거부한다."""
        # Given
        self.write(self.codex_home / "agents" / "custom.toml", 'name = "custom"\n')
        wrong_version = self.codex_home / "plugins/cache/market/wrong-version/1.0.0/.codex-plugin/model-roles.json"
        self.write(wrong_version, json.dumps({"version": 2, "agents": {}}))
        unreadable = self.codex_home / "plugins/cache/market/unreadable/1.0.0/.codex-plugin/model-roles.json"
        unreadable.mkdir(parents=True)

        # When
        output = self.output("codex", {"agent_type": "custom"})

        # Then
        self.assertEqual("deny", output["permissionDecision"])
        self.assertIn(f"`{wrong_version}` has no version 1 agents object", output["permissionDecisionReason"])
        self.assertIn(f"`{unreadable}` cannot be read", output["permissionDecisionReason"])

    def test_Codex_깨진_역할_파일이_있어도_레지스트리_역할은_자신의_고정_쌍으로만_판단하고_다른_파일의_선언도_거부한다(self):
        """깨진 파일이 있으면 다른 파일이 선언한 역할은 고정 쌍이 맞아도 거부하고, scout은 레지스트리의 쌍과 자체 검사만 따른다."""
        # Given
        self.write(self.codex_home / "agents" / "example_scout.toml", 'name = "example_scout"\n')
        self.write(self.codex_home / "agents" / "scout.toml", 'name = "scout"\n')
        self.write(
            self.codex_home / "plugins/cache/market/example-plugin/1.0.0/.codex-plugin/model-roles.json",
            json.dumps({"version": 1, "agents": {"example_scout": {"model": "gpt-6.1-sol", "effort": "xhigh"}}}),
        )
        self.write(self.codex_home / "plugins/cache/market/broken-plugin/1.0.0/.codex-plugin/model-roles.json", "{not json")

        # When
        declared = self.output("codex", {"agent_type": "example_scout", "model": "gpt-6.1-sol", "reasoning_effort": "xhigh"})
        registry = self.decide("codex", {"agent_type": "scout", "model": "gpt-5.6-luna", "reasoning_effort": "xhigh"})
        missing = self.output("codex", {"agent_type": "scout"})

        # Then
        self.assertEqual("deny", declared["permissionDecision"])
        self.assertIn("is not valid JSON", declared["permissionDecisionReason"])
        self.assertIsNone(registry)
        self.assertEqual("deny", missing["permissionDecision"])
        self.assertNotIn("unusable", missing["permissionDecisionReason"])

    def test_Codex_역할_파일이_모델이나_effort를_요청과_다르게_두면_그_파일을_이유에_적고_거부한다(self):
        """역할 파일이 model이나 model_reasoning_effort를 설정하면 설정된 값이 요청과 같아야 하고, 한쪽만 설정하면 그 값만 확인한다."""
        # Given
        role = self.codex_home / "agents" / "scout.toml"
        request = {"agent_type": "scout", "model": "gpt-5.6-luna", "reasoning_effort": "xhigh"}
        cases = [
            ('name = "scout"\nmodel = "gpt-6.1-sol"\n', "deny"),
            ('name = "scout"\nmodel_reasoning_effort = "high"\n', "deny"),
            ('name = "scout"\nmodel_reasoning_effort = "xhigh"\n', None),
            ('name = "scout"\nmodel = "gpt-5.6-luna"\nmodel_reasoning_effort = "xhigh"\n', None),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                # Given
                self.write(role, text)

                # When
                output = self.output("codex", request)

                # Then
                self.assertEqual(expected, None if output is None else output["permissionDecision"])
                if expected == "deny":
                    self.assertIn(str(role), output["permissionDecisionReason"])

    def test_Codex_캐시된_플러그인은_숫자로_가장_새_버전의_선언_파일만_읽는다(self):
        """같은 플러그인의 캐시 버전은 1.10.0이 1.9.0보다 새 버전이므로 1.9.0의 선언은 무시한다."""
        # Given
        self.write(self.codex_home / "agents" / "example_scout.toml", 'name = "example_scout"\n')
        self.write(
            self.codex_home / "plugins/cache/market/example-plugin/1.9.0/.codex-plugin/model-roles.json",
            json.dumps({"version": 1, "agents": {"example_scout": {"model": "gpt-6.1-sol", "effort": "xhigh"}}}),
        )
        self.write(
            self.codex_home / "plugins/cache/market/example-plugin/1.10.0/.codex-plugin/model-roles.json",
            json.dumps({"version": 1, "agents": {"example_linter": {"model": "gpt-6.1-sol", "effort": "high"}}}),
        )

        # When
        decision = self.decide("codex", {"agent_type": "example_scout", "model": "gpt-5.6-luna", "reasoning_effort": "high"})

        # Then
        self.assertIsNone(decision)

    def test_Codex_버전_이름이_숫자가_아니면_수정_시각이_가장_새_캐시만_읽는다(self):
        """버전 이름을 숫자로 읽을 수 없으면 수정 시각이 가장 새 캐시 디렉터리의 선언만 따른다."""
        # Given
        self.write(self.codex_home / "agents" / "example_scout.toml", 'name = "example_scout"\n')
        older = self.codex_home / "plugins/cache/market/example-plugin/nightly/.codex-plugin/model-roles.json"
        newer = self.codex_home / "plugins/cache/market/example-plugin/stable/.codex-plugin/model-roles.json"
        self.write(older, json.dumps({"version": 1, "agents": {"example_scout": {"model": "gpt-6.1-sol", "effort": "xhigh"}}}))
        self.write(newer, json.dumps({"version": 1, "agents": {"example_linter": {"model": "gpt-6.1-sol", "effort": "high"}}}))
        os.utime(older.parents[1], (1000, 1000))
        os.utime(newer.parents[1], (2000, 2000))

        # When
        decision = self.decide("codex", {"agent_type": "example_scout", "model": "gpt-5.6-luna", "reasoning_effort": "high"})

        # Then
        self.assertIsNone(decision)

    def test_Codex_토글이_비었거나_알_수_없는_값이면_계속_거부한다(self):
        """값이 없거나 빈 문자열이거나 인식할 수 없으면 기본값인 켜짐으로 읽는다."""
        # When
        decisions = [
            self.decide("codex", {"agent_type": "default"}),
            self.decide("codex", {"agent_type": "default"}, HEI5ENBUG_AGENT_GUARD=""),
            self.decide("codex", {"agent_type": "default"}, HEI5ENBUG_AGENT_GUARD="on"),
            self.decide("codex", {"agent_type": "default"}, HEI5ENBUG_AGENT_GUARD="maybe"),
        ]

        # Then
        self.assertEqual(["deny"] * 4, decisions)

    def test_Claude_옵션_환경_변수는_Codex_토글에_영향을_주지_않는다(self):
        """Codex 호스트는 CLAUDE_PLUGIN_OPTION_AGENT_GUARD를 읽지 않는다."""
        # When
        decision = self.decide("codex", {"agent_type": "default"}, CLAUDE_PLUGIN_OPTION_AGENT_GUARD="false")

        # Then
        self.assertEqual("deny", decision)

    def test_Agent_호출이_아니거나_입력을_해석할_수_없으면_막지_않는다(self):
        """다른 이벤트나 tool_input이 없는 입력은 판단하지 않고 그대로 통과시킨다."""
        # When
        other_event = self.decide("codex", {"agent_type": "default"}, event_name="PostToolUse")
        no_input = self.decide("codex", None)

        # Then
        self.assertIsNone(other_event)
        self.assertIsNone(no_input)

    def test_두_호스트의_Agent_호출_전에_가드_훅이_실행된다(self):
        """PreToolUse 훅은 Claude의 Agent·Task와 Codex의 spawn_agent를 잡는 Agent 매처로 가드를 실행한다."""
        # When
        entries = [
            (group["matcher"], hook["command"])
            for group in HOOKS["PreToolUse"]
            for hook in group["hooks"]
            if "agent_guard.py" in hook["command"]
        ]

        # Then
        self.assertEqual([("Agent|Task", 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/hook_python.sh" agent_guard.py')], entries)


if __name__ == "__main__":
    unittest.main()
