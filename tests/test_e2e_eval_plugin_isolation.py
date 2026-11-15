"""Tests that a Claude Code trial of the end-to-end evaluation harness loads only the variant plugin."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))

from harness import command, environment, matrix, metrics, pilot_check, runner  # noqa: E402

VARIANT_PLUGIN = {"name": "hei5enbug-agent-setup", "source": "hei5enbug-agent-setup@inline", "path": "/tmp/work/export"}
EXTRA_PLUGIN = {"name": "demo-viewer", "source": "demo-viewer@inline", "path": "/tmp/work/demo-viewer"}


def init_event(plugins: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "system", "subtype": "init", "session_id": "s-1", "permissionMode": "auto", "plugins": plugins}


def write_profile(folder: Path, installed: list[str], enabled: list[str]) -> None:
    (folder / "plugins").mkdir(parents=True)
    (folder / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"version": 2, "plugins": {key: [{"scope": "user"}] for key in installed}}), encoding="utf-8")
    (folder / "settings.json").write_text(json.dumps({"enabledPlugins": {key: True for key in enabled}}), encoding="utf-8")


class ProfilePluginsOffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile = Path(self.tmp.name) / "profile"
        self.variant = command.validate_variant({"name": "after", "ref": "HEAD"})

    def test_프로필에서_켜진_플러그인_셋은_실행_설정에서_모두_꺼지고_변형은_적히지_않는다(self):
        """설치 기록에 둘, 설정 파일에 셋째가 있으면 세 개 모두 false이고 인라인 변형 키는 없다."""
        # given
        write_profile(self.profile, ["alpha@demo", "beta@demo"], ["beta@demo", "gamma@demo"])

        # when
        settings = command.run_settings(self.variant, environment.profile_plugin_ids(self.profile))

        # then
        enabled = settings["enabledPlugins"]
        self.assertEqual([enabled[key] for key in ("alpha@demo", "beta@demo", "gamma@demo")], [False, False, False])
        self.assertIs(enabled["hei5enbug-agent-setup@hei5enbug"], False)
        self.assertFalse([key for key in enabled if key.endswith("@inline")])

    def test_변형_설정이_프로필_플러그인을_켜려_해도_꺼진_채로_남는다(self):
        """변형이 프로필에 있는 플러그인을 true로 적어도 병합 뒤 false이고, 프로필에 없는 키는 그대로 둔다."""
        # given
        write_profile(self.profile, ["alpha@demo"], [])
        variant = command.validate_variant({"name": "v", "ref": "HEAD", "settings": {"enabledPlugins": {"alpha@demo": True, "free@demo": True}}})

        # when
        enabled = command.run_settings(variant, environment.profile_plugin_ids(self.profile))["enabledPlugins"]

        # then
        self.assertEqual((enabled["alpha@demo"], enabled["free@demo"]), (False, True))

    def test_프로필_파일이_없으면_빈_목록이고_깨졌으면_오류를_낸다(self):
        """파일이 없는 프로필은 끌 플러그인이 없고, 읽을 수 없는 JSON은 조용히 넘기지 않는다."""
        # given
        broken = Path(self.tmp.name) / "broken"
        (broken / "plugins").mkdir(parents=True)
        (broken / "plugins" / "installed_plugins.json").write_text("{not json", encoding="utf-8")

        # when
        missing = environment.profile_plugin_ids(Path(self.tmp.name) / "none")

        # then
        self.assertEqual(missing, [])
        with self.assertRaises(ValueError):
            environment.profile_plugin_ids(broken)

    def test_자식_환경에서_인라인_플러그인_경로_변수도_빠지고_이름이_기록된다(self):
        """CLAUDE_CODE_PLUGIN_DIRS는 ORCA_ 접두사가 없어도 제거되고 다른 변수는 남는다."""
        # given
        base = {"CLAUDE_CODE_PLUGIN_DIRS": "/tmp/demo-viewer", "ORCA_X": "1", "PATH": "/bin"}

        # when
        env, removed = environment.child_environment(base, {})

        # then
        self.assertEqual(removed, ["CLAUDE_CODE_PLUGIN_DIRS", "ORCA_X"])
        self.assertEqual(env, {"PATH": "/bin"})

    def test_명령줄은_승인_서버_밖의_MCP_서버를_읽지_않는다(self):
        """--strict-mcp-config가 --mcp-config 뒤에 들어가고 pilot-check가 문제를 찾지 못한다."""
        # given
        task = {"limits": {"wall_seconds": 60, "max_budget_usd": 7}}

        # when
        argv = command.build_command(command.HarnessConfig(), task, self.variant, "prompt", "/tmp/p", Path("/tmp/run"))

        # then
        self.assertIn("--strict-mcp-config", argv)
        self.assertEqual(pilot_check.command_problems(argv), [])
        self.assertEqual(pilot_check.command_problems([item for item in argv if item != "--strict-mcp-config"]), ["missing --strict-mcp-config"])


class ExtraPluginRunTest(unittest.TestCase):
    def test_init_이벤트에_다른_플러그인이_있으면_infra_failed이고_이름을_밝힌다(self):
        """변형 외에 demo-viewer가 올라온 실행은 결과 메시지가 있어도 infra_failed이고 오류에 이름이 있다."""
        # given
        facts = metrics.stream_facts([init_event([VARIANT_PLUGIN, EXTRA_PLUGIN]), {"type": "result", "is_error": False}])

        # when
        status = runner.decide_status(facts, None, False)

        # then
        self.assertEqual(status, "infra_failed")
        self.assertIn("demo-viewer@inline", runner.contamination_error(facts) or "")
        self.assertEqual(runner.decide_status(facts, None, True), "infra_failed")

    def test_init_이벤트에_변형만_있으면_완료로_판정한다(self):
        """내보낸 변형 하나만 올라온 실행은 complete이고 오염 오류가 없다."""
        # given
        facts = metrics.stream_facts([init_event([VARIANT_PLUGIN]), {"type": "result", "is_error": False}])

        # when
        status = runner.decide_status(facts, None, False)

        # then
        self.assertEqual((status, runner.contamination_error(facts)), ("complete", None))


class PilotCheckExtraPluginTest(unittest.TestCase):
    def seed(self, root: Path, plugins: list[dict[str, Any]]) -> None:
        spec = matrix.make_spec(root, "camp", "T13", "baseline", 1)
        folder = spec.result_dir
        matrix.write_json(folder / "run.json", {"run_id": spec.run_id, "status": "complete", "plugin": {"path": VARIANT_PLUGIN["path"]}})
        (folder / "stream.jsonl").write_text(
            "\n".join(json.dumps(event) for event in (init_event(plugins), {"type": "result", "is_error": False})) + "\n", encoding="utf-8")

    def test_init_이벤트에_다른_플러그인이_있는_실행은_pilot_check가_실패시킨다(self):
        """변형만 있으면 해당 항목이 PASS이고, demo-viewer가 더 있으면 FAIL 줄에 이름이 나온다."""
        # given
        with tempfile.TemporaryDirectory() as tmp:
            clean, dirty = Path(tmp) / "clean", Path(tmp) / "dirty"
            self.seed(clean, [VARIANT_PLUGIN])
            self.seed(dirty, [VARIANT_PLUGIN, EXTRA_PLUGIN])
            clean_out, dirty_out = io.StringIO(), io.StringIO()

            # when
            pilot_check.pilot_check(clean, "camp", frozenset(), clean_out)
            pilot_check.pilot_check(dirty, "camp", frozenset(), dirty_out)

            # then
            self.assertIn("PASS no plugin besides the variant", clean_out.getvalue())
            self.assertIn("FAIL no plugin besides the variant: demo-viewer@inline", dirty_out.getvalue())


if __name__ == "__main__":
    unittest.main()
