"""Tests for a stock variant (no plugin) and for a variant that removes parts of the plugin's text, in the e2e harness."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))

from harness import campaign, caps, codex_host, command, inputs, markdown_parts, matrix, pilot_check, plugin_export, records  # noqa: E402
from harness.config import HarnessConfig  # noqa: E402

GUIDE = """# Guide

Intro paragraph that stays.

- First rule stays on
  across two lines.
- Second rule goes away
  and so does this line.
- Third rule stays.

## Extras

Extra paragraph one.

- Extra bullet.

## Tail

Tail paragraph stays.
"""


def make_repo(root: Path, files: dict[str, str]) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git = ["git", "-c", "user.name=Demo Dev", "-c", "user.email=dev@example.com", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q", "-b", "main"], cwd=repo, check=True)
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    subprocess.run([*git, "add", "."], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


class MarkdownPartsTest(unittest.TestCase):
    def test_불릿과_문단과_제목을_구분하고_이어지는_줄은_불릿에_붙는다(self):
        """줄바꿈으로 이어진 불릿은 한 부분이고 제목은 불릿이나 문단으로 세지 않는다."""
        # given / when
        parts = markdown_parts.parse_parts(GUIDE)

        # then
        self.assertEqual([(part.kind, part.text) for part in parts][:5], [
            ("heading", "Guide"), ("paragraph", "Intro paragraph that stays."),
            ("bullet", "First rule stays on across two lines."), ("bullet", "Second rule goes away and so does this line."),
            ("bullet", "Third rule stays."),
        ])

    def test_첫_단어로_고른_불릿만_잘라내고_앞뒤_줄바꿈은_빈_줄_하나만_남긴다(self):
        """두 줄짜리 불릿 하나가 사라지고 나머지는 그대로이며 연속된 빈 줄이 생기지 않는다."""
        # given
        span = markdown_parts.span_of(GUIDE, start="Second rule goes")

        # when
        cut = markdown_parts.cut_spans(GUIDE, [span])

        # then
        self.assertNotIn("Second rule", cut)
        self.assertNotIn("and so does this line", cut)
        self.assertIn("- First rule stays on\n  across two lines.\n- Third rule stays.", cut)
        self.assertNotIn("\n\n\n", cut)

    def test_제목으로_고르면_다음_같은_수준_제목_앞까지_구역_전체가_잘린다(self):
        """`## Extras` 아래 문단과 불릿이 함께 사라지고 `## Tail`은 남는다."""
        # given
        span = markdown_parts.span_of(GUIDE, heading="## Extras")

        # when
        cut = markdown_parts.cut_spans(GUIDE, [span])

        # then
        self.assertNotIn("Extra", cut)
        self.assertIn("## Tail\n\nTail paragraph stays.", cut)

    def test_아무것도_못_찾거나_둘_이상을_찾는_선택은_오류다(self):
        """일치가 0개나 2개 이상이면 PartError이고 메시지가 어느 쪽인지 말한다."""
        # given
        text = "- Same start one.\n- Same start two.\n"

        # when / then
        with self.assertRaisesRegex(markdown_parts.PartError, "matches nothing"):
            markdown_parts.span_of(text, start="Absent words")
        with self.assertRaisesRegex(markdown_parts.PartError, "matches 2 parts"):
            markdown_parts.span_of(text, start="Same start")


class RemoveEntryExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.root, {"instructions/session/guide.md": GUIDE, "README.md": "# Demo\n\nUntouched.\n"})
        self.runs = self.root / "runs"

    def export(self, removals: list[dict[str, str]]) -> dict[str, Any]:
        return plugin_export.export_plugin(self.repo, self.runs, "HEAD", removals=removals)

    def test_섹션_하나를_remove하면_그_제목_구역만_내보낸_폴더에서_사라진다(self):
        """`## Extras` 항목 하나로 내보내면 그 구역만 없고 다른 구역과 다른 파일은 그대로이며 기록에 잘라낸 바이트가 남는다."""
        # given
        removals = [{"file": "instructions/session/guide.md", "heading": "## Extras"}]

        # when
        exported = self.export(removals)
        root = Path(exported["path"])
        text = (root / "instructions/session/guide.md").read_text(encoding="utf-8")

        # then
        self.assertNotIn("Extra", text)
        self.assertIn("## Tail", text)
        self.assertIn("Third rule stays.", text)
        self.assertEqual((root / "README.md").read_text(encoding="utf-8"), "# Demo\n\nUntouched.\n")
        self.assertEqual([item["file"] for item in exported["removed"]], ["instructions/session/guide.md"])
        self.assertGreater(exported["removed"][0]["bytes"], 0)

    def test_아무것도_못_찾는_remove_항목은_내보내기를_실패시킨다(self):
        """없는 불릿 첫 단어는 ExportError이고 메시지에 파일과 단어가 나온다."""
        # given
        removals = [{"file": "instructions/session/guide.md", "start": "Absent rule"}]

        # when / then
        with self.assertRaisesRegex(plugin_export.ExportError, "matches nothing.*Absent rule"):
            self.export(removals)

    def test_둘_이상을_찾는_remove_항목과_없는_파일은_내보내기를_실패시킨다(self):
        """`Extra`로 시작하는 부분이 둘이면 실패하고, 없는 파일을 가리켜도 실패한다."""
        # given
        ambiguous = [{"file": "instructions/session/guide.md", "start": "Extra"}]
        missing = [{"file": "instructions/session/none.md", "heading": "## Extras"}]

        # when / then
        with self.assertRaisesRegex(plugin_export.ExportError, "matches 2 parts"):
            self.export(ambiguous)
        with self.assertRaisesRegex(plugin_export.ExportError, "cannot read"):
            self.export(missing)

    def test_remove가_다른_내보내기는_다른_폴더에_들어가고_같은_항목은_그_폴더를_다시_쓴다(self):
        """제거 없는 내보내기, 불릿 하나 제거, 같은 제거를 다시 한 경우가 각각 어느 폴더인지 확인한다."""
        # given
        removal = [{"file": "instructions/session/guide.md", "start": "Second rule goes"}]

        # when
        plain = self.export([])
        cut = self.export(removal)
        again = self.export(removal)

        # then
        self.assertNotEqual(plain["path"], cut["path"])
        self.assertEqual(cut["path"], again["path"])
        self.assertIn("Second rule", (Path(plain["path"]) / "instructions/session/guide.md").read_text(encoding="utf-8"))
        self.assertNotIn("Second rule", (Path(cut["path"]) / "instructions/session/guide.md").read_text(encoding="utf-8"))

    def test_제거_변형의_기록_리비전은_제거_없는_같은_sha와_다르고_짧게_줄여도_제거_표시가_남는다(self):
        """같은 sha에서 불릿 하나를 뺀 내보내기의 리비전은 전체 플러그인의 sha와 달라 기록에서 두 변형이 구분된다."""
        # given
        removal = [{"file": "instructions/session/guide.md", "start": "Second rule goes"}]
        plain, cut = self.export([]), self.export(removal)

        # when
        plain_label, cut_label = plugin_export.revision_of(plain), plugin_export.revision_of(cut)

        # then
        self.assertEqual(plain_label, plain["sha"])
        self.assertNotEqual(cut_label, plain_label)
        self.assertTrue(cut_label.startswith(plain["sha"] + "-"))
        self.assertEqual(plugin_export.short_revision(cut_label), f"{plain['sha'][:12]}-{plugin_export.removals_key(removal)}")
        self.assertEqual(plugin_export.short_revision(plain_label), plain["sha"][:12])

    def test_변형의_remove_항목_모양이_틀리면_변형을_읽을_때_거부한다(self):
        """start와 heading을 둘 다 주거나 절대 경로를 주면 ConfigError다."""
        # given
        both = {"name": "v", "ref": "HEAD", "remove": [{"file": "a.md", "start": "x", "heading": "## y"}]}
        absolute = {"name": "v", "ref": "HEAD", "remove": [{"file": "/etc/a.md", "start": "x"}]}

        # when / then
        for bad in (both, absolute):
            with self.subTest(bad=bad), self.assertRaises(command.ConfigError):
                command.validate_variant(bad)


class StockVariantTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        variants = self.root / "variants"
        variants.mkdir()
        (variants / "stock.json").write_text(json.dumps({"name": "stock", "plugin": "none"}), encoding="utf-8")
        (variants / "plugin.json").write_text(json.dumps({"name": "plugin", "ref": "HEAD", "env": {
            "CLAUDE_PLUGIN_OPTION_REVIEW_MODEL": "gpt-6.1-sol", "HEI5ENBUG_REVIEW_MODEL": "gpt-6.1-sol"}}), encoding="utf-8")
        self.repo = make_repo(self.root, {"README.md": "# Demo\n"})
        self.cfg = HarnessConfig(
            run_root=self.root / "runs", tasks_root=REPO_ROOT / "evals/e2e/tasks", fixtures_root=REPO_ROOT / "evals/e2e/fixtures",
            variants_root=variants, repo_root=self.repo, codex_bin="codex",
        )

    def plan(self) -> str:
        out = io.StringIO()
        tasks, variants = campaign.load_plan(self.cfg, ["T08"], ["stock", "plugin"])
        specs = campaign.build_specs(self.cfg, "demo", ["T08"], ["stock", "plugin"], 1, ["claude", "codex"])
        campaign.print_plan(out, self.cfg, specs, tasks, variants)
        return out.getvalue()

    def test_플러그인_없는_변형의_드라이런은_Claude_명령에_plugin_dir이_없고_Codex_설치_단계도_없다(self):
        """stock은 `--plugin-dir`과 Codex `plugin add` 줄이 없고, 같은 계획의 plugin 변형은 둘 다 가진다."""
        # given / when
        blocks = [block for block in self.plan().split("\n\n") if block.startswith("[")]
        by_id = {block.split("\n")[0].split()[1]: block for block in blocks}

        # then
        self.assertNotIn("--plugin-dir", by_id["T08-stock-r1"])
        self.assertIn("claude -p", by_id["T08-stock-r1"])
        self.assertNotIn("plugin add", by_id["T08-stock-codex-r1"])
        self.assertNotIn("marketplace", by_id["T08-stock-codex-r1"])
        self.assertIn("codex exec", by_id["T08-stock-codex-r1"])
        self.assertIn("--plugin-dir", by_id["T08-plugin-r1"])
        self.assertIn("plugin add", by_id["T08-plugin-codex-r1"])

    def test_플러그인_없는_변형은_ref와_remove를_받지_않고_ref_없이_읽힌다(self):
        """`plugin: none`에 ref나 remove를 주면 ConfigError이고, 둘 다 없으면 stock으로 읽힌다."""
        # given
        with_ref = {"name": "s", "plugin": "none", "ref": "HEAD"}
        with_remove = {"name": "s", "plugin": "none", "remove": [{"file": "a.md", "start": "x"}]}
        unknown = {"name": "s", "plugin": "other"}

        # when
        stock = command.validate_variant({"name": "s", "plugin": "none"})

        # then
        self.assertTrue(command.is_stock(stock))
        for bad in (with_ref, with_remove, unknown):
            with self.subTest(bad=bad), self.assertRaises(command.ConfigError):
                command.validate_variant(bad)

    def test_플러그인_없는_변형은_내보내지_않고_입력_지문에_none으로_들어간다(self):
        """stock은 export_for_variant가 폴더 없는 기록을 주고 inputs의 variant sha가 `none`이다."""
        # given
        stock = command.load_variant(self.cfg.variants_root, "stock")

        # when
        record = plugin_export.export_for_variant(self.repo, self.cfg.run_root, stock)
        current = inputs.compute_inputs(self.cfg, ["T08"], ["stock"], {"stock": record})

        # then
        self.assertEqual((record["path"], record["sha"], record["stock"]), (None, None, True))
        self.assertFalse((self.cfg.run_root / "plugins").exists())
        self.assertEqual(current["variant_shas"], {"stock": "none"})

    def test_Codex_플러그인_없는_실행은_홈과_인증만_만들고_설치와_훅_신뢰를_하지_않는다(self):
        """플러그인 폴더가 None이면 setup 명령이 없고 codex-setup.json에 설치 단계 없이 plugin none이 적힌다."""
        # given
        user_home = self.root / "user-codex"
        user_home.mkdir()
        (user_home / "auth.json").write_text("demo-credential", encoding="utf-8")
        result_dir = self.root / "result"
        result_dir.mkdir()
        env = {**os.environ, **codex_host.host_env(result_dir)}

        # when
        record = codex_host.prepare_home(self.cfg, result_dir, None, env, user_home)

        # then
        self.assertEqual(codex_host.setup_commands(self.cfg, None), [])
        self.assertEqual((record["steps"], record["plugin"]), ([], "none"))
        self.assertTrue((result_dir / "codex-home" / "auth.json").is_symlink())

    def test_플러그인_없는_변형은_모델_상한_검사에서_매니페스트_기본값을_읽지_않는다(self):
        """ref가 없는 stock 변형도 check_variant가 문제 없이 통과하고 ref를 해석하려 하지 않는다."""
        # given
        stock = command.load_variant(self.cfg.variants_root, "stock")

        # when
        problems = caps.check_variant(self.cfg, stock)

        # then
        self.assertEqual(problems, [])

    def test_플러그인_없는_실행의_훅_사실은_빈_경로를_현재_폴더로_읽지_않고_건너뛴다(self):
        """run.json의 plugin 경로가 None이면 run_hook_facts가 skipped를 돌려준다."""
        # given
        spec = matrix.make_spec(self.root, "camp", "T08", "stock", 1)
        matrix.write_json(spec.result_dir / "run.json", {"plugin": {"stock": True, "path": None}})
        matrix.write_json(spec.result_dir / "view.json", {"tool_calls": []})
        Path(spec.repo).mkdir(parents=True, exist_ok=True)

        # when
        facts = records.run_hook_facts(spec)

        # then
        self.assertIn("skipped", facts)

    def test_stock_변형의_기록_리비전은_캠페인_입력의_none이다(self):
        """실행이 sha를 저장하지 않은 stock 변형은 record의 리비전이 `none`이다."""
        # given
        base = matrix.campaign_dir(self.root, "camp")
        matrix.write_json(base / "campaign.json", {"inputs": {"variant_shas": {"stock": "none"}}})

        # when
        revision = records.variant_revision(self.root, "camp", "stock")

        # then
        self.assertEqual(revision, "none")

    def test_pilot_check는_플러그인_없는_Claude_실행에서_plugin_dir이_있으면_실패시킨다(self):
        """stock이면 `--plugin-dir`이 없어야 통과하고, 있으면 문제로 보고하며, plugin 변형은 반대다."""
        # given
        base = ["claude", "-p", "--settings", "s", "--permission-prompt-tool", pilot_check.APPROVER_TOOL,
                "--max-budget-usd", "1", "--strict-mcp-config", "--setting-sources", "project,local"]
        with_dir = [*base, "--plugin-dir", "/tmp/p"]

        # when / then
        self.assertEqual(pilot_check.command_problems(base, stock=True), [])
        self.assertEqual(pilot_check.command_problems(with_dir, stock=True), ["stock run passes --plugin-dir"])
        self.assertEqual(pilot_check.command_problems(base), ["missing --plugin-dir"])
        self.assertEqual(pilot_check.command_problems(with_dir), [])

    def test_stock_변형_실행_기록은_pilot_check에서_플러그인_없음_항목으로_통과한다(self):
        """plugin이 stock인 run.json과 init 이벤트에 플러그인이 없는 스트림은 `no plugin loaded` PASS다."""
        # given
        spec = matrix.make_spec(self.root, "camp", "T08", "stock", 1)
        matrix.write_json(spec.result_dir / "run.json", {"run_id": spec.run_id, "status": "complete", "plugin": {"stock": True, "path": None}})
        matrix.write_json(spec.result_dir / "command.json", {"argv": [
            "claude", "-p", "--settings", "s", "--permission-prompt-tool", pilot_check.APPROVER_TOOL, "--max-budget-usd", "1",
            "--strict-mcp-config", "--setting-sources", "project,local", "--", "prompt"]})
        matrix.write_json(spec.result_dir / "env.json", {"instruction_isolation": {"env": {pilot_check.AUTO_MEMORY_OFF_ENV: "1"}}})
        events = [{"type": "system", "subtype": "init", "session_id": "s-1", "permissionMode": "auto", "plugins": []},
                  {"type": "result", "is_error": False}]
        (spec.result_dir / "stream.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
        out = io.StringIO()

        # when
        code = pilot_check.pilot_check(self.root, "camp", frozenset(), out)

        # then
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("PASS no plugin loaded", out.getvalue())
        self.assertIn("PASS command line without bypass flags", out.getvalue())


class CommittedVariantsTest(unittest.TestCase):
    def test_저장소의_stock_변형은_플러그인_없이_읽히고_baseline_변형은_ref를_가진다(self):
        """evals/e2e/variants의 stock.json과 baseline.json이 변형 검증을 통과한다."""
        # given
        folder = REPO_ROOT / "evals/e2e/variants"

        # when
        stock = command.load_variant(folder, "stock")
        baseline = command.load_variant(folder, "baseline")

        # then
        self.assertTrue(command.is_stock(stock))
        self.assertFalse(command.is_stock(baseline))
        self.assertTrue(baseline["ref"])


if __name__ == "__main__":
    unittest.main()
