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

    def decide(self, host: str, tool_input, event_name: str = "PreToolUse") -> str | None:
        env = {"PATH": os.environ.get("PATH", ""), "CLAUDE_CONFIG_DIR": str(self.claude_home),
               "CODEX_HOME": str(self.codex_home), "CLAUDE_PROJECT_DIR": str(self.project)}
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

    def test_Claude_내장_에이전트와_종류를_비운_호출은_거부한다(self):
        """정의 파일이 없는 내장 이름과 general-purpose로 실행되는 빈 종류는 모두 거부한다."""
        # Given
        built_ins = ("general-purpose", "Explore", "explore", "Plan", "claude", "fork")

        # When
        decisions = {name: self.decide("claude", {"subagent_type": name, "prompt": "x"}) for name in built_ins}
        omitted = self.decide("claude", {"prompt": "x"})

        # Then
        self.assertEqual({name: "deny" for name in built_ins}, decisions)
        self.assertEqual("deny", omitted)

    def test_Claude_범위가_좁은_내장_에이전트는_대소문자와_관계없이_허용한다(self):
        """claude-code-guide와 statusline-setup은 scout나 worker와 겹치지 않으므로 이름의 대소문자와 상관없이 막지 않는다."""
        # Given
        names = ("claude-code-guide", "Claude-Code-Guide", "statusline-setup", "StatusLine-Setup")

        # When
        decisions = {name: self.decide("claude", {"subagent_type": name, "prompt": "x"}) for name in names}

        # Then
        self.assertEqual({name: None for name in names}, decisions)

    def test_Claude_플러그인과_사용자_정의_에이전트는_허용한다(self):
        """플러그인 이름공간 에이전트와 사용자·프로젝트 파일, CLI나 관리 설정처럼 훅이 볼 수 없는 정의도 막지 않는다."""
        # Given
        self.write(self.claude_home / "agents" / "reviewer.md", "---\nname: reviewer\ndescription: r\n---\nbody\n")
        self.write(self.project / ".claude" / "agents" / "nested" / "local.md", "---\nname: 'local-helper'\n---\n")

        # When
        allowed = [
            self.decide("claude", {"subagent_type": "hei5enbug-agent-setup:scout"}),
            self.decide("claude", {"subagent_type": "tradlinx-agent-setup:pr-review-gate-reader"}),
            self.decide("claude", {"subagent_type": "reviewer"}),
            self.decide("claude", {"subagent_type": "local-helper"}),
            self.decide("claude", {"subagent_type": "cli-defined-reviewer"}),
        ]

        # Then
        self.assertEqual([None] * 5, allowed)

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

    def test_Codex_설치된_역할_파일이_있는_에이전트는_허용한다(self):
        """훅이 설치한 scout와 worker, 파일 이름과 다른 name이나 작은따옴표 name을 가진 사용자 역할은 허용한다."""
        # Given
        self.write(self.codex_home / "agents" / "scout.toml", (REPO_ROOT / "standalone-agents/codex-scout.toml").read_text())
        self.write(self.codex_home / "agents" / "worker.toml", (REPO_ROOT / "standalone-agents/codex-worker.toml").read_text())
        self.write(self.project / ".codex" / "agents" / "pr-code-reviewer.toml", 'name = "pr_code_reviewer"\n')
        self.write(self.project / ".codex" / "agents" / "reviewer.toml", "name = 'reviewer'\ndescription = 'r'\n")

        # When
        decisions = [self.decide("codex", {"agent_type": name}) for name in ("scout", "worker", "pr_code_reviewer", "reviewer")]

        # Then
        self.assertEqual([None] * 4, decisions)

    def test_Agent_호출이_아니거나_입력을_해석할_수_없으면_막지_않는다(self):
        """다른 이벤트나 tool_input이 없는 입력은 판단하지 않고 그대로 통과시킨다."""
        # When
        other_event = self.decide("claude", {"subagent_type": "general-purpose"}, event_name="PostToolUse")
        no_input = self.decide("claude", None)

        # Then
        self.assertIsNone(other_event)
        self.assertIsNone(no_input)

    def test_두_호스트의_Agent_호출_전에_가드_훅이_실행된다(self):
        """PreToolUse 훅은 Claude의 Agent·Task와 Codex의 spawn_agent를 잡는 Agent 매처로 가드를 실행한다."""
        # When
        entries = [(group["matcher"], hook["command"]) for group in HOOKS["PreToolUse"] for hook in group["hooks"]]

        # Then
        self.assertEqual([("Agent|Task", 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/agent_guard.py"')], entries)


if __name__ == "__main__":
    unittest.main()
