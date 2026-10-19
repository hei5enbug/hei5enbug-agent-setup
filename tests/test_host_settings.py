from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import approval_state  # noqa: E402
import host_settings  # noqa: E402
import plugin_toggles  # noqa: E402

FAKE_CODEX = """#!{python}
import os, sys
from pathlib import Path

home = Path(os.environ["CODEX_HOME"])
with (home / "codex-calls.log").open("a") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
if sys.argv[1:3] == ["features", "list"]:
    print("{listed}")
elif sys.argv[1:3] == ["features", "enable"]:
    config = home / "config.toml"
    config.write_text(config.read_text().replace("plugin_hooks = false", "plugin_hooks = true"))
"""
USER_RULES = """# user rules
prefix_rule(pattern=["helm", "list"], decision="allow")
prefix_rule(pattern=["kubectl", "get"], decision="prompt", justification="decision = \\"forbidden\\" in text")
prefix_rule(
    pattern = [["az", "/opt/homebrew/bin/az"], "vm", "list"],
    decision = "forbidden",
    justification = "keep",
)
prefix_rule(pattern=["git", ["status", "log"]], decision="prompt")
prefix_rule(pattern=["kubectl", "apply"], decision="prompt")
prefix_rule(pattern=["az", "keyvault"], decision="forbidden")
prefix_rule(pattern=["az", "account", "get-access-token"], decision="prompt")
prefix_rule(pattern=["kubectl", "describe"], decision="allow")
# prefix_rule(pattern=["helm", "status"], decision="prompt")
prefix_rule(pattern=[["env", "sudo"], ["az"], "list"], decision="forbidden")
"""
CONFIG = """# user config
approval_policy = "on-request"

[features]
plugin_hooks = false
other_feature = true

[mcp_servers.datagrip]
command = "datagrip-mcp"
default_tools_approval_mode = "approve"

[mcp_servers.datagrip.tools.execute_sql_query]
approval_mode = "prompt"

[mcp_servers.other]
command = "other-mcp"
"""


