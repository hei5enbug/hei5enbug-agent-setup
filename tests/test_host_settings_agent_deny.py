from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_host_settings import HostSettingsTestCase, host_settings, snapshot  # noqa: E402

DENIES = ["Agent(general-purpose)", "Agent(Explore)", "Agent(Plan)", "Agent(claude)"]


class AgentDenyTest(HostSettingsTestCase):
    def setUp(self):
        super().setUp()
        del os.environ["CLAUDE_PLUGIN_OPTION_AGENT_GUARD"]
        self.settings = self.claude / "settings.json"

    def deny(self):
        return json.loads(self.settings.read_text(encoding="utf-8"))["permissions"]["deny"]

    def test_check는_네_항목이_없으면_보고하고_모두_있으면_보고하지_않는다(self):
        """사용자 설정에 Agent 거부 규칙이 하나라도 없으면 claude-agent-deny를 한 줄로 보고하고 쓰지 않는다."""
        # given
        self.write_json(self.settings, {"permissions": {"deny": ["Agent(Plan)", "Bash(rm:*)"]}})
        before = snapshot(self.base)

        # when
        problems = [p for p in self.check("claude") if p.id == "claude-agent-deny"]
        self.write_json(self.settings, {"permissions": {"deny": DENIES}})

        # then
        self.assertEqual(len(problems), 1)
        self.assertIn("Agent(general-purpose), Agent(Explore), Agent(claude)", problems[0].text)
        self.assertLessEqual(len(problems[0].text), host_settings.MAX_LINE)
        self.assertNotIn("claude-agent-deny", self.ids("claude"))
        self.assertNotEqual(snapshot(self.base), before)

    def test_check는_설정_파일이_없어도_보고하고_agent_guard가_꺼지면_보고하지_않는다(self):
        """파일이 없으면 네 항목 모두 없는 것으로 보고하고, agent_guard가 off이면 점검에서 뺀다."""
        # given / when
        missing = self.ids("claude")
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_OPTION_AGENT_GUARD": "off"}):
            off = self.ids("claude")

        # then
        self.assertIn("claude-agent-deny", missing)
        self.assertNotIn("claude-agent-deny", off)

    def test_Codex_호스트의_check는_Agent_거부_규칙을_보고하지_않는다(self):
        """Claude 사용자 설정 규칙은 Claude 호스트에서만 점검한다."""
        self.assertNotIn("claude-agent-deny", self.ids("codex"))

    def test_apply는_빠진_네_항목만_기존_항목_뒤에_더하고_다른_키와_순서를_그대로_둔다(self):
        """기존 deny 항목, 순서, 다른 키와 들여쓰기를 유지하고 빠진 항목만 뒤에 붙이며 같은 날 백업을 만든다."""
        # given
        original = '{\n    "model": "opus",\n    "permissions": {\n        "allow": ["Bash(ls:*)"],\n        "deny": ["Agent(Plan)", "Read(.env)"]\n    },\n    "z": 1\n}\n'
        self.write(self.settings, original)

        # when
        result = self.apply("claude")

        # then
        data = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(data["permissions"]["deny"], ["Agent(Plan)", "Read(.env)", "Agent(general-purpose)", "Agent(Explore)", "Agent(claude)"])
        self.assertEqual(list(data), ["model", "permissions", "z"])
        self.assertEqual(data["permissions"]["allow"], ["Bash(ls:*)"])
        self.assertTrue(self.settings.read_text(encoding="utf-8").startswith('{\n    "model"'))
        backups = sorted(path.name for path in self.claude.glob("settings.json.bak-hei5enbug-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((self.claude / backups[0]).read_text(encoding="utf-8"), original)
        self.assertEqual([change.label for change in result.changes], ["claude agent deny rules"])
        self.assertNotIn("claude-agent-deny", self.ids("claude"))

    def test_apply는_두_번째_실행에서_아무것도_바꾸지_않는다(self):
        """이미 네 항목이 있으면 파일 바이트와 백업이 그대로이고 변경 목록이 비어 있다."""
        # given
        self.write_json(self.settings, {"permissions": {"deny": ["Read(.env)"]}})
        self.apply("claude")
        before = snapshot(self.base)

        # when
        result = self.apply("claude")

        # then
        self.assertEqual(result.changes, [])
        self.assertEqual(snapshot(self.base), before)
        self.assertEqual(self.deny(), ["Read(.env)", *DENIES])

    def test_apply는_파일이나_permissions가_없으면_만들고_백업은_만들지_않는다(self):
        """설정 파일이 없을 때는 네 항목만 가진 파일을 만들고, permissions만 없을 때는 다른 키를 지키며 더한다."""
        # given / when
        self.apply("claude")

        # then
        self.assertEqual(self.deny(), DENIES)
        self.assertEqual(list(self.claude.glob("settings.json.bak-*")), [])

        # given
        self.write_json(self.settings, {"theme": "dark"})

        # when
        self.apply("claude")

        # then
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8"))["theme"], "dark")
        self.assertEqual(self.deny(), DENIES)

    def test_apply는_CLAUDE_CONFIG_DIR을_따른다(self):
        """claude_dir 인자가 없으면 CLAUDE_CONFIG_DIR의 settings.json을 쓴다."""
        # given
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.claude)}):
            # when
            host_settings.apply("claude")

        # then
        self.assertEqual(self.deny(), DENIES)

    def test_apply는_agent_guard가_꺼져_있으면_쓰지_않는다(self):
        """agent_guard 토글이 off이면 설정 파일을 만들지도 바꾸지도 않는다."""
        # given
        self.write_json(self.settings, {"permissions": {"deny": []}})
        before = snapshot(self.base)

        # when
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_OPTION_AGENT_GUARD": "false"}):
            result = self.apply("claude")

        # then
        self.assertEqual(result.changes, [])
        self.assertEqual(snapshot(self.base), before)

    def test_apply는_해석할_수_없는_설정을_건드리지_않고_알린다(self):
        """JSON이 아니거나 객체가 아니거나 deny가 목록이 아니면 아무것도 쓰지 않고 한 줄로 알린다."""
        for text in ("{not json", "[]", '{"permissions": {"deny": "Agent(Plan)"}}', '{"permissions": []}'):
            with self.subTest(text=text):
                # given
                self.write(self.settings, text)
                before = snapshot(self.base)

                # when
                result = self.apply("claude")

                # then
                self.assertEqual(result.changes, [])
                self.assertEqual(len(result.notes), 1)
                self.assertEqual(snapshot(self.base), before)

    def test_apply_출력은_변경_한_줄이고_Codex_호스트는_Claude_설정을_건드리지_않는다(self):
        """Codex 호스트의 apply는 Claude 사용자 설정을 만들거나 바꾸지 않는다."""
        # given
        self.write_json(self.settings, {"permissions": {"deny": []}})
        before = self.settings.read_bytes()

        # when
        result = self.apply("codex")

        # then
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertNotIn("claude agent deny rules", [change.label for change in result.changes])
