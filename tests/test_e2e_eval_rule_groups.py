"""Tests for the stock variant, the removal of named rule groups from an export, and the decision on rule groups."""

from __future__ import annotations

import contextlib
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

from harness import cli, codex_host, command, inputs, pilot_check, plugin_export, records, rule_groups, runner  # noqa: E402
from harness.config import HarnessConfig  # noqa: E402

COMMON = "instructions/session/common.md"
SAMPLE = (
    "# Common\n\nIntro paragraph one that stays here.\n\n## Alpha\n\n- First bullet rule that spans\n  two lines of text.\n"
    "- Second bullet rule stays too.\n\nStandalone paragraph rule text.\n\n## Beta\n\n- Beta bullet rule number one.\n\n"
    "### Deeper\n\nDeeper paragraph rule text.\n\n## Gamma\n\nGamma paragraph rule text.\n"
)
WITHIN_CAP_ENV = {"CLAUDE_PLUGIN_OPTION_REVIEW_MODEL": "gpt-6.1-sol", "HEI5ENBUG_REVIEW_MODEL": "gpt-6.1-sol"}


def make_repo(folder: str, files: dict[str, str]) -> Path:
    repo = Path(folder) / "repo"
    repo.mkdir(parents=True)
    git = ["git", "-c", "user.name=Demo Dev", "-c", "user.email=dev@example.com", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q", "-b", "main"], cwd=repo, check=True)
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    subprocess.run([*git, "add", "."], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def run_cli(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(args))
    return code, out.getvalue(), err.getvalue()


class RemovalExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(self.tmp.name, {COMMON: SAMPLE, "skills/demo/SKILL.md": "demo\n"})
        self.runs = Path(self.tmp.name) / "runs"

    def export(self, remove):
        return plugin_export.export_plugin(self.repo, self.runs, "HEAD", remove)

    def exported_text(self, info) -> str:
        return (Path(info["path"]) / COMMON).read_text(encoding="utf-8")

    def test_제목_항목은_그_절_전체만_지우고_나머지_바이트는_그대로_둔다(self):
        """given 제목 항목 하나 when 내보내면 then 그 제목의 절(하위 절 포함)만 없고 다른 절과 파일은 원본과 같다."""
        # given
        remove = [{"file": COMMON, "heading": "## Beta"}]

        # when
        text = self.exported_text(self.export(remove))

        # then
        self.assertEqual(text, SAMPLE.replace("## Beta\n\n- Beta bullet rule number one.\n\n### Deeper\n\nDeeper paragraph rule text.\n\n", ""))

    def test_첫_단어_항목은_이어지는_줄을_가진_목록_항목과_문단을_각각_하나만_지운다(self):
        """given 목록 항목과 문단의 첫 단어 when 내보내면 then 여러 줄 항목과 그 문단만 없고 이웃 항목은 남는다."""
        # given
        remove = [{"file": COMMON, "starts_with": "First bullet rule that spans"}, {"file": COMMON, "starts_with": "Standalone paragraph"}]

        # when
        info = self.export(remove)
        text = self.exported_text(info)

        # then
        self.assertNotIn("First bullet", text)
        self.assertNotIn("two lines of text", text)
        self.assertNotIn("Standalone", text)
        self.assertIn("- Second bullet rule stays too.\n\n## Beta", text)
        self.assertEqual([item["lines"] for item in info["removed"]], [2, 1])

    def test_아무것도_찾지_못하는_항목은_내보내기를_실패시키고_폴더를_남기지_않는다(self):
        """given 없는 제목, 없는 첫 단어, 없는 파일 when 내보내면 then 각각 remove를 말하는 ExportError이고 내보낸 폴더가 없다."""
        # given
        cases = [[{"file": COMMON, "heading": "## Missing"}], [{"file": COMMON, "starts_with": "No such rule"}],
                 [{"file": "nope.md", "starts_with": "Anything"}]]

        for remove in cases:
            with self.subTest(remove=remove):
                # when / then
                with self.assertRaises(plugin_export.ExportError) as caught:
                    self.export(remove)
                self.assertIn("remove", str(caught.exception))
        self.assertEqual(list((self.runs / "plugins").iterdir()), [])

    def test_둘_이상의_부분이나_절에_맞는_항목은_맞은_수를_알리며_실패한다(self):
        """given 같은 말로 시작하는 두 항목과 같은 제목의 두 절 when 내보내면 then 맞은 수 2를 메시지에 담아 실패한다."""
        # given
        text = "# T\n\n- Same start one.\n- Same start two.\n\n## Notes\n\nA.\n\n## Notes\n\nB.\n"
        repo = make_repo(str(Path(self.tmp.name) / "two"), {COMMON: text})

        for entry in ({"file": COMMON, "starts_with": "Same start"}, {"file": COMMON, "heading": "Notes"}):
            with self.subTest(entry=entry):
                # when / then
                with self.assertRaises(plugin_export.ExportError) as caught:
                    plugin_export.export_plugin(repo, self.runs, "HEAD", [entry])
                self.assertIn("matches 2 parts", str(caught.exception))

    def test_제거한_내보내기는_원본_내보내기와_다른_폴더를_쓰고_항목을_기록하며_다시_쓸_수_있다(self):
        """given 같은 개정의 전체 내보내기와 제거 내보내기 when 만들면 then 폴더가 다르고 기록에 항목이 있고, 같은 항목은 재사용된다."""
        # given
        remove = [{"file": COMMON, "heading": "## Gamma"}]

        # when
        whole = self.export(None)
        first = self.export(remove)
        again = self.export(remove)
        other = self.export([{"file": COMMON, "heading": "## Beta"}])

        # then
        self.assertEqual(len({whole["path"], first["path"], other["path"]}), 3)
        self.assertEqual(again["path"], first["path"])
        self.assertEqual(first["remove"], remove)
        self.assertNotEqual(first["content_digest"], whole["content_digest"])
        self.assertIn("Gamma", self.exported_text(whole))


class VariantValidationTest(unittest.TestCase):
    def test_remove_항목은_상대_파일과_첫_단어_또는_제목_하나를_문자열로_가져야_한다(self):
        """given 잘못된 remove 항목들 when 변형을 검증하면 then 모두 ConfigError이고 올바른 항목은 공백이 정리돼 통과한다."""
        # given
        bad = [[], [{"file": COMMON}], [{"file": COMMON, "starts_with": "a b", "heading": "## A"}], [{"file": "/etc/x.md", "heading": "## A"}],
               [{"file": "../x.md", "heading": "## A"}], [{"file": COMMON, "starts_with": ""}], [{"file": COMMON, "heading": "## A"}] * 2, "text"]

        # when / then
        for remove in bad:
            with self.subTest(remove=remove), self.assertRaises(command.ConfigError):
                command.validate_variant({"name": "v", "ref": "HEAD", "remove": remove})
        good = command.validate_variant({"name": "v", "ref": "HEAD", "remove": [{"file": COMMON, "starts_with": "Use  parallel\nsubagents"}]})
        self.assertEqual(good["remove"], [{"file": COMMON, "starts_with": "Use parallel subagents"}])

    def test_플러그인_없음_변형은_개정과_제거를_가질_수_없고_다른_값은_거부한다(self):
        """given plugin none 변형 when ref나 remove를 함께 주거나 다른 plugin 값을 주면 then ConfigError, ref 없이는 통과한다."""
        # given / when
        stock = command.validate_variant({"name": "stock", "plugin": "none"})

        # then
        self.assertEqual((command.loads_plugin(stock), stock["ref"], stock["remove"]), (False, "", []))
        for body in ({"ref": "HEAD"}, {"remove": [{"file": COMMON, "heading": "## A"}]}, {"plugin": "off"}):
            with self.subTest(body=body), self.assertRaises(command.ConfigError):
                command.validate_variant({"name": "stock", "plugin": "none", **body} if "plugin" not in body else {"name": "stock", **body})
        with self.assertRaises(command.ConfigError):
            command.validate_variant({"name": "loaded"})


class StockVariantTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        folder = self.root / "variants"
        folder.mkdir()
        (folder / "stock.json").write_text(json.dumps({"name": "stock", "plugin": "none"}), encoding="utf-8")
        (folder / "full.json").write_text(json.dumps({"name": "full", "ref": "HEAD", "env": WITHIN_CAP_ENV}), encoding="utf-8")
        self.folder = folder

    def plan(self) -> str:
        code, out, err = run_cli("run", "--campaign", "demo", "--hosts", "claude,codex", "--tasks", "T08", "--dry-run", "--variants", "stock,full",
                                 "--run-root", str(self.root / "runs"), "--variants-root", str(self.folder))
        self.assertEqual((code, err), (0, ""))
        return out

    def test_드라이런은_플러그인_없음_변형에_plugin_dir_없는_Claude_명령과_플러그인을_올리지_않는_Codex_명령을_출력한다(self):
        """given 플러그인 없음 변형과 전체 변형 when 두 호스트로 드라이런하면 then 없음 변형만 --plugin-dir와 Codex 설치 명령이 없다."""
        # given / when
        blocks = {line.split()[1]: block for block in self.plan().split("\n\n[")[1:] for line in [block.splitlines()[0]]}

        # then
        stock_claude, stock_codex = blocks["T08-stock-r1"], blocks["T08-stock-codex-r1"]
        self.assertNotIn("--plugin-dir", stock_claude)
        self.assertIn("claude -p", stock_claude)
        self.assertNotIn("marketplace", stock_codex)
        self.assertNotIn("plugin add", stock_codex)
        self.assertIn("codex exec", stock_codex)
        self.assertIn("--plugin-dir", blocks["T08-full-r1"])
        self.assertIn("marketplace add", blocks["T08-full-codex-r1"])

    def test_Codex_준비는_플러그인_없음이면_명령을_하나도_실행하지_않고_빈_설치_기록을_남긴다(self):
        """given 인증 파일만 있는 홈 when 플러그인 폴더 없이 prepare_home을 부르면 then 외부 명령은 실행되지 않고 steps가 빈 기록이다."""
        # given
        source = self.root / "auth-home"
        source.mkdir()
        (source / "auth.json").write_text("{}", encoding="utf-8")
        result_dir = self.root / "result"

        # when
        with mock.patch.object(codex_host.subprocess, "run") as spawned:
            record = codex_host.prepare_home(HarnessConfig(run_root=self.root), result_dir, None, {"PATH": "/usr/bin"}, source_home=source)

        # then
        spawned.assert_not_called()
        self.assertEqual((record["steps"], record["plugin"]), ([], "none"))
        self.assertEqual(json.loads((result_dir / codex_host.SETUP_RECORD).read_text(encoding="utf-8"))["steps"], [])

    def test_플러그인이_없어야_하는_실행에서_수출_플러그인이_보이면_오염으로_기록한다(self):
        """given 인라인 플러그인이 올라온 init when 없음 실행으로 판정하면 then 오염 메시지와 infra_failed이고, 전체 실행은 그대로 완료다."""
        # given
        plugin = {"name": "hei5enbug-agent-setup", "source": "hei5enbug-agent-setup@inline", "path": "/tmp/work/export"}
        facts = {"plugins": [plugin], "has_result": True, "terminal_reason": None}

        # when / then
        self.assertIn("hei5enbug-agent-setup@inline", runner.contamination_error(facts, loaded=False))
        self.assertEqual(runner.decide_status(facts, None, False, loaded=False), "infra_failed")
        self.assertIsNone(runner.contamination_error(facts))
        self.assertEqual(runner.decide_status(facts, None, False), "complete")

    def test_파일럿_검사는_플러그인_없음_실행의_plugin_dir를_실패로_보고_전체_실행에서는_요구한다(self):
        """given plugin-dir가 있는 명령줄과 없는 명령줄 when 검사하면 then 없음 실행은 있는 쪽을 실패, 전체 실행은 없는 쪽을 실패로 본다."""
        # given
        base = ["claude", "-p", "--settings", "s", "--permission-prompt-tool", "mcp__eval_approver__approve", "--max-budget-usd", "1",
                "--strict-mcp-config", "--setting-sources", "project,local", "--", "prompt"]
        with_dir = [*base[:2], "--plugin-dir", "/tmp/work/export", *base[2:]]

        # when / then
        self.assertEqual(pilot_check.command_problems(base, loaded=False), [])
        self.assertEqual(pilot_check.command_problems(with_dir, loaded=False), ["--plugin-dir passed to a run that loads no plugin"])
        self.assertEqual(pilot_check.command_problems(base), ["missing --plugin-dir"])

    def test_캠페인_입력은_플러그인_없음_변형의_개정을_none으로_적고_git을_부르지_않는다(self):
        """given 저장소가 아닌 repo_root when 없음 변형의 입력을 계산하면 then 개정은 none이고 오류 없이 지문이 나온다."""
        # given
        cfg = HarnessConfig(run_root=self.root, variants_root=self.folder, repo_root=self.root)

        # when
        found = inputs.compute_inputs(cfg, [], ["stock"], {"stock": plugin_export.stock_plugin()})

        # then
        self.assertEqual(found["variant_shas"], {"stock": "none"})
        self.assertTrue(found["fingerprint"])


TASKS = [
    {"id": "T91", "checks": [{"id": "alpha", "required": True}, {"id": "beta", "required": True}, {"id": "note", "required": False}],
     "rules": [{"check": "alpha", "file": COMMON, "starts_with": "First bullet rule"},
               {"check": "beta", "file": COMMON, "starts_with": "Standalone paragraph"}]},
    {"id": "T92", "checks": [{"id": "gamma", "required": True}],
     "rules": [{"check": "gamma", "file": COMMON, "starts_with": "Beta bullet rule number one"}]},
]


def reader(text: str):
    return lambda file: text if file == COMMON else None


class GroupMapTest(unittest.TestCase):
    def test_묶음은_파일의_모든_항목과_문단이며_가장_짧은_고유_첫_단어와_자기_바이트를_가진다(self):
        """given 두 항목이 같은 말로 시작하는 파일 when 묶음을 읽으면 then 첫 단어는 서로 구별되고 바이트는 각 항목의 줄만 센다."""
        # given
        text = "# T\n\n- Before the first thing, read x.\n- Before the second thing, read y.\n\nTail paragraph here now.\n"

        # when
        groups = rule_groups.read_groups(lambda file: text, ("a.md",))

        # then
        self.assertEqual([group["starts_with"] for group in groups],
                         ["Before the first thing,", "Before the second thing,", "Tail paragraph here now."])
        self.assertEqual([group["bytes"] for group in groups], [len("- Before the first thing, read x."), len("- Before the second thing, read y."),
                                                              len("Tail paragraph here now.")])

    def test_연결된_검사가_없는_묶음은_측정되지_않음이고_절은_모든_부분이_연결됐을_때만_묶음이_된다(self):
        """given 규칙 두 개가 Alpha의 두 부분을 모두, Beta의 한 부분만 연결할 때 when 지도를 만들면 then Alpha 절만 묶음이고 나머지는 측정되지 않음이다."""
        # given
        rules = rule_groups.task_rules(TASKS[:1])

        # when
        mapped = rule_groups.group_map(reader(SAMPLE), rules, (COMMON,))

        # then
        by_start = {group["starts_with"]: group for group in mapped if group["kind"] != "section"}
        self.assertEqual(by_start["First bullet rule that"]["checks"], ["T91/alpha"])
        self.assertEqual(by_start["Second bullet rule stays"]["status"], "unmeasured")
        self.assertEqual(by_start["Gamma paragraph rule text."]["checks"], [])
        self.assertEqual([group["section"] for group in mapped if group["kind"] == "section"], [])

        # when
        full = rules + [{"task": "T91", "check": "beta", "file": COMMON, "starts_with": "Second bullet rule"}]
        sections = [group for group in rule_groups.group_map(reader(SAMPLE), full, (COMMON,)) if group["kind"] == "section"]

        # then
        self.assertEqual([item["section"] for item in sections], ["Alpha"])
        self.assertEqual(sections[0]["checks"], ["T91/alpha", "T91/beta"])
        self.assertEqual(sections[0]["bytes"], len("## Alpha\n\n- First bullet rule that spans\n  two lines of text.\n- Second bullet rule stays too.\n\nStandalone paragraph rule text."))

    def test_규칙의_첫_단어가_어떤_묶음에도_맞지_않으면_지도를_만들지_않고_실패한다(self):
        """given 없는 규칙 when 지도를 만들면 then RemovalError이고 과제와 검사가 메시지에 있다."""
        # given
        rules = [{"task": "T91", "check": "alpha", "file": COMMON, "starts_with": "No such rule"}]

        # when / then
        with self.assertRaises(rule_groups.RemovalError) as caught:
            rule_groups.group_map(reader(SAMPLE), rules, (COMMON,))
        self.assertIn("T91: alpha", str(caught.exception))


class TaskRulesTest(unittest.TestCase):
    def test_커밋된_과제의_규칙은_모든_필수_검사를_덮고_현재_세션_지침에서_하나의_부분으로_풀린다(self):
        """given 저장소의 과제 파일 when 규칙 목록을 검사하면 then 문제가 없고 일곱 기준 과제가 모두 규칙을 가진다."""
        # given
        tasks = rule_groups.load_tasks(REPO_ROOT / "evals/e2e/tasks")
        removed = {group["id"] for path in (REPO_ROOT / "evals/e2e/records").glob("*.json")
                   for group in (json.loads(path.read_text(encoding="utf-8")).get("rule_groups") or {}).get("groups", [])
                   if group["verdict"] == rule_groups.REMOVED}
        baseline = None
        for path in (REPO_ROOT / "evals/e2e/records").glob("*.json"):
            section = json.loads(path.read_text(encoding="utf-8")).get("rule_groups")
            if section:
                revision = json.loads(path.read_text(encoding="utf-8"))["variants"][section["plugin"]]["revision"]
                baseline = rule_groups.revision_reader(REPO_ROOT, revision)

        # when
        problems = rule_groups.rules_problems(tasks, rule_groups.tree_reader(REPO_ROOT), baseline, removed)

        # then
        self.assertEqual(problems, [])
        self.assertEqual(sorted(task["id"] for task in tasks if "rules" in task), ["T02", "T05", "T07", "T08", "T09", "T12", "T20"])

    def test_기준_개정에_없는_규칙과_제거_기록_없이_현재_개정에서_사라진_규칙과_필수가_아닌_검사는_문제다(self):
        """given 시드 과제 when 개정마다 다른 텍스트로 검사하면 then 기준에 없는 규칙, 기록 없는 삭제, 규칙 없는 필수 검사, 필수 아닌 검사를 각각 알린다."""
        # given
        current = SAMPLE.replace("- Beta bullet rule number one.\n\n", "")
        tasks = [*TASKS, {"id": "T93", "checks": [{"id": "x", "required": True}, {"id": "y", "required": True}, {"id": "n", "required": False}],
                          "rules": [{"check": "x", "file": COMMON, "starts_with": "Intro paragraph one"},
                                    {"check": "n", "file": COMMON, "starts_with": "Intro paragraph one"}]}]
        beta = f"{COMMON}::Beta bullet rule number"

        # when
        gone = rule_groups.rules_problems(tasks, reader(current), reader(SAMPLE))
        recorded = rule_groups.rules_problems(tasks, reader(current), reader(SAMPLE), {beta})
        late = rule_groups.rules_problems(tasks[:2], reader(current), reader(SAMPLE.replace("Beta bullet rule number one.", "Other.")))

        # then
        self.assertEqual([item for item in gone if item.startswith("T92")], ["T92: gamma -> instructions/session/common.md \"Beta bullet rule number one\" matches 0 parts in the current revision"])
        self.assertEqual([item for item in recorded if item.startswith("T92")], [])
        self.assertIn("T93: required check y has no rule", gone)
        self.assertIn("T93: rule names n, which is not a required check", gone)
        self.assertEqual([item for item in late if item.startswith("T92")],
                         ["T92: gamma -> instructions/session/common.md \"Beta bullet rule number one\" matches 0 parts in the baseline revision",
                          "T92: gamma -> instructions/session/common.md \"Beta bullet rule number one\" matches 0 parts in the current revision"])


def candidate(name: str, size: int, checks=("T01/a",), stock=True, removal=True, comparison=True, **extra):
    """A seeded group: stock results per host, two removal runs per host, and the host comparison of the removal."""
    run = {check: removal for check in checks}
    return {"id": name, "bytes": size, "checks": list(checks), "stock": {host: {check: stock for check in checks} for host in ("claude", "codex")},
            "removal": {host: [dict(run), dict(run)] for host in ("claude", "codex")}, "host_comparison": comparison, **extra}


class DecisionTest(unittest.TestCase):
    def verdicts(self, *groups):
        return {item["id"]: item["verdict"] for item in rule_groups.decide(list(groups))}

    def test_스톡과_두_번의_제거_실행이_두_호스트에서_모두_통과하고_호스트_비교가_성립하면_제거한다(self):
        """given 스톡 통과, 호스트마다 두 번 통과한 제거 실행, 성립한 호스트 비교 when 판정하면 then 제거이고 그 단계가 이유를 담는다."""
        # given / when
        decided = rule_groups.decide([candidate("g", 100)])

        # then
        self.assertEqual(decided[0]["verdict"], "removed")
        self.assertIn("both removal runs on both hosts", decided[0]["step"])

    def test_제거_실행_하나라도_실패하거나_호스트_비교가_깨지면_남기고_비교가_미정이면_측정되지_않음이다(self):
        """given 제거 실행 하나 실패, 비교 불성립, 비교 미정 when 판정하면 then 필요, 필요, 아직 측정되지 않음이다."""
        # given
        failing = candidate("fail", 100)
        failing["removal"]["codex"][1] = {"T01/a": False}

        # when
        got = self.verdicts(failing, candidate("gap", 90, comparison=False), candidate("open", 80, comparison=None))

        # then
        self.assertEqual(got, {"fail": "kept as needed", "gap": "kept as needed", "open": "not yet measured"})

    def test_스톡에서_한_호스트의_검사가_실패하면_제거_실행_없이_남기고_결과가_없으면_아직_측정되지_않음이다(self):
        """given 스톡 실패 검사가 한 호스트에 있는 묶음과 스톡 결과가 없는 묶음 when 판정하면 then 필요와 아직 측정되지 않음이고 제거 실행은 보지 않는다."""
        # given
        stock_fail = candidate("fail", 100, removal=True)
        stock_fail["stock"]["codex"]["T01/a"] = False
        missing = candidate("missing", 90)
        del missing["stock"]["claude"]["T01/a"]

        # when
        decided = {item["id"]: item for item in rule_groups.decide([stock_fail, missing])}

        # then
        self.assertEqual((decided["fail"]["verdict"], decided["missing"]["verdict"]), ("kept as needed", "not yet measured"))
        self.assertIn("stock", decided["fail"]["step"])

    def test_연결된_검사가_없으면_측정되지_않음으로_남기고_세_과제를_넘으면_아직_측정되지_않음이다(self):
        """given 검사 없는 묶음과 네 과제에 걸친 묶음 when 판정하면 then 측정되지 않음 유지와 아직 측정되지 않음이다."""
        # given
        none = candidate("none", 100, checks=())
        wide = candidate("wide", 90, checks=("T01/a", "T02/a", "T03/a", "T04/a"))

        # when / then
        self.assertEqual(self.verdicts(none, wide), {"none": "kept as unmeasured", "wide": "not yet measured"})

    def test_다른_규칙이나_훅이_기대는_묶음은_제거_실행을_보지_않고_남긴다(self):
        """given 기대는 곳이 기록된 묶음 when 판정하면 then 제거 실행이 모두 통과해도 필요로 남고 그 이유를 적는다."""
        # given
        relied = candidate("relied", 100, relied_on="another rule applies the reply rules of this group")

        # when
        decided = rule_groups.decide([relied])

        # then
        self.assertEqual((decided[0]["verdict"], decided[0]["step"]), ("kept as needed", "another rule, hook, or script relies on it"))

    def test_열한_번째_후보는_큰_묶음부터_열을_채운_뒤_아직_측정되지_않음으로_기록한다(self):
        """given 크기가 다른 후보 열한 개 when 판정하면 then 가장 작은 열한 번째만 아직 측정되지 않음이고 나머지 열 개는 제거다."""
        # given
        groups = [candidate(f"g{index:02d}", 200 - index) for index in range(11)][::-1]

        # when
        decided = rule_groups.decide(groups)

        # then
        self.assertEqual([item["id"] for item in decided], [f"g{index:02d}" for index in range(11)])
        self.assertEqual([item["verdict"] for item in decided], ["removed"] * 10 + ["not yet measured"])

    def test_제거된_묶음과_겹치는_묶음은_따로_제거하지_않고_아직_측정되지_않음으로_둔다(self):
        """given 절 묶음과 그 안의 부분 묶음 when 판정하면 then 큰 절이 제거되고 부분은 아직 측정되지 않음이다."""
        # given
        part = candidate("part", 50, members=["part"])
        section = candidate("section", 120, members=["part", "other"])

        # when / then
        self.assertEqual(self.verdicts(part, section), {"section": "removed", "part": "not yet measured"})


def record_with(group: dict) -> dict:
    run = {"case": "T01", "variant": "stock", "host": "claude", "models": {"main": {"model": "claude-opus-5-5", "effort": "high"}},
           "checks": {"a": True}, "wall_seconds": 1.0, "cost_usd": 1.0}
    return {"issue": 101, "cases": ["T01"], "variants": {"stock": {"revision": "none"}, "plugin": {"revision": "abc123"}}, "runs": [run],
            "verdicts": [{"case": "T01", "verdict": "pass", "step": "demo"}],
            "rule_groups": {"stock": "stock", "plugin": "plugin", "groups": [group]}}


def listed_group(**changes) -> dict:
    runs = [{"host": host, "rep": rep, "checks": {"T01/a": True}} for host in ("claude", "codex") for rep in (1, 2)]
    return {"id": "f.md::Rule one", "file": "f.md", "bytes": 10, "checks": ["T01/a"], "stock": {"claude": True, "codex": True},
            "removal_runs": runs, "verdict": "removed", "references": {"searched": ["skills/", "scripts/"], "relied_on": None}, **changes}


class RecordSectionTest(unittest.TestCase):
    def test_제거된_묶음의_기록은_검색한_참조와_의존_없음과_호스트마다_두_번의_제거_실행을_가져야_한다(self):
        """given 완전한 제거 기록과 빠진 기록 when 검증하면 then 완전한 쪽은 통과하고 빠진 쪽은 각각 문제를 낸다."""
        # given / when
        complete = records.validate_record(record_with(listed_group()))
        no_search = records.validate_record(record_with(listed_group(references={"searched": [], "relied_on": None})))
        relied = records.validate_record(record_with(listed_group(references={"searched": ["scripts/"], "relied_on": "a hook"})))
        one_run = records.validate_record(record_with(listed_group(removal_runs=listed_group()["removal_runs"][:3])))

        # then
        self.assertEqual(complete, [])
        for problems in (no_search, relied):
            self.assertEqual([item for item in problems if "references searched" in item], ["rule_groups.groups[0] is removed without a record of the references searched and of no reliance"])
        self.assertEqual(one_run, ["rule_groups.groups[0] is removed without 2 removal runs on each host"])

    def test_측정되지_않음_묶음에_연결된_검사가_있거나_모르는_판정과_변형_이름이면_거부한다(self):
        """given 잘못된 판정, 연결 검사가 있는 측정되지 않음, 없는 변형, 사례 밖 과제 when 검증하면 then 각각 문제를 낸다."""
        # given
        unknown = record_with(listed_group(verdict="maybe"))
        unmeasured = record_with(listed_group(verdict="kept as unmeasured"))
        no_variant = record_with(listed_group())
        no_variant["rule_groups"]["plugin"] = "missing"
        other_case = record_with(listed_group(checks=["T09/a"]))

        # when
        found = [records.validate_record(item) for item in (unknown, unmeasured, no_variant, other_case)]

        # then
        self.assertIn("rule_groups.groups[0] verdict is not one of removed, kept as needed, kept as unmeasured, not yet measured", found[0])
        self.assertIn("rule_groups.groups[0] is kept as unmeasured but has mapped checks", found[1])
        self.assertIn("rule_groups.plugin names a variant that is not in variants", found[2])
        self.assertIn("rule_groups.groups[0] names a check of a task that is not a case", found[3])


class RuleGroupsCommandTest(unittest.TestCase):
    def test_명령은_네_세션_파일의_모든_묶음을_바이트와_연결된_검사와_함께_출력하고_과제의_모든_규칙을_연결한다(self):
        """given 저장소의 과제와 세션 지침 when rule-groups --json을 실행하면 then 네 파일이 모두 있고 과제 규칙의 검사가 빠짐없이 한 묶음에 연결된다."""
        # given
        expected = {f"{rule['task']}/{rule['check']}" for rule in rule_groups.task_rules(rule_groups.load_tasks(REPO_ROOT / "evals/e2e/tasks"))}

        # when
        code, out, err = run_cli("rule-groups", "--json")
        groups = json.loads(out)

        # then
        self.assertEqual((code, err), (0, ""))
        self.assertEqual({group["file"] for group in groups}, set(rule_groups.SESSION_FILES))
        self.assertTrue(all(group["bytes"] > 0 for group in groups))
        self.assertEqual({check for group in groups if group["kind"] != "section" for check in group["checks"]}, expected)
        self.assertTrue(all((group["status"] == "unmeasured") == (not group["checks"]) for group in groups))


if __name__ == "__main__":
    unittest.main()