def snapshot(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


class HostSettingsTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.claude = self.base / "claude"
        self.codex = self.base / "codex"
        self.project = self.base / "project"
        self.state = self.base / "state"
        self.bin = self.base / "bin"
        for directory in (self.claude, self.codex, self.project, self.bin):
            directory.mkdir()
        environ = mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.state), "HOME": str(self.base / "home")})
        environ.start()
        self.addCleanup(environ.stop)
        for name in list(os.environ):
            if name in {"CLAUDE_CONFIG_DIR", "CODEX_HOME", "CLAUDE_PROJECT_DIR", "PLUGIN_ROOT"} or name.startswith(
                ("HEI5ENBUG_", "CLAUDE_PLUGIN_OPTION_")
            ):
                del os.environ[name]
        self.hooks = self.base / "hooks.json"
        self.hooks.write_text('{"hooks": {}}\n', encoding="utf-8")
        hooks = mock.patch.object(approval_state, "HOOKS_PATH", self.hooks)
        hooks.start()
        self.addCleanup(hooks.stop)
        native = mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", False)
        native.start()
        self.addCleanup(native.stop)
        self.confirm_hooks()

    def confirm_hooks(self, digest=None):
        directory = self.state / "hei5enbug-agent-setup" / "heartbeats"
        directory.mkdir(parents=True, exist_ok=True)
        value = digest or hashlib.sha256(self.hooks.read_bytes()).hexdigest()
        (directory / "confirmed-codex").write_text(value + "\n", encoding="utf-8")

    def write(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_json(self, path: Path, value) -> Path:
        return self.write(path, json.dumps(value))

    def fake_codex(self, listed="plugin_hooks  stable  false") -> str:
        path = self.bin / "codex"
        path.write_text(FAKE_CODEX.format(python=sys.executable, listed=listed), encoding="utf-8")
        path.chmod(0o755)
        return str(path)

    def check(self, host="codex"):
        return host_settings.check(host, self.claude, self.codex, self.project)

    def ids(self, host="codex"):
        return [problem.id for problem in self.check(host)]

    def apply(self, host="codex", **kwargs):
        return host_settings.apply(host, self.claude, self.codex, **kwargs)

    def backups(self, name):
        return sorted(path.name for path in self.codex.rglob(f"{name}.bak-hei5enbug-*"))


class CheckTest(HostSettingsTestCase):
    def test_Claude_dontAsk는_사용자_프로젝트_로컬_순서로_실제_적용되는_값만_보고한다(self):
        """사용자 설정의 dontAsk도 보고하고, 로컬 설정이 default로 덮으면 보고하지 않는다."""
        # given
        self.write_json(self.claude / "settings.json", {"permissions": {"defaultMode": "dontAsk"}})

        # when
        user_only = self.ids("claude")
        self.write_json(self.project / ".claude/settings.local.json", {"permissions": {"defaultMode": "default"}})
        overridden = self.ids("claude")

        # then
        self.assertEqual(user_only, ["claude-dontask"])
        self.assertEqual(overridden, [])

    def test_프로젝트와_로컬의_dontAsk를_보고하고_한_줄은_120자_미만이다(self):
        """프로젝트 설정과 로컬 설정의 dontAsk도 보고하며 모든 출력 줄은 120자 미만이다."""
        for name in ("settings.json", "settings.local.json"):
            with self.subTest(name=name):
                # given
                self.write_json(self.project / ".claude" / name, {"permissions": {"defaultMode": "dontAsk"}})

                # when
                problems = self.check("claude")

                # then
                self.assertEqual([problem.id for problem in problems], ["claude-dontask"])
                self.assertTrue(all(len(problem.text) < 120 for problem in problems))
                (self.project / ".claude" / name).unlink()

    def test_Claude_ask_규칙은_Bash와_mcp만_최대_세_개_이름으로_보고한다(self):
        """Bash와 mcp ask 규칙만 세 개까지 이름을 대고, 긴 이름도 줄이 120자 미만이다."""
        # given
        self.write_json(self.claude / "settings.json", {"permissions": {"ask": [
            "Bash(git diff:*)", "Read(*)", "mcp__server__tool", "Bash", "mcp__fourth__tool",
        ]}})
        self.write_json(self.project / ".claude/settings.local.json", {"permissions": {"ask": [
            "Bash(" + "x" * 80 + ")",
        ]}})

        # when
        problems = self.check("claude")

        # then
        self.assertEqual([problem.id for problem in problems], ["claude-ask-rules"])
        text = problems[0].text
        self.assertTrue(text.startswith(host_settings.ASK_RULES_MESSAGE))
        self.assertIn("Bash(git diff:*)", text)
        self.assertIn("mcp__server__tool", text)
        self.assertNotIn("Read(*)", text)
        self.assertNotIn("mcp__fourth__tool", text)
        self.assertLess(len(text), 120)

    def test_Claude_호스트는_Codex_설정_파일이_없으면_Codex_항목을_보고하지_않는다(self):
        """Codex 설정이 없고 Claude 설정이 정상이면 아무 문제도 보고하지 않는다."""
        # given
        self.write_json(self.claude / "settings.json", {"permissions": {"defaultMode": "acceptEdits", "ask": ["Read(*)"]}})

        # when
        problems = self.check("claude")

        # then
        self.assertEqual(problems, [])

    def test_Codex_plugin_hooks가_true가_아니면_Claude와_Codex_호스트_모두_보고한다(self):
        """plugin_hooks가 false이거나 features 표가 없으면 보고하고, true이거나 설정 파일이 없으면 보고하지 않는다."""
        for text, expected in [
            ("[features]\nplugin_hooks = false\n", ["codex-plugin-hooks"]),
            ("[features]\nother = true\n", ["codex-plugin-hooks"]),
            ("approval_policy = \"never\"\n", ["codex-plugin-hooks"]),
            ("[features]\nplugin_hooks = true\n", []),
        ]:
            for host in ("claude", "codex"):
                with self.subTest(text=text, host=host):
                    # given
                    self.write(self.codex / "config.toml", text)

                    # when
                    result = self.ids(host)

                    # then
                    self.assertEqual(result, expected)
        (self.codex / "config.toml").unlink()
        self.assertEqual(self.ids("codex"), [])

    def test_Codex_설정이_TOML이_아니면_Codex_호스트만_보고한다(self):
        """읽을 수 없는 config.toml은 Codex 호스트에서만 한 줄로 보고한다."""
        # given
        self.write(self.codex / "config.toml", "[features\nplugin_hooks = true\n")

        # when
        codex = self.ids("codex")
        claude = self.ids("claude")

        # then
        self.assertEqual(codex, ["codex-config-invalid"])
        self.assertEqual(claude, [])

    def test_Codex_훅_신뢰는_heartbeat_해시가_없거나_다르면_보고한다(self):
        """확인된 해시가 없거나 훅 파일과 다르면 보고하고, 같으면 보고하지 않으며 훅 파일이 없으면 판단하지 않는다."""
        # given
        confirmed = self.state / "hei5enbug-agent-setup" / "heartbeats" / "confirmed-codex"

        # when
        matching = self.ids()
        self.confirm_hooks("0" * 64)
        different = self.ids()
        confirmed.unlink()
        missing = self.ids()
        self.confirm_hooks()
        self.hooks.unlink()
        unreadable = self.ids()

        # then
        self.assertEqual(matching, [])
        self.assertEqual(different, ["codex-hooks-trust"])
        self.assertEqual(missing, ["codex-hooks-trust"])
        self.assertEqual(unreadable, [])
        self.assertEqual(self.ids("claude"), [])

    def test_규칙_파일과_MCP_모드는_네이티브_승인이_켜졌을_때만_점검한다(self):
        """없는 규칙 파일, 구버전 규칙 파일, prompt가 아닌 MCP 모드는 기능이 켜졌을 때만 보고한다."""
        # given
        self.write(self.codex / "config.toml", CONFIG.replace("plugin_hooks = false", "plugin_hooks = true"))
        rules = self.codex / "rules" / host_settings.RULES_NAME

        for flag, expected_missing in ((False, []), (True, ["codex-rules-file", "codex-mcp-mode"])):
            with self.subTest(flag=flag), mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", flag):
                # when
                missing = [i for i in self.ids() if i in {"codex-rules-file", "codex-mcp-mode"}]

                # then
                self.assertEqual(missing, expected_missing)

        with mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", True):
            # when
            self.write(rules, host_settings.OWNER_MARK + ": stale\n")
            outdated = self.check()
            self.write(rules, host_settings.rules_text(host_settings.ROOT))
            current = [p.id for p in self.check()]

            # then
            self.assertIn("codex-rules-file", [p.id for p in outdated])
            self.assertIn("outdated", next(p.text for p in outdated if p.id == "codex-rules-file"))
            self.assertNotIn("codex-rules-file", current)
            self.assertIn("codex-mcp-mode", current)
            self.assertTrue(all(len(p.text) < 120 for p in outdated))

    def test_MCP_모드가_prompt이면_네이티브_승인에서_보고하지_않는다(self):
        """가드가 분류하는 서버의 default_tools_approval_mode가 prompt이고 규칙 파일이 최신이면 문제가 없다."""
        # given
        self.write(self.codex / "config.toml",
                   '[features]\nplugin_hooks = true\n[mcp_servers.datagrip]\ndefault_tools_approval_mode = "prompt"\n'
                   '[mcp_servers.tabularis]\ncommand = "x"\n')
        self.write(self.codex / "rules" / host_settings.RULES_NAME, host_settings.rules_text(host_settings.ROOT))

        # when
        with mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", True):
            problems = self.check()

        # then
        self.assertEqual([(p.id, "tabularis" in p.text) for p in problems], [("codex-mcp-mode", True)])

    def test_다른_규칙_파일의_조회_접두_prompt와_forbidden_규칙을_앞_단어로_보고한다(self):
        """사용자 규칙 파일에서 조회 접두를 막는 규칙만 앞 단어로 보고하고 파일은 바꾸지 않는다."""
        # given
        rules = self.write(self.codex / "rules" / "default.rules", USER_RULES)
        self.write(self.codex / "rules" / host_settings.RULES_NAME,
                   'prefix_rule(pattern=["git", "status"], decision="prompt")\n')
        before = snapshot(self.codex)

        # when
        problems = [p for p in self.check() if p.id == "codex-user-rule"]

        # then
        texts = [p.text for p in problems]
        self.assertEqual(len(texts), 3, texts)
        self.assertIn('"kubectl get"', texts[0])
        self.assertIn("prompt", texts[0])
        self.assertIn('"az vm list"', texts[1])
        self.assertIn("forbidden", texts[1])
        self.assertIn('"git status|log"', texts[2])
        self.assertTrue(all(len(text) < 120 and "default.rules" in text for text in texts))
        self.assertEqual(snapshot(self.codex), before)
        self.assertTrue(rules.is_file())

    def test_네이티브_승인이_꺼져_있으면_가드_서버의_prompt_도구를_보고한다(self):
        """기능이 꺼져 있을 때만 가드 서버 도구의 approval_mode prompt를 이름과 함께 보고한다."""
        # given
        self.write(self.codex / "config.toml", CONFIG.replace("plugin_hooks = false", "plugin_hooks = true"))

        for flag, expected in ((False, ["codex-mcp-tool-prompt"]), (True, [])):
            with self.subTest(flag=flag), mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", flag):
                # when
                found = [p for p in self.check() if p.id == "codex-mcp-tool-prompt"]

                # then
                self.assertEqual([p.id for p in found], expected)
                if found:
                    self.assertIn("datagrip", found[0].text)
                    self.assertIn("execute_sql_query", found[0].text)
                    self.assertLess(len(found[0].text), 120)

    def test_옵션_host_settings는_report만_report이고_나머지는_apply이다(self):
        """옵션이 없거나 알 수 없는 값이면 apply이고, report는 대소문자와 공백을 무시한다."""
        for value, expected in [(None, "apply"), ("", "apply"), ("apply", "apply"), ("bogus", "apply"),
                                (" Report ", "report"), ("report", "report")]:
            with self.subTest(value=value):
                # given
                env = {} if value is None else {"CLAUDE_PLUGIN_OPTION_HOST_SETTINGS": value}

                # when
                with mock.patch.dict(os.environ, env):
                    mode = plugin_toggles.host_settings_mode()

                # then
                self.assertEqual(mode, expected)

    def test_매니페스트는_host_settings_옵션을_apply_기본으로_선언한다(self):
        """플러그인 옵션 host_settings는 문자열이며 기본값 apply와 report 선택지를 가진다."""
        # given
        manifest = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))

        # when
        option = manifest["userConfig"]["host_settings"]

        # then
        self.assertEqual((option["type"], option["default"]), ("string", "apply"))
        self.assertEqual(option["options"], ["apply", "report"])
        self.assertTrue(option["description"].startswith("apply: at session start, back up and fix"))


