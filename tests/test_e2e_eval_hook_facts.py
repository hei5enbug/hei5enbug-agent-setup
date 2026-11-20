"""Unit tests for the informational hook facts of a run: the replay of recorded tool calls and the Claude Code stream counts."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))

from harness import hook_facts, records  # noqa: E402

DENY = json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                          "permissionDecisionReason": "no /Users/demo/secret.txt for demo"}})


def write_plugin(root: Path, hooks: dict) -> Path:
    (root / "hooks").mkdir(parents=True)
    (root / "hooks" / "hooks.json").write_text(json.dumps({"hooks": hooks}), encoding="utf-8")
    return root


def command_hook(command: str, matcher: str | None = None) -> list[dict]:
    entry = {"hooks": [{"type": "command", "command": command}]}
    return [{**entry, "matcher": matcher} if matcher else entry]


class HookFactsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)

    def test_재생은_도구에_맞는_훅만_실행하고_시간과_가장_느린_훅을_센다(self):
        """Bash 호출 두 개와 Read 호출 하나를 보내면 Bash 훅은 두 번, Read 훅은 한 번 돈다."""
        # given
        plugin = write_plugin(self.root / "plugin", {
            "PreToolUse": command_hook("cat >/dev/null; echo one", "^Bash$") + command_hook("cat >/dev/null; echo two", "^Read$"),
            "Stop": command_hook("echo never")})
        calls = [{"name": "Bash", "input": {"command": "ls"}, "id": "1"}, {"name": "Bash", "input": {}, "id": "2"},
                 {"name": "Read", "input": {}, "id": "3"}]

        # when
        facts = hook_facts.replay(plugin, "claude", calls, self.root)

        # then
        self.assertEqual((facts["replayed_hooks"], facts["replay_denials"], facts["replay_total_seconds"] >= 0), (3, [], True))
        self.assertTrue(facts["replay_slowest"].startswith("PreToolUse:"))

    def test_거부_결정은_이유와_함께_기록되고_절대_경로는_가려진다(self):
        """훅이 deny를 출력하면 도구와 이유가 남고 이유 안의 절대 경로는 <path>가 된다."""
        # given
        plugin = write_plugin(self.root / "plugin", {"PreToolUse": command_hook(f"cat >/dev/null; echo '{DENY}'")})

        # when
        facts = hook_facts.replay(plugin, "claude", [{"name": "Bash", "input": {}, "id": "1"}], self.root)

        # then
        self.assertEqual([(d["tool"], d["reason"]) for d in facts["replay_denials"]], [("Bash", "no <path> for demo")])

    def test_스트림의_훅_응답은_개수_실패_거부로_센다(self):
        """success가 아닌 outcome은 실패이고, deny 출력은 거부다."""
        # given
        events = [{"type": "system", "subtype": "hook_response", "hook_name": "PreToolUse:Bash", "output": "", "outcome": "success"},
                  {"type": "system", "subtype": "hook_response", "hook_name": "PreToolUse:Bash", "output": DENY, "outcome": "success"},
                  {"type": "system", "subtype": "hook_response", "hook_name": "Stop", "output": "", "outcome": "error"},
                  {"type": "assistant"}]

        # when
        facts = hook_facts.stream_hook_facts(events)

        # then
        self.assertEqual((facts["stream_hook_responses"], facts["stream_hook_failures"], len(facts["stream_denials"])), (3, 1, 1))

    def test_기록의_hooks_필드는_객체만_허용한다(self):
        """run 항목의 hooks는 선택 필드이고 객체가 아니면 검증이 실패한다."""
        run = {"case": "T1", "variant": "a", "host": "claude", "models": {"main": {"model": "claude-opus-5-5", "effort": "high"}},
               "checks": {"x": True}, "wall_seconds": 1.0, "cost_usd": 0.1}
        good = records.run_problems("runs[0]", {**run, "hooks": {"replayed_hooks": 1}}, ["T1"], {"a": {}})
        bad = records.run_problems("runs[0]", {**run, "hooks": 3}, ["T1"], {"a": {}})
        self.assertEqual((good, bad), ([], ["runs[0] hooks is not an object"]))

    def test_Codex_재생의_worker_생성은_Codex로_평가되고_agent_type_worker로_읽힌다(self):
        """Codex 재생의 spawn_agent는 agent_type과 message로 가드에 가고, worker 짝이 아닌 모델은 worker 이름으로 거부된다."""
        # given
        codex_home = self.root / "codex-home"
        (codex_home / "agents").mkdir(parents=True)
        (codex_home / "agents" / "worker.toml").write_text('name = "worker"\n', encoding="utf-8")
        calls = [{"name": "spawn_agent", "id": "1", "input": {"subagent_type": "worker", "prompt": "작업", "task_name": "w1",
                                                              "model": "claude-opus-5-5", "reasoning_effort": "high"}}]
        env = {"CODEX_HOME": str(codex_home), "HEI5ENBUG_CODEX_WORKER_MODEL": "auto", "HEI5ENBUG_CODEX_WORKER_EFFORT": "high"}

        # when
        facts = hook_facts.replay(REPO_ROOT, "codex", calls, self.root, env)

        # then
        self.assertEqual([(d["hook"], d["tool"]) for d in facts["replay_denials"]], [("PreToolUse:agent_guard.py", "Agent")])
        self.assertIn("`worker` assignments must use", facts["replay_denials"][0]["reason"])

    def test_호스트_환경은_Codex에만_PLUGIN_ROOT를_두고_Claude에서는_상속된_값을_지운다(self):
        """Codex 재생은 PLUGIN_ROOT와 CLAUDE_PLUGIN_ROOT를 함께 주고, Claude Code 재생은 상속된 PLUGIN_ROOT를 남기지 않는다."""
        # given
        inherited = {"PLUGIN_ROOT": "/inherited"}

        # when
        with mock.patch.dict(os.environ, inherited):
            codex = hook_facts.host_environment(self.root, "codex", None)
            claude = hook_facts.host_environment(self.root, "claude", None)

        # then
        self.assertEqual((codex["PLUGIN_ROOT"], codex["CLAUDE_PLUGIN_ROOT"]), (str(self.root), str(self.root)))
        self.assertEqual((claude.get("PLUGIN_ROOT"), claude["CLAUDE_PLUGIN_ROOT"]), (None, str(self.root)))


if __name__ == "__main__":
    unittest.main()
