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
CODEX_DEFAULT = ("auto", "high")
CLAUDE_DEFAULT = "high"


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

    def resolve(self):
        model, effort, notice = plugin_toggles.worker_setting()
        return (model, effort), notice

    def test_Codex는_저장된_설정이_없으면_매니페스트_기본값을_알림_없이_쓴다(self):
        """settings.json이 없어도 기본 gpt-6-luna와 high를 돌려주고 알림은 없다."""
        # Given
        settings = self.config / "settings.json"

        # When
        pair, notice = self.resolve()

        # Then
        self.assertFalse(settings.exists())
        self.assertEqual(CODEX_DEFAULT, pair)
        self.assertIsNone(notice)

    def test_Codex는_저장된_옵션의_모델과_effort를_쓴다(self):
        """pluginConfigs의 hei5enbug-agent-setup@ 항목에 저장된 gpt-6.2-sol과 high를 돌려준다."""
        # Given
        self.save({"codex_worker_model": "gpt-6.2-sol", "codex_worker_effort": "high", "agent_guard": True})

        # When
        pair, notice = self.resolve()

        # Then
        self.assertEqual(("gpt-6.2-sol", "high"), pair)
        self.assertIsNone(notice)

    def test_Codex는_terra와_xhigh_쌍을_알림_없이_돌려준다(self):
        """저장된 gpt-6.1-terra와 xhigh는 목록에 있으므로 그대로 돌려준다."""
        # Given
        self.save({"codex_worker_model": "gpt-6.1-terra", "codex_worker_effort": "xhigh"})

        # When
        pair, notice = self.resolve()

        # Then
        self.assertEqual(("gpt-6.1-terra", "xhigh"), pair)
        self.assertIsNone(notice)

    def test_Codex는_terra와_목록_밖_medium_쌍이면_기본값과_알림을_돌려준다(self):
        """terra에 목록 밖 effort medium을 저장하면 두 키 모두 기본값으로 되돌리고 알림을 남긴다."""
        # Given
        self.save({"codex_worker_model": "gpt-6.1-terra", "codex_worker_effort": "medium"})

        # When
        pair, notice = self.resolve()

        # Then
        self.assertEqual(CODEX_DEFAULT, pair)
        self.assertIn("medium", notice)

    def test_고정_모델_값은_GPT_모델만_돌려주고_auto와_Claude_값은_None이다(self):
        """fixed_worker_model은 gpt-로 시작하는 고정 값만 모델로 돌려준다."""
        # When
        values = {setting: plugin_toggles.fixed_worker_model(setting) for setting in ("auto", "gpt-6-luna", "gpt-6.1-terra", "claude-sonnet-5-5")}

        # Then
        self.assertEqual({"auto": None, "gpt-6-luna": "gpt-6-luna", "gpt-6.1-terra": "gpt-6.1-terra", "claude-sonnet-5-5": None}, values)

    def test_Codex는_마켓플레이스_이름이_달라도_플러그인_접두사가_같으면_저장값을_쓴다(self):
        """키가 hei5enbug-agent-setup@로 시작하면 마켓플레이스 이름과 무관하게 읽는다."""
        # Given
        self.save({"codex_worker_effort": "high"}, key="hei5enbug-agent-setup@other-market")

        # When
        pair, notice = self.resolve()

        # Then
        self.assertEqual(("auto", "high"), pair)
        self.assertIsNone(notice)

    def test_Codex는_고정_모델과_auto와_Sonnet_경로를_저장값으로_받는다(self):
        """저장된 gpt-6-luna와 gpt-6.2-sol은 고정 모델로, auto와 claude-sonnet-5-5는 그대로 돌려주고, 알림은 없다."""
        # Given
        saved = ("gpt-6-luna", "gpt-6.2-sol", "auto", "claude-sonnet-5-5")

        # When
        results = []
        for model in saved:
            self.save({"codex_worker_model": model, "codex_worker_effort": "xhigh"})
            results.append(self.resolve())

        # Then
        self.assertEqual([((model, "xhigh"), None) for model in saved], results)

    def test_Codex는_환경_변수가_저장된_값보다_우선한다(self):
        """HEI5ENBUG_CODEX_WORKER_MODEL이 있으면 저장된 모델을 덮고, 없는 키는 저장된 값을 쓴다."""
        # Given
        self.save({"codex_worker_model": "gpt-6.2-sol", "codex_worker_effort": "high"})

        # When
        with mock.patch.dict(os.environ, {"HEI5ENBUG_CODEX_WORKER_MODEL": " GPT-6-Luna "}):
            pair, notice = self.resolve()

        # Then
        self.assertEqual(("gpt-6-luna", "high"), pair)
        self.assertIsNone(notice)

    def test_Codex는_두_환경_변수가_있으면_설정_파일을_읽지_않는다(self):
        """두 키가 모두 환경 변수로 오면 깨진 settings.json이 있어도 알림 없이 그 값을 쓴다."""
        # Given
        (self.config / "settings.json").write_text("{broken", encoding="utf-8")
        env = {"HEI5ENBUG_CODEX_WORKER_MODEL": "gpt-6.2-sol", "HEI5ENBUG_CODEX_WORKER_EFFORT": "xhigh"}

        # When
        with mock.patch.dict(os.environ, env):
            pair, notice = self.resolve()

        # Then
        self.assertEqual(("gpt-6.2-sol", "xhigh"), pair)
        self.assertIsNone(notice)

    def test_Codex는_목록에_없는_저장_모델이면_기본값과_값을_적은_알림을_돌려준다(self):
        """저장된 모델이 매니페스트 목록에 없으면 두 키 모두 기본값으로 되돌리고 무시한 값을 알림에 적는다."""
        # Given
        self.save({"codex_worker_model": "gpt-4.1-mini", "codex_worker_effort": "high"})

        # When
        pair, notice = self.resolve()

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
                pair, notice = self.resolve()

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
                pair, notice = self.resolve()

                # Then
                self.assertEqual(CODEX_DEFAULT, pair)
                self.assertIn("Ignored", notice)

    def test_Codex는_설정_파일_자리에_디렉터리가_있으면_기본값과_알림을_돌려준다(self):
        """settings.json을 읽을 수 없으면 기본값과 알림을 돌려준다."""
        # Given
        (self.config / "settings.json").mkdir()

        # When
        pair, notice = self.resolve()

        # Then
        self.assertEqual(CODEX_DEFAULT, pair)
        self.assertIn("unreadable", notice)

    def test_Codex는_환경_변수_하나만_있고_설정_파일이_깨져도_그_값을_유지하고_알림을_돌려준다(self):
        """모델만 환경 변수로 오고 settings.json이 깨졌으면 모델은 유지하고 effort만 기본값을 쓰며 무시 알림을 적는다."""
        # Given
        (self.config / "settings.json").write_text("{broken", encoding="utf-8")

        # When
        with mock.patch.dict(os.environ, {"HEI5ENBUG_CODEX_WORKER_MODEL": "gpt-6.2-sol"}):
            pair, notice = self.resolve()

        # Then
        self.assertEqual(("gpt-6.2-sol", "high"), pair)
        self.assertIn("Ignored the saved worker settings", notice)

    def test_Claude는_역할_고정이_꺼져_있으면_설정값_대신_기본값과_알림을_돌려준다(self):
        """role_pinning이 꺼지면 설정한 effort는 적용되지 않으므로 기본값과 역할 고정 알림을 돌려준다."""
        # Given
        env = {
            "CLAUDE_PLUGIN_OPTION_ROLE_PINNING": "false",
            "CLAUDE_PLUGIN_OPTION_WORKER_EFFORT": "xhigh",
        }

        # When
        with mock.patch.dict(os.environ, env):
            effort, notice = plugin_toggles.claude_worker_effort()

        # Then
        self.assertEqual(CLAUDE_DEFAULT, effort)
        self.assertIn("role pinning is off", notice)

    def test_Codex는_역할_고정_옵션과_무관하게_설정값을_쓴다(self):
        """Claude의 role_pinning이 꺼져 있어도 Codex 쌍은 그대로 적용된다."""
        # Given
        env = {
            "CLAUDE_PLUGIN_OPTION_ROLE_PINNING": "false",
            "HEI5ENBUG_ROLE_PINNING": "false",
            "HEI5ENBUG_CODEX_WORKER_MODEL": "gpt-6.2-sol",
            "HEI5ENBUG_CODEX_WORKER_EFFORT": "high",
        }

        # When
        with mock.patch.dict(os.environ, env):
            pair, notice = self.resolve()

        # Then
        self.assertEqual(("gpt-6.2-sol", "high"), pair)
        self.assertIsNone(notice)

    def test_설정_조회는_설정_파일을_쓰지_않는다(self):
        """저장된 값을 읽은 뒤에도 settings.json의 바이트가 그대로이고 새 파일이 생기지 않는다."""
        # Given
        self.save({"codex_worker_model": "gpt-6.2-sol"})
        path = self.config / "settings.json"
        before = path.read_bytes()

        # When
        self.resolve()

        # Then
        self.assertEqual(before, path.read_bytes())
        self.assertEqual([path], list(self.config.iterdir()))

    def test_Claude는_옵션_환경_변수의_effort를_쓰고_저장된_파일은_읽지_않는다(self):
        """CLAUDE_PLUGIN_OPTION_WORKER_EFFORT를 돌려주고 저장된 파일은 읽지 않으며, 더는 선언하지 않는 worker_model은 무시한다."""
        # Given
        self.save({"worker_effort": "low", "worker_model": "claude-opus-5-5"})
        env = {"CLAUDE_PLUGIN_OPTION_WORKER_MODEL": "claude-opus-5-5", "CLAUDE_PLUGIN_OPTION_WORKER_EFFORT": "max"}

        # When
        with mock.patch.dict(os.environ, env):
            effort, notice = plugin_toggles.claude_worker_effort()

        # Then
        self.assertEqual("max", effort)
        self.assertIsNone(notice)

    def test_Claude는_옵션이_없으면_기본값을_알림_없이_쓴다(self):
        """환경 변수가 없거나 비어 있으면 high를 돌려준다."""
        # Given
        env = {"CLAUDE_PLUGIN_OPTION_WORKER_EFFORT": " "}

        # When
        with mock.patch.dict(os.environ, env):
            effort, notice = plugin_toggles.claude_worker_effort()

        # Then
        self.assertEqual(CLAUDE_DEFAULT, effort)
        self.assertIsNone(notice)

    def test_Claude는_목록에_없는_effort이면_기본값과_알림을_돌려준다(self):
        """목록에 없는 effort는 기본값으로 되돌리고 무시한 값을 알림에 적는다."""
        # Given
        env = {"CLAUDE_PLUGIN_OPTION_WORKER_EFFORT": "ultra"}

        # When
        with mock.patch.dict(os.environ, env):
            effort, notice = plugin_toggles.claude_worker_effort()

        # Then
        self.assertEqual(CLAUDE_DEFAULT, effort)
        self.assertIn("worker_effort", notice)
        self.assertIn("ultra", notice)

    def test_effort_규칙이_허용하지_않는_쌍은_기본값과_알림을_돌려준다(self):
        """레지스트리 effort_rules가 막는 모델과 effort 조합은 두 키 모두 기본값으로 되돌린다."""
        # Given
        rules = {"gpt-6.2-sol": ["high"]}
        registry = json.loads((REPO_ROOT / "config" / "model-registry.json").read_text(encoding="utf-8"))
        registry["effort_rules"] = {**registry["effort_rules"], **rules}
        env = {"HEI5ENBUG_CODEX_WORKER_MODEL": "gpt-6.2-sol", "HEI5ENBUG_CODEX_WORKER_EFFORT": "xhigh"}
        original = Path.read_text

        def read_text(path, *args, **kwargs):
            return json.dumps(registry) if path.name == "model-registry.json" else original(path, *args, **kwargs)

        # When
        with mock.patch.dict(os.environ, env), mock.patch.object(Path, "read_text", read_text):
            pair, notice = self.resolve()

        # Then
        self.assertEqual(CODEX_DEFAULT, pair)
        self.assertIn("not allowed", notice)


if __name__ == "__main__":
    unittest.main()