class RulesTextTest(unittest.TestCase):
    def test_규칙_파일_본문은_래퍼_경로_prompt_규칙과_머리글_주석을_가진다(self):
        """플러그인 소유 규칙 파일은 머리글 주석 뒤에 래퍼 경로 prompt 규칙 한 줄을 둔다."""
        # given
        root = Path("/opt/plugin root")

        # when
        text = host_settings.rules_text(root)

        # then
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("# hei5enbug-agent-setup plugin-owned file"))
        self.assertEqual(
            lines[-1],
            'prefix_rule(pattern=["/opt/plugin root/scripts/approve_wrapper.sh"], decision="prompt", '
            'justification="hei5enbug: approve writes once for this session")',
        )


class ApplyTest(HostSettingsTestCase):
    def test_Claude_호스트의_apply는_아무것도_바꾸지_않고_그렇다고_알린다(self):
        """Claude 호스트에서는 설정 파일이 있어도 변경 없이 알림만 반환한다."""
        # given
        self.write_json(self.claude / "settings.json", {"permissions": {"defaultMode": "dontAsk"}})
        self.write(self.codex / "config.toml", CONFIG)
        self.write(self.codex / "rules" / "default.rules", USER_RULES)
        before = snapshot(self.base)

        # when
        for flag in (False, True):
            with mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", flag):
                result = self.apply("claude", codex_bin=self.fake_codex())

        # then
        self.assertEqual(result.changes, [])
        self.assertIn("Claude Code host", result.notes[0])
        after = snapshot(self.base)
        after.pop("bin/codex")
        self.assertEqual(after, before)

    def test_plugin_hooks는_codex_features_목록에_있을_때만_그_CLI로_켜고_백업한다(self):
        """features list에 plugin_hooks가 있으면 CLI로 켜고 백업을 남기며, 두 번째 실행은 아무것도 바꾸지 않는다."""
        # given
        self.write(self.codex / "config.toml", CONFIG)
        original = (self.codex / "config.toml").read_bytes()
        codex = self.fake_codex()

        # when
        first = self.apply(codex_bin=codex)
        after_first = snapshot(self.codex)
        second = self.apply(codex_bin=codex)

        # then
        self.assertEqual([change.label for change in first.changes], ["plugin_hooks"])
        self.assertEqual(second.changes, [])
        self.assertEqual(snapshot(self.codex), after_first)
        backups = self.backups("config.toml")
        self.assertEqual(len(backups), 1)
        self.assertRegex(backups[0], r"^config\.toml\.bak-hei5enbug-\d{8}$")
        self.assertEqual((self.codex / backups[0]).read_bytes(), original)
        self.assertEqual(
            (self.codex / "config.toml").read_text(),
            CONFIG.replace("plugin_hooks = false", "plugin_hooks = true"),
        )
        calls = (self.codex / "codex-calls.log").read_text().splitlines()
        self.assertEqual(calls, ["features list", "features enable plugin_hooks"])

    def test_features_목록에_plugin_hooks가_없거나_CLI가_없으면_보고만_한다(self):
        """CLI 목록에 기능이 없거나 CLI를 실행할 수 없으면 설정 파일과 백업을 만들지 않고 알린다."""
        # given
        self.write(self.codex / "config.toml", CONFIG)
        before = snapshot(self.codex)

        for codex in (self.fake_codex(listed="other_feature  stable  false"), str(self.bin / "missing-codex")):
            with self.subTest(codex=codex):
                # when
                result = self.apply(codex_bin=codex)

                # then
                self.assertEqual(result.changes, [])
                self.assertIn("plugin_hooks", result.notes[0])
                after = snapshot(self.codex)
                after.pop("codex-calls.log", None)
                self.assertEqual(after, before)

    def test_기능이_꺼져_있으면_규칙_파일과_MCP_모드를_건드리지_않는다(self):
        """네이티브 승인이 꺼져 있으면 apply는 plugin_hooks 외에는 아무것도 쓰지 않는다."""
        # given
        self.write(self.codex / "config.toml", CONFIG.replace("plugin_hooks = false", "plugin_hooks = true"))
        before = snapshot(self.codex)

        # when
        with mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", False):
            result = self.apply(codex_bin=self.fake_codex())

        # then
        self.assertEqual(result.changes, [])
        self.assertEqual(snapshot(self.codex), before)
        self.assertFalse((self.codex / "rules").exists())

    def test_기능이_켜져_있으면_규칙_파일과_MCP_모드를_허용_목록_안에서만_바꾼다(self):
        """규칙 파일을 만들고 모든 MCP 서버 표의 키 한 줄만 바꾸며, 나머지 줄은 그대로이고 두 번째 실행은 무변경이다."""
        # given
        enabled = CONFIG.replace("plugin_hooks = false", "plugin_hooks = true")
        self.write(self.codex / "config.toml", enabled)
        codex = self.fake_codex()

        with mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", True):
            # when
            first = self.apply(codex_bin=codex)
            after_first = snapshot(self.codex)
            second = self.apply(codex_bin=codex)

        # then
        self.assertEqual([c.label for c in first.changes], [f"rules/{host_settings.RULES_NAME}", "mcp datagrip", "mcp other"])
        self.assertEqual(second.changes, [])
        self.assertEqual(snapshot(self.codex), after_first)
        new = (self.codex / "config.toml").read_text()
        expected = [line.replace('"approve"', '"prompt"') for line in enabled.splitlines()]
        expected.insert(expected.index("[mcp_servers.other]") + 1, 'default_tools_approval_mode = "prompt"')
        self.assertEqual(new.splitlines(), expected)
        self.assertNotIn("tabularis", new)
        self.assertEqual(
            (self.codex / "rules" / host_settings.RULES_NAME).read_text(),
            host_settings.rules_text(host_settings.ROOT),
        )
        self.assertEqual(len(self.backups("config.toml")), 1)
        self.assertEqual(self.backups(host_settings.RULES_NAME), [])
        self.assertEqual(
            sorted(path for path in snapshot(self.codex) if ".bak-" not in path),
            ["config.toml", f"rules/{host_settings.RULES_NAME}"],
        )

    def test_키가_없으면_표_머리글_바로_아래에_넣고_두_서버를_모두_처리한다(self):
        """모드 키가 없는 datagrip과 tabularis 표에 한 줄씩 넣고 다른 서버와 줄은 그대로 둔다."""
        # given
        text = (
            '[features]\nplugin_hooks = true\n\n[mcp_servers."datagrip"] # note\ncommand = "a"\n\n'
            "[mcp_servers.tabularis]\r\ncommand = 'b'\r\n\r\n[mcp_servers.keep]\ncommand = \"c\"\n"
        )
        self.write(self.codex / "config.toml", text)
        original_bytes = (self.codex / "config.toml").read_bytes()

        # when
        with mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", True):
            result = self.apply(codex_bin=self.fake_codex())

        # then
        self.assertEqual(
            [c.label for c in result.changes],
            [f"rules/{host_settings.RULES_NAME}", "mcp datagrip", "mcp tabularis", "mcp keep"],
        )
        new = (self.codex / "config.toml").read_bytes()
        parsed = tomllib.loads(new.decode())
        self.assertEqual(parsed["mcp_servers"]["datagrip"], {"command": "a", host_settings.PROMPT_MODE: "prompt"})
        self.assertEqual(parsed["mcp_servers"]["tabularis"], {"command": "b", host_settings.PROMPT_MODE: "prompt"})
        self.assertEqual(parsed["mcp_servers"]["keep"], {"command": "c", host_settings.PROMPT_MODE: "prompt"})
        self.assertEqual(len(new.splitlines()), len(original_bytes.splitlines()) + 3)
        self.assertIn(b'tabularis]\r\ndefault_tools_approval_mode = "prompt"\r\n', new)

    def test_이미_있는_규칙_파일이_다르면_백업_후_갱신하고_같은_날_백업은_덮지_않는다(self):
        """구버전 규칙 파일은 백업한 뒤 새 내용으로 바꾸고, 같은 날 백업이 이미 있으면 그대로 둔다."""
        # given
        self.write(self.codex / "config.toml", "[features]\nplugin_hooks = true\n")
        rules = self.write(self.codex / "rules" / host_settings.RULES_NAME, host_settings.OWNER_MARK + ": old rules\n")
        existing = self.write(self.codex / "rules" / f"{host_settings.RULES_NAME}.bak-hei5enbug-{host_settings._today()}", "first backup\n")

        # when
        with mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", True):
            result = self.apply(codex_bin=self.fake_codex())

        # then
        self.assertEqual([c.label for c in result.changes], [f"rules/{host_settings.RULES_NAME}"])
        self.assertEqual(rules.read_text(), host_settings.rules_text(host_settings.ROOT))
        self.assertEqual(existing.read_text(), "first backup\n")

    def test_소유_표시가_없는_hei5enbug_규칙_파일은_덮어쓰지_않고_알린다(self):
        """사용자가 만든 hei5enbug.rules는 소유 표시가 없으면 apply가 쓰지도 백업하지도 않는다."""
        # given
        self.write(self.codex / "config.toml", "[features]\nplugin_hooks = true\n")
        rules = self.write(self.codex / "rules" / host_settings.RULES_NAME, USER_RULES)

        # when
        with mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", True):
            result = self.apply(codex_bin=self.fake_codex())
            problems = self.check()

        # then
        self.assertEqual(rules.read_text(), USER_RULES)
        self.assertEqual(self.backups(host_settings.RULES_NAME), [])
        self.assertEqual([c.label for c in result.changes], [])
        self.assertTrue(any("not plugin-owned" in note for note in result.notes))
        self.assertIn("not plugin-owned", next(p.text for p in problems if p.id == "codex-rules-file"))

    def test_규칙_파일이_심볼릭_링크이면_따라가지_않고_대상을_그대로_둔다(self):
        """hei5enbug.rules가 default.rules를 가리켜도 apply는 링크도 대상도 쓰지 않는다."""
        # given
        self.write(self.codex / "config.toml", "[features]\nplugin_hooks = true\n")
        target = self.write(self.codex / "rules" / "default.rules", USER_RULES)
        link = self.codex / "rules" / host_settings.RULES_NAME
        link.symlink_to(target)

        # when
        with mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", True):
            result = self.apply(codex_bin=self.fake_codex())

        # then
        self.assertTrue(link.is_symlink())
        self.assertEqual(target.read_text(), USER_RULES)
        self.assertEqual([c.label for c in result.changes], [])
        self.assertTrue(any("symbolic link" in note for note in result.notes))
        self.assertEqual(self.backups("default.rules"), [])

    def test_끊어진_심볼릭_링크도_따라가_만들지_않는다(self):
        """없는 대상을 가리키는 hei5enbug.rules 링크도 apply가 대상 파일을 새로 만들지 않는다."""
        # given
        self.write(self.codex / "config.toml", "[features]\nplugin_hooks = true\n")
        (self.codex / "rules").mkdir(parents=True, exist_ok=True)
        missing = self.codex / "rules" / "elsewhere.rules"
        (self.codex / "rules" / host_settings.RULES_NAME).symlink_to(missing)

        # when
        with mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", True):
            result = self.apply(codex_bin=self.fake_codex())

        # then
        self.assertFalse(missing.exists())
        self.assertEqual([c.label for c in result.changes], [])

    def test_다른_규칙_파일은_apply가_건드리지_않는다(self):
        """사용자 소유 rules 파일은 문제가 있어도 apply 뒤에 바이트까지 그대로다."""
        # given
        self.write(self.codex / "config.toml", "[features]\nplugin_hooks = true\n")
        rules = self.write(self.codex / "rules" / "default.rules", USER_RULES)

        # when
        with mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", True):
            self.apply(codex_bin=self.fake_codex())

        # then
        self.assertEqual(rules.read_text(), USER_RULES)
        self.assertEqual(self.backups("default.rules"), [])

    def test_config_toml이_파싱되지_않으면_아무것도_쓰지_않고_알린다(self):
        """TOML 오류가 있으면 config.toml을 쓰거나 백업하지 않는다. 규칙 파일 쓰기는 별개로 한다."""
        # given
        broken = "[features\nplugin_hooks = false\n[mcp_servers.datagrip]\n"
        self.write(self.codex / "config.toml", broken)

        for flag in (False, True):
            with self.subTest(flag=flag), mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", flag):
                # when
                result = self.apply(codex_bin=self.fake_codex())

                # then
                self.assertEqual([c.label for c in result.changes], [f"rules/{host_settings.RULES_NAME}"] if flag else [])
                self.assertTrue(any("not valid TOML" in note for note in result.notes))
                self.assertEqual((self.codex / "config.toml").read_text(), broken)
                self.assertEqual(self.backups("config.toml"), [])
                self.assertFalse((self.codex / "codex-calls.log").exists())

    def test_줄_편집이_TOML을_깨면_아무것도_쓰지_않는다(self):
        """여러 줄 문자열 값을 첫 줄만 바꾸면 파싱이 달라지므로 쓰지 않고 알린다."""
        # given
        text = '[features]\nplugin_hooks = true\n[mcp_servers.datagrip]\ndefault_tools_approval_mode = """\napprove"""\n'
        self.write(self.codex / "config.toml", text)

        # when
        with mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", True):
            result = self.apply(codex_bin=self.fake_codex())

        # then
        self.assertEqual([c.label for c in result.changes], [f"rules/{host_settings.RULES_NAME}"])
        self.assertTrue(any("wrote nothing" in note for note in result.notes))
        self.assertEqual((self.codex / "config.toml").read_text(), text)
        self.assertEqual(self.backups("config.toml"), [])

    def test_평범한_표_머리글이_없는_서버는_쓰지_않고_알린다(self):
        """인라인 표로 선언된 서버는 줄 편집이 불가능하므로 쓰지 않고 알리며, 서버를 추가하지도 않는다."""
        # given
        text = '[features]\nplugin_hooks = true\n[mcp_servers]\ndatagrip = { command = "x" }\n'
        self.write(self.codex / "config.toml", text)

        # when
        with mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", True):
            result = self.apply(codex_bin=self.fake_codex())

        # then
        self.assertTrue(any("plain table header" in note for note in result.notes))
        self.assertEqual((self.codex / "config.toml").read_text(), text)

    def test_서버_표가_없으면_서버를_만들지_않는다(self):
        """MCP 서버 표가 없는 설정에는 규칙 파일만 만들고 config.toml은 그대로 둔다."""
        # given
        text = '[features]\nplugin_hooks = true\n[other]\ncommand = "x"\n'
        self.write(self.codex / "config.toml", text)

        # when
        with mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", True):
            result = self.apply(codex_bin=self.fake_codex())

        # then
        self.assertEqual([c.label for c in result.changes], [f"rules/{host_settings.RULES_NAME}"])
        self.assertEqual((self.codex / "config.toml").read_text(), text)

    def test_기본값은_네이티브_승인이_켜진_상태이다(self):
        """모듈 기본값은 True이고 다른 테스트는 setUp에서 끈 채로 시작한다."""
        # given
        source = (host_settings.ROOT / "scripts" / "host_settings.py").read_text(encoding="utf-8")

        # then
        self.assertIn("\nCODEX_NATIVE_APPROVAL = True\n", source)

    def test_도구별_approval_mode는_이미_있는_줄만_prompt로_바꾸고_줄을_새로_만들지_않는다(self):
        """모든 서버의 도구 표 approval_mode 줄만 바꾸고 다른 도구 표는 그대로이며 두 번째 실행은 무변경이다."""
        # given
        text = (
            '[features]\nplugin_hooks = true\n\n[mcp_servers.alpha]\ncommand = "a"\ndefault_tools_approval_mode = "prompt"\n\n'
            '[mcp_servers.alpha.tools.read_it]\napproval_mode = "approve"\n\n'
            '[mcp_servers.alpha.tools.keep_it]\nenabled = true\n\n'
            '[mcp_servers."beta"]\ncommand = "b"\n\n[mcp_servers."beta".tools."write-it"]\n  approval_mode = "auto"  # mine\n'
        )
        self.write(self.codex / "config.toml", text)
        codex = self.fake_codex()

        with mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", True):
            # when
            first = self.apply(codex_bin=codex)
            after_first = snapshot(self.codex)
            second = self.apply(codex_bin=codex)

        # then
        self.assertEqual(
            [c.label for c in first.changes],
            [f"rules/{host_settings.RULES_NAME}", "mcp alpha.read_it", "mcp beta", "mcp beta.write-it"],
        )
        self.assertEqual(second.changes, [])
        self.assertEqual(snapshot(self.codex), after_first)
        parsed = tomllib.loads((self.codex / "config.toml").read_text())
        alpha, beta = parsed["mcp_servers"]["alpha"], parsed["mcp_servers"]["beta"]
        self.assertEqual(alpha["tools"]["read_it"], {"approval_mode": "prompt"})
        self.assertEqual(alpha["tools"]["keep_it"], {"enabled": True})
        self.assertEqual(beta[host_settings.PROMPT_MODE], "prompt")
        self.assertEqual(beta["tools"]["write-it"], {"approval_mode": "prompt"})
        self.assertEqual(len((self.codex / "config.toml").read_text().splitlines()), len(text.splitlines()) + 1)
        self.assertEqual(len(self.backups("config.toml")), 1)

    def test_approval_guard가_꺼져_있으면_MCP_모드를_건드리지_않고_점검이_이유를_보고한다(self):
        """토글이 꺼지면 apply는 규칙 파일만 쓰고 config.toml을 그대로 두며, check는 건너뛴 이유를 보고한다."""
        # given
        text = CONFIG.replace("plugin_hooks = false", "plugin_hooks = true")
        self.write(self.codex / "config.toml", text)
        name = plugin_toggles.variable_name("approval_guard", plugin_toggles.detect_host())

        with mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", True), mock.patch.dict(os.environ, {name: "off"}):
            # when
            result = self.apply(codex_bin=self.fake_codex())
            problems = {p.id: p.text for p in self.check()}

        # then
        self.assertEqual([c.label for c in result.changes], [f"rules/{host_settings.RULES_NAME}"])
        self.assertEqual((self.codex / "config.toml").read_text(), text)
        self.assertEqual(self.backups("config.toml"), [])
        self.assertIn("approval_guard", problems["codex-mcp-skipped"])
        self.assertNotIn("codex-mcp-mode", problems)

    def test_점검은_prompt가_아닌_모든_서버를_세_개까지_이름으로_보고한다(self):
        """가드 서버가 아니어도 default 모드나 도구 모드가 prompt가 아니면 한 줄로 보고한다."""
        # given
        self.write(self.codex / "config.toml",
                   '[features]\nplugin_hooks = true\n[mcp_servers.a]\ncommand = "x"\n[mcp_servers.b]\ncommand = "x"\n'
                   '[mcp_servers.c]\ncommand = "x"\n[mcp_servers.d]\ncommand = "x"\n'
                   '[mcp_servers.e]\ndefault_tools_approval_mode = "prompt"\n[mcp_servers.e.tools.t]\napproval_mode = "approve"\n')
        self.write(self.codex / "rules" / host_settings.RULES_NAME, host_settings.rules_text(host_settings.ROOT))

        # when
        with mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", True):
            problems = [p for p in self.check() if p.id == "codex-mcp-mode"]

        # then
        self.assertEqual(len(problems), 1)
        self.assertIn("a, b, c", problems[0].text)
        self.assertIn("+2 more", problems[0].text)
        self.assertLess(len(problems[0].text), 120)


