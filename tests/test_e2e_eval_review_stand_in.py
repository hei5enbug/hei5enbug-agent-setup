"""Tests for the Claude stand-in of the text reviewer model in the plugin export of the end-to-end evaluation harness."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))

from harness import campaign, cli, environment, plugin_export, records  # noqa: E402
from harness.config import HarnessConfig  # noqa: E402

LITERAL = "gpt-6.1-sol"
STAND_IN = "claude-sonnet-5-5"
REVIEW_SCRIPT = f'KINDS = ("a", "b")\nREVIEW_MODELS = {{kind: "{LITERAL}" for kind in KINDS}}\nDEFAULT_TIMEOUT = 600\n'
FILES = {"scripts/text_review.py": REVIEW_SCRIPT, "instructions/shared-text.md": "review with the script\n",
         "hooks/hooks.json": '{"hooks": {}}\n', "commands/run.md": "run it\n", "README.md": f"{LITERAL} stays in prose\n"}


def make_repo(tmp: str, files: dict[str, str]) -> Path:
    repo = Path(tmp) / "repo"
    repo.mkdir(exist_ok=True)
    git = ["git", "-c", "user.name=Demo Dev", "-c", "user.email=dev@example.com", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q", "-b", "main"], cwd=repo, check=True)
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    subprocess.run([*git, "add", "."], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def tree(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


class ExportStandInTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.tmp.name, FILES)

    def test_옵션을_켜면_리뷰_모델_글자만_Claude_모델로_바뀌고_다른_바이트는_그대로다(self):
        """given 리뷰어 모델이 적힌 ref when 옵션을 켜고 내보내면 then text_review.py의 그 글자만 바뀌고 나머지 파일은 옵션 없이 낸 것과 같다."""
        # given
        plain = plugin_export.export_plugin(self.repo, self.root / "plain", "HEAD")

        # when
        swapped = plugin_export.export_plugin(self.repo, self.root / "swapped", "HEAD", review_stand_in=True)

        # then
        before, after = tree(Path(plain["path"])), tree(Path(swapped["path"]))
        self.assertEqual(set(before), set(after))
        self.assertEqual([name for name in before if before[name] != after[name]], ["scripts/text_review.py"])
        self.assertEqual(after["scripts/text_review.py"].decode(), REVIEW_SCRIPT.replace(LITERAL, STAND_IN))
        self.assertNotEqual(plain["content_digest"], swapped["content_digest"])

    def test_옵션이_꺼져_있으면_내보낸_폴더가_바뀌지_않고_기록도_스탠드인이_없다고_적는다(self):
        """given 리뷰어 모델이 적힌 ref when 옵션 없이 내보내면 then text_review.py가 git 내용 그대로이고 기록에 스탠드인이 없다."""
        # when
        exported = plugin_export.export_plugin(self.repo, self.root / "runs", "HEAD")

        # then
        self.assertEqual((Path(exported["path"]) / "scripts/text_review.py").read_text(encoding="utf-8"), REVIEW_SCRIPT)
        self.assertIsNone(exported["review_stand_in"])
        self.assertNotIn("claude-review", exported["path"])

    def test_옵션을_켠_내보내기는_별도_폴더에_만들고_모델과_파일과_바꾼_글자를_기록한다(self):
        """given 같은 ref when 옵션을 켠 내보내기와 끈 내보내기를 한 실행 폴더에 함께 만들면 then 폴더가 따로 있고 기록에 모델과 바꾼 글자가 남는다."""
        # when
        plain = plugin_export.export_plugin(self.repo, self.root / "runs", "HEAD")
        swapped = plugin_export.export_plugin(self.repo, self.root / "runs", "HEAD", review_stand_in=True)
        again = plugin_export.export_plugin(self.repo, self.root / "runs", "HEAD", review_stand_in=True)

        # then
        self.assertNotEqual(plain["path"], swapped["path"])
        self.assertEqual(swapped["review_stand_in"],
                         {"model": STAND_IN, "file": "scripts/text_review.py", "replaced": LITERAL})
        self.assertEqual(again, swapped)
        self.assertEqual((Path(plain["path"]) / "scripts/text_review.py").read_text(encoding="utf-8"), REVIEW_SCRIPT)

    def test_리뷰_모델_글자가_정확히_하나가_아니면_내보내기를_거부하고_폴더를_만들지_않는다(self):
        """given 리뷰어 모델 글자가 없거나 둘인 text_review.py when 옵션을 켜고 내보내면 then 파일과 글자를 알리는 오류가 나고 내보낸 폴더가 없다."""
        for text in ("REVIEW_MODELS = {}\n", f'a = "{LITERAL}"\nb = "{LITERAL}"\n'):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                # given
                repo = make_repo(tmp, {"scripts/text_review.py": text})

                # when / then
                with self.assertRaises(plugin_export.ExportError) as caught:
                    plugin_export.export_plugin(repo, Path(tmp) / "runs", "HEAD", review_stand_in=True)
                self.assertIn("scripts/text_review.py", str(caught.exception))
                self.assertIn(LITERAL, str(caught.exception))
                self.assertFalse(list((Path(tmp) / "runs").glob("plugins/*/*")))

    def test_text_review_py가_없는_개정도_옵션을_켜면_거부한다(self):
        """given text_review.py가 없는 ref when 옵션을 켜고 내보내면 then 그 파일이 없다는 오류가 난다."""
        with tempfile.TemporaryDirectory() as tmp:
            # given
            repo = make_repo(tmp, {"README.md": "x\n"})

            # when / then
            with self.assertRaises(plugin_export.ExportError) as caught:
                plugin_export.export_plugin(repo, Path(tmp) / "runs", "HEAD", review_stand_in=True)
            self.assertIn("scripts/text_review.py", str(caught.exception))

    def test_두_변형은_같은_변환을_받는다(self):
        """given 서로 다른 개정의 두 변형 when 옵션을 켜고 내보내면 then 둘 다 같은 모델로 바뀌고 같은 기록을 남긴다."""
        # given
        (self.repo / "scripts/text_review.py").write_text(REVIEW_SCRIPT + "# changed\n", encoding="utf-8")
        git = ["git", "-c", "user.name=Demo Dev", "-c", "user.email=dev@example.com", "-c", "commit.gpgsign=false"]
        subprocess.run([*git, "commit", "-q", "-am", "second"], cwd=self.repo, check=True)

        # when
        first = plugin_export.export_plugin(self.repo, self.root / "runs", "HEAD~1", review_stand_in=True)
        second = plugin_export.export_plugin(self.repo, self.root / "runs", "HEAD", review_stand_in=True)

        # then
        self.assertEqual(first["review_stand_in"], second["review_stand_in"])
        for exported in (first, second):
            text = (Path(exported["path"]) / "scripts/text_review.py").read_text(encoding="utf-8")
            self.assertIn(f'kind: "{STAND_IN}"', text)
            self.assertNotIn(LITERAL, text)


class OptionFlowTest(unittest.TestCase):
    def test_run_옵션은_설정으로_들어가고_기본은_꺼져_있다(self):
        """given run 인자 when 설정을 만들면 then 옵션을 준 때만 review_stand_in이 켜진다."""
        # when
        off = cli.config_from(cli.build_parser().parse_args(["run"]))
        on = cli.config_from(cli.build_parser().parse_args(["run", "--claude-review-stand-in"]))
        export = cli.config_from(cli.build_parser().parse_args(["export-plugin", "--ref", "HEAD", "--claude-review-stand-in"]))

        # then
        self.assertEqual((off.review_stand_in, on.review_stand_in, export.review_stand_in), (False, True, True))

    def test_캠페인은_설정의_옵션을_내보내기에_넘기고_계획_출력은_그_폴더를_쓴다(self):
        """given 옵션이 켜진 설정 when 캠페인을 시작하면 then export_plugin이 옵션과 함께 불리고 export_dir이 별도 폴더를 돌려준다."""
        with tempfile.TemporaryDirectory() as tmp:
            # given
            root = Path(tmp)
            (root / "tasks/prompts").mkdir(parents=True)
            (root / "tasks/T01.json").write_text(json.dumps({"id": "T01", "fixture": "demo", "prompt_file": "prompts/T01.txt",
                                                             "limits": {"wall_seconds": 60, "max_budget_usd": 1}}), encoding="utf-8")
            (root / "tasks/prompts/T01.txt").write_text("do it\n", encoding="utf-8")
            (root / "variants").mkdir()
            (root / "variants/baseline.json").write_text(json.dumps({"name": "baseline", "ref": "HEAD", "env": {
                "CLAUDE_PLUGIN_OPTION_REVIEW_MODEL": "gpt-6.1-sol", "HEI5ENBUG_REVIEW_MODEL": "gpt-6.1-sol"}}), encoding="utf-8")
            cfg = HarnessConfig(run_root=root / "runs", tasks_root=root / "tasks", variants_root=root / "variants", review_stand_in=True)
            info = {"ref": "HEAD", "sha": "abc", "path": "/tmp/p"}

            # when
            with mock.patch.object(campaign.plugin_export, "export_plugin", return_value=info) as export, \
                    mock.patch.object(campaign.environment, "capture_base", return_value={}):
                campaign.run_campaign(cfg, "c1", ["T01"], ["baseline"], 1, 1, frozenset(), io.StringIO(), lambda *a, **k: {"status": "complete"})

            # then
            self.assertEqual(export.call_args.kwargs.get("review_stand_in"), True)
            self.assertNotEqual(plugin_export.export_dir(root, "a" * 40, True), plugin_export.export_dir(root, "a" * 40))

    def test_실행의_env_json은_스탠드인_기록을_담는다(self):
        """given 스탠드인 기록이 든 내보내기 정보 when 실행 스냅샷을 만들면 then env 스냅샷에 그 기록이 있고 없던 내보내기는 None이다."""
        # given
        stand_in = {"model": STAND_IN, "file": "scripts/text_review.py", "replaced": LITERAL}

        # when
        with_option = environment.run_snapshot({}, {"ref": "HEAD", "sha": "abc", "review_stand_in": stand_in}, [])
        without = environment.run_snapshot({}, {"ref": "HEAD", "sha": "abc"}, [])

        # then
        self.assertEqual(with_option["review_stand_in"], stand_in)
        self.assertIsNone(without["review_stand_in"])


class RecordStandInTest(unittest.TestCase):
    def seed(self, root: Path, env: dict) -> None:
        folder = root / "camp/results/T08/base/rep1"
        for name, data in (
            ("run.json", {"run_id": "T08-base-r1", "task": "T08", "variant": "base", "rep": 1, "status": "complete", "host": "claude"}),
            ("metrics.json", {"success": True, "wall_seconds": 10.0, "host": "claude", "plugin": {"subagent_models": {}},
                              "cost": {"claude_total_cost_usd": 1.0, "claude_runner_list_cost_usd": 0.0, "claude_list_cost_usd": 0.0}}),
            ("grade/grade.json", {"checks": [{"id": "hidden-tests", "required": True, "passed": True, "data": {}}]}),
            ("command.json", {"argv": ["claude", "-p", "--model", "claude-opus-5-5", "--effort", "high", "--", "prompt"]}),
            ("env.json", env), ("view.json", {"tool_calls": []})):
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            (folder / name).write_text(json.dumps(data) + "\n", encoding="utf-8")
        (folder / "stream.jsonl").write_text(json.dumps({"type": "system", "subtype": "init", "model": "claude-opus-5-5"}) + "\n", encoding="utf-8")

    def entry(self, env: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.seed(root, env)
            (root / "camp/campaign.json").write_text("{}", encoding="utf-8")
            runs = records.campaign_runs(root, "camp", ["base"], None)
        return runs[0]["entry"]

    def test_스탠드인을_쓴_실행의_기록_항목은_그_모델을_밝히고_쓰지_않은_실행은_필드가_없다(self):
        """given env.json에 스탠드인이 적힌 실행과 없는 실행 when 기록 항목을 만들면 then 앞의 것만 review_stand_in 모델을 가진다."""
        # when
        used = self.entry({"review_stand_in": {"model": STAND_IN, "file": "scripts/text_review.py", "replaced": LITERAL}})
        unused = self.entry({"review_stand_in": None})

        # then
        self.assertEqual(used["review_stand_in"], STAND_IN)
        self.assertNotIn("review_stand_in", unused)

    def test_기록은_스탠드인_필드를_담고_상한_밖_모델은_거부한다(self):
        """given review_stand_in이 든 실행 항목 when 기록을 만들고 검증하면 then 필드가 남고 상한 밖 모델이면 검증이 실패한다."""
        # given
        run = {"case": "T08", "variant": "base", "host": "claude", "rep": 1, "models": {"main": {"model": "claude-opus-5-5", "effort": "high"}},
               "checks": {"hidden-tests": True}, "wall_seconds": 10.0, "cost_usd": 1.0}
        verdicts = [{"case": "T08", "verdict": "baseline", "step": "first run"}]

        # when
        built = records.build_record(1, ["T08"], {"base": "0123456789ab"}, [{**run, "review_stand_in": STAND_IN}], verdicts)
        problems = records.validate_record({**built, "runs": [{**run, "review_stand_in": "gpt-7-nova"}]})

        # then
        self.assertEqual(built["runs"][0]["review_stand_in"], STAND_IN)
        self.assertTrue(any("review_stand_in" in problem for problem in problems))


if __name__ == "__main__":
    unittest.main()
