"""Unit tests for the informational hook facts of a run: the replay of recorded tool calls and the Claude Code stream counts."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