class CommandLineTest(HostSettingsTestCase):
    def run_main(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = host_settings.main(list(arguments))
        return code, out.getvalue(), err.getvalue()

    def test_check는_문제만_한_줄씩_출력하고_문제가_있어도_종료_코드_0이다(self):
        """문제가 없으면 출력이 없고, 있으면 줄마다 하나씩 출력하며 종료 코드는 0이다."""
        # given
        args = ("check", "--host", "claude", "--claude-dir", str(self.claude), "--codex-home", str(self.codex))

        # when
        clean = self.run_main(*args)
        self.write_json(self.claude / "settings.json", {"permissions": {"defaultMode": "dontAsk", "ask": ["Bash(ls:*)"]}})
        problem = self.run_main(*args)

        # then
        self.assertEqual(clean, (0, "", ""))
        self.assertEqual(problem[0], 0)
        lines = problem[1].splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(len(line) < 120 for line in lines))

    def test_check_json은_호스트와_문제_목록을_출력한다(self):
        """--json은 호스트와 문제 id와 메시지를 한 객체로 출력한다."""
        # given
        self.write(self.codex / "config.toml", "[features]\nplugin_hooks = false\n")

        # when
        code, out, _ = self.run_main("check", "--host", "codex", "--codex-home", str(self.codex), "--json")

        # then
        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(payload["host"], "codex")
        self.assertEqual([p["id"] for p in payload["problems"]], ["codex-plugin-hooks"])

    def test_잘못된_인자는_종료_코드_2이다(self):
        """알 수 없는 명령, 호스트, 옵션과 명령 누락은 종료 코드 2이다."""
        for arguments in (("bogus",), ("check", "--host", "other"), ("check", "--nope"), ()):
            with self.subTest(arguments=arguments):
                # when
                code, _, _ = self.run_main(*arguments)

                # then
                self.assertEqual(code, 2)

    def test_apply_출력은_변경마다_한_줄이고_Claude_호스트는_무변경을_알린다(self):
        """Codex는 변경 한 줄씩 출력하고 두 번째 실행은 출력이 없으며, Claude 호스트는 변경 없음을 알린다."""
        # given
        self.write(self.codex / "config.toml", CONFIG)
        args = ("apply", "--host", "codex", "--codex-home", str(self.codex), "--codex-bin", self.fake_codex())

        # when
        first = self.run_main(*args)
        second = self.run_main(*args)
        claude = self.run_main("apply", "--host", "claude", "--codex-home", str(self.codex))

        # then
        self.assertEqual(first[0], 0)
        self.assertEqual(len(first[1].splitlines()), 1)
        self.assertEqual(second, (0, "", ""))
        self.assertEqual(claude[0], 0)
        self.assertIn("changes no settings", claude[1])

    def test_입출력_실패는_종료_코드_1이다(self):
        """설정 파일 쓰기가 실패하면 파이썬 오류 대신 한 줄과 종료 코드 1을 낸다."""
        # given
        self.write(self.codex / "config.toml", "[features]\nplugin_hooks = true\n")

        # when
        with mock.patch.object(host_settings, "CODEX_NATIVE_APPROVAL", True), mock.patch.object(
            host_settings, "_write", side_effect=PermissionError("denied")
        ):
            code, out, err = self.run_main("apply", "--host", "codex", "--codex-home", str(self.codex))

        # then
        self.assertEqual((code, out), (1, ""))
        self.assertIn("denied", err)

    def test_스크립트로_직접_실행해도_check가_동작한다(self):
        """python3 scripts/host_settings.py check를 격리된 환경에서 실행하면 문제를 출력한다."""
        # given
        self.write(self.codex / "config.toml", "[features]\nplugin_hooks = false\n")
        env = {"PATH": os.environ["PATH"], "HOME": str(self.base / "home"), "XDG_STATE_HOME": str(self.state)}

        # when
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "host_settings.py"), "check", "--host", "claude",
             "--claude-dir", str(self.claude), "--codex-home", str(self.codex)],
            env=env, text=True, capture_output=True, timeout=20, cwd=self.project,
        )

        # then
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("plugin_hooks = true", result.stdout)


if __name__ == "__main__":
    unittest.main()
