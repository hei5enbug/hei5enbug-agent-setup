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
        return output["permissionDecision"]

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

    def test_Codex_연구원을_포함한_설치_역할은_허용한다(self):
        """researcher와 설치된 역할 파일이 있는 사용자 에이전트는 훅에서 허용한다."""
        # Given
        self.write(self.codex_home / "agents" / "scout.toml", (REPO_ROOT / "standalone-agents/codex-scout.toml").read_text())
        self.write(self.codex_home / "agents" / "worker.toml", (REPO_ROOT / "standalone-agents/codex-worker.toml").read_text())
        self.write(self.codex_home / "agents" / "researcher.toml", (REPO_ROOT / "standalone-agents/codex-researcher.toml").read_text())
        self.write(self.project / ".codex" / "agents" / "pr-code-reviewer.toml", 'name = "pr_code_reviewer"\n')
        self.write(self.project / ".codex" / "agents" / "reviewer.toml", "name = 'reviewer'\ndescription = 'r'\n")

        # When
        decisions = [
            self.decide("codex", {"agent_type": name})
            for name in ("scout", "worker", "researcher", "pr_code_reviewer", "reviewer")
        ]

        # Then
        self.assertEqual([None] * 5, decisions)

    def test_Codex_토글이_꺼짐_값이면_내장_에이전트도_출력하지_않는다(self):
        """HEI5ENBUG_AGENT_GUARD가 false, 0, off, no(대소문자 무시)이면 거부 대상 호출에도 출력이 없다."""
        # Given
        values = ("false", "0", "off", "no", "OFF", "False")

        # When
        decisions = {value: self.decide("codex", {"agent_type": "default"}, HEI5ENBUG_AGENT_GUARD=value) for value in values}

        # Then
        self.assertEqual({value: None for value in values}, decisions)

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
        self.assertEqual([("Agent|Task", 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/agent_guard.py"')], entries)


if __name__ == "__main__":
    unittest.main()
