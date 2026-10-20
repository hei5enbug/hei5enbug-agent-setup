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
import plugin_toggles  # noqa: E402

PLUGIN_KEY = "hei5enbug-agent-setup@hei5enbug"
CODEX_DEFAULT = ("gpt-5.6-luna", "high")
CLAUDE_DEFAULT = ("claude-haiku-5-5", "high")


class WorkerSettingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.config = self.base / "claude config"
        self.config.mkdir()
        patcher = mock.patch.dict(
            os.environ,
            {"CLAUDE_CONFIG_DIR": str(self.config), "CODEX_HOME": str(self.base / "codex"), "HOME": str(self.base)},
            clear=True,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def save(self, options, key=PLUGIN_KEY):
        (self.config / "settings.json").write_text(
            json.dumps({"pluginConfigs": {key: {"options": options}}}), encoding="utf-8"
        )

    def resolve(self, host):
        model, effort, notice = plugin_toggles.worker_setting(host)
        return (model, effort), notice

    def test_Codex는_저장된_설정이_없으면_매니페스트_기본값을_알림_없이_쓴다(self):
        """settings.json이 없어도 기본 gpt-5.6-luna와 high를 돌려주고 알림은 없다."""
        # Given
        settings = self.config / "settings.json"

        # When
        pair, notice = self.resolve("codex")

        # Then
        self.assertFalse(settings.exists())
        self.assertEqual(CODEX_DEFAULT, pair)
        self.assertIsNone(notice)

    def test_Codex는_저장된_옵션의_모델과_effort를_쓴다(self):
        """pluginConfigs의 hei5enbug-agent-setup@ 항목에 저장된 gpt-6.1-sol과 high를 돌려준다."""
        # Given
        self.save({"codex_worker_model": "gpt-6.1-sol", "codex_worker_effort": "high", "agent_guard": True})

        # When
        pair, notice = self.resolve("codex")

        # Then
        self.assertEqual(("gpt-6.1-sol", "high"), pair)
        self.assertIsNone(notice)

    def test_Codex는_마켓플레이스_이름이_달라도_플러그인_접두사가_같으면_저장값을_쓴다(self):
        """키가 hei5enbug-agent-setup@로 시작하면 마켓플레이스 이름과 무관하게 읽는다."""
        # Given
        self.save({"codex_worker_effort": "high"}, key="hei5enbug-agent-setup@other-market")

        # When
        pair, notice = self.resolve("codex")

        # Then
        self.assertEqual(("gpt-5.6-luna", "high"), pair)
        self.assertIsNone(notice)

    def test_Codex는_환경_변수가_저장된_값보다_우선한다(self):
        """HEI5ENBUG_CODEX_WORKER_MODEL이 있으면 저장된 모델을 덮고, 없는 키는 저장된 값을 쓴다."""
        # Given
        self.save({"codex_worker_model": "gpt-6.1-sol", "codex_worker_effort": "high"})

        # When
        with mock.patch.dict(os.environ, {"HEI5ENBUG_CODEX_WORKER_MODEL": " GPT-5.6-Luna "}):
            pair, notice = self.resolve("codex")

        # Then
        self.assertEqual(("gpt-5.6-luna", "high"), pair)
        self.assertIsNone(notice)

    def test_Codex는_두_환경_변수가_있으면_설정_파일을_읽지_않는다(self):
        """두 키가 모두 환경 변수로 오면 깨진 settings.json이 있어도 알림 없이 그 값을 쓴다."""
        # Given
        (self.config / "settings.json").write_text("{broken", encoding="utf-8")
        env = {"HEI5ENBUG_CODEX_WORKER_MODEL": "gpt-6.1-sol", "HEI5ENBUG_CODEX_WORKER_EFFORT": "xhigh"}

        # When
        with mock.patch.dict(os.environ, env):
            pair, notice = self.resolve("codex")

        # Then
        self.assertEqual(("gpt-6.1-sol", "xhigh"), pair)
        self.assertIsNone(notice)

    def test_Codex는_목록에_없는_저장_모델이면_기본값과_값을_적은_알림을_돌려준다(self):
        """저장된 모델이 매니페스트 목록에 없으면 두 키 모두 기본값으로 되돌리고 무시한 값을 알림에 적는다."""
        # Given
        self.save({"codex_worker_model": "gpt-4.1-mini", "codex_worker_effort": "high"})

        # When
        pair, notice = self.resolve("codex")

        # Then
        self.assertEqual(CODEX_DEFAULT, pair)
        self.assertIn("codex_worker_model", notice)
        self.assertIn("gpt-4.1-mini", notice)

    def test_Codex는_목록에_없는_effort와_문자열이_아닌_값도_기본값으로_되돌린다(self):
        """medium은 Codex 목록에 없고 숫자 값은 문자열이 아니므로 둘 다 기본값과 알림이 된다."""
        # Given
        cases = [{"codex_worker_effort": "medium"}, {"codex_worker_model": 5}]

        for options in cases:
            with self.subTest(options=options):
                self.save(options)

                # When
                pair, notice = self.resolve("codex")

                # Then
                self.assertEqual(CODEX_DEFAULT, pair)
                self.assertIn(next(iter(options)), notice)

    def test_Codex는_깨진_설정_파일이면_기본값과_알림을_돌려준다(self):
        """settings.json이 JSON이 아니거나 pluginConfigs가 객체가 아니면 기본값과 알림을 돌려준다."""
        # Given
        contents = ["{broken", json.dumps({"pluginConfigs": ["x"]})]

        for text in contents:
            with self.subTest(text=text):
                (self.config / "settings.json").write_text(text, encoding="utf-8")

                # When
                pair, notice = self.resolve("codex")

                # Then
                self.assertEqual(CODEX_DEFAULT, pair)
                self.assertIn("Ignored", notice)

    def test_Codex는_설정_파일_자리에_디렉터리가_있으면_기본값과_알림을_돌려준다(self):
        """settings.json을 읽을 수 없으면 기본값과 알림을 돌려준다."""
        # Given
        (self.config / "settings.json").mkdir()

        # When
        pair, notice = self.resolve("codex")

        # Then
        self.assertEqual(CODEX_DEFAULT, pair)
        self.assertIn("unreadable", notice)

    def test_Codex는_환경_변수_하나만_있고_설정_파일이_깨져도_그_값을_유지하고_알림을_돌려준다(self):
        """모델만 환경 변수로 오고 settings.json이 깨졌으면 모델은 유지하고 effort만 기본값을 쓰며 무시 알림을 적는다."""
        # Given
        (self.config / "settings.json").write_text("{broken", encoding="utf-8")

        # When
        with mock.patch.dict(os.environ, {"HEI5ENBUG_CODEX_WORKER_MODEL": "gpt-6.1-sol"}):
            pair, notice = self.resolve("codex")

        # Then
        self.assertEqual(("gpt-6.1-sol", "high"), pair)
        self.assertIn("Ignored the saved worker settings", notice)

    def test_Claude는_역할_고정이_꺼져_있으면_설정값_대신_기본값과_알림을_돌려준다(self):
        """role_pinning이 꺼지면 설정한 쌍은 적용되지 않으므로 기본값과 역할 고정 알림을 돌려준다."""
        # Given
        env = {
            "CLAUDE_PLUGIN_OPTION_ROLE_PINNING": "false",
            "CLAUDE_PLUGIN_OPTION_WORKER_MODEL": "claude-opus-5-5",
            "CLAUDE_PLUGIN_OPTION_WORKER_EFFORT": "xhigh",
        }

        # When
        with mock.patch.dict(os.environ, env):
            pair, notice = self.resolve("claude")

        # Then
        self.assertEqual(CLAUDE_DEFAULT, pair)
        self.assertIn("role pinning is off", notice)

    def test_Codex는_역할_고정_옵션과_무관하게_설정값을_쓴다(self):
        """Claude의 role_pinning이 꺼져 있어도 Codex 쌍은 그대로 적용된다."""
        # Given
        env = {
            "CLAUDE_PLUGIN_OPTION_ROLE_PINNING": "false",
            "HEI5ENBUG_ROLE_PINNING": "false",
            "HEI5ENBUG_CODEX_WORKER_MODEL": "gpt-6.1-sol",
            "HEI5ENBUG_CODEX_WORKER_EFFORT": "high",
        }

        # When
        with mock.patch.dict(os.environ, env):
            pair, notice = self.resolve("codex")

        # Then
        self.assertEqual(("gpt-6.1-sol", "high"), pair)
        self.assertIsNone(notice)

    def test_설정_조회는_설정_파일을_쓰지_않는다(self):
        """저장된 값을 읽은 뒤에도 settings.json의 바이트가 그대로이고 새 파일이 생기지 않는다."""
        # Given
        self.save({"codex_worker_model": "gpt-6.1-sol"})
        path = self.config / "settings.json"
        before = path.read_bytes()

        # When
        self.resolve("codex")

        # Then
        self.assertEqual(before, path.read_bytes())
        self.assertEqual([path], list(self.config.iterdir()))

    def test_Claude는_옵션_환경_변수의_값을_쓴다(self):
        """CLAUDE_PLUGIN_OPTION_WORKER_MODEL과 WORKER_EFFORT를 돌려주고 저장된 파일은 읽지 않는다."""
        # Given
        self.save({"worker_model": "claude-opus-5-5"})
        env = {"CLAUDE_PLUGIN_OPTION_WORKER_MODEL": "claude-sonnet-5-5", "CLAUDE_PLUGIN_OPTION_WORKER_EFFORT": "max"}

        # When
        with mock.patch.dict(os.environ, env):
            pair, notice = self.resolve("claude")

        # Then
        self.assertEqual(("claude-sonnet-5-5", "max"), pair)
        self.assertIsNone(notice)

    def test_Claude는_옵션이_없으면_기본값을_알림_없이_쓴다(self):
        """환경 변수가 없거나 비어 있으면 claude-haiku-5-5와 high를 돌려준다."""
        # Given
        env = {"CLAUDE_PLUGIN_OPTION_WORKER_MODEL": "", "CLAUDE_PLUGIN_OPTION_WORKER_EFFORT": " "}

        # When
        with mock.patch.dict(os.environ, env):
            pair, notice = self.resolve("claude")

        # Then
        self.assertEqual(CLAUDE_DEFAULT, pair)
        self.assertIsNone(notice)

    def test_Claude는_목록에_없는_값이면_기본값과_알림을_돌려준다(self):
        """목록에 없는 effort는 기본값으로 되돌리고 무시한 값을 알림에 적는다."""
        # Given
        env = {"CLAUDE_PLUGIN_OPTION_WORKER_MODEL": "claude-opus-5-5", "CLAUDE_PLUGIN_OPTION_WORKER_EFFORT": "ultra"}

        # When
        with mock.patch.dict(os.environ, env):
            pair, notice = self.resolve("claude")

        # Then
        self.assertEqual(CLAUDE_DEFAULT, pair)
        self.assertIn("worker_effort", notice)
        self.assertIn("ultra", notice)

    def test_effort_규칙이_허용하지_않는_쌍은_기본값과_알림을_돌려준다(self):
        """레지스트리 effort_rules가 막는 모델과 effort 조합은 두 키 모두 기본값으로 되돌린다."""
        # Given
        rules = {"gpt-6.1-sol": ["high"]}
        registry = json.loads((REPO_ROOT / "config" / "model-registry.json").read_text(encoding="utf-8"))
        registry["effort_rules"] = {**registry["effort_rules"], **rules}
        env = {"HEI5ENBUG_CODEX_WORKER_MODEL": "gpt-6.1-sol", "HEI5ENBUG_CODEX_WORKER_EFFORT": "xhigh"}
        original = Path.read_text

        def read_text(path, *args, **kwargs):
            return json.dumps(registry) if path.name == "model-registry.json" else original(path, *args, **kwargs)

        # When
        with mock.patch.dict(os.environ, env), mock.patch.object(Path, "read_text", read_text):
            pair, notice = self.resolve("codex")

        # Then
        self.assertEqual(CODEX_DEFAULT, pair)
        self.assertIn("not allowed", notice)


if __name__ == "__main__":
    unittest.main()
