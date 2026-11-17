"""Tests that `cli.py record --rule-groups` builds the rule_groups section from the run folders of seeded campaigns."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))

from harness import cli, records, rule_record  # noqa: E402

SESSION = "instructions/session/"
SESSION_TEXT = {
    SESSION + "core.md": "# Core\n\n- Rule removed one alpha beta.\n- Rule kept two gamma delta.\n",
    SESSION + "common.md": "# Common\n\n- Rule stock three epsilon zeta.\n- Rule missing four eta theta.\n- Rule unmeasured five iota kappa.\n",
    SESSION + "claude-code.md": "# Claude Code only\n\nHost claude only rule here.\n",
    SESSION + "codex.md": "# Codex only\n\nHost codex only rule here.\n",
    "scripts/reader.py": 'NOTE = "Rule unmeasured five iota kappa"\n',
    "evals/e2e/note.md": "Rule missing four eta theta\n",
}
RULES = {"T91": ("core.md", "Rule removed one"), "T92": ("core.md", "Rule kept two"),
         "T93": ("common.md", "Rule stock three"), "T94": ("common.md", "Rule missing four")}
HOSTS = ("claude", "codex")
RUN_LINE = {"type": "system", "subtype": "init", "model": "claude-opus-5-5"}


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")


def make_repo(folder: Path) -> tuple[Path, str]:
    repo = folder / "repo"
    repo.mkdir(parents=True)
    git = ["git", "-c", "user.name=Demo Dev", "-c", "user.email=dev@example.com", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q", "-b", "main"], cwd=repo, check=True)
    for name, text in SESSION_TEXT.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    subprocess.run([*git, "add", "."], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], cwd=repo, check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
    return repo, sha


def seed_run(root: Path, task: str, variant: str, host: str, rep: int, failing: str | None = None, status: str = "complete") -> None:
    """One run folder shaped like the harness writes it; `failing` names the one required check that fails."""
    folder = root / "camp" / "results" / task / variant / ("codex" if host == "codex" else "") / f"rep{rep}"
    run_id = f"{task}-{variant}-{host + '-' if host == 'codex' else ''}r{rep}"
    write(folder / "run.json", {"run_id": run_id, "task": task, "variant": variant, "rep": rep, "status": status, "host": host})
    claude = host == "claude"
    write(folder / "metrics.json", {
        "success": failing is None, "wall_seconds": 100.0, "host": host, "plugin": {"subagent_models": {}},
        "session": {"model": "gpt-6.1-sol", "effort": "high"},
        "cost": {"claude_total_cost_usd": 1.0 if claude else None, "claude_runner_list_cost_usd": 0.0, "claude_list_cost_usd": 0.0,
                 "codex_list_cost_usd_estimate": None if claude else 1.0}})
    write(folder / "grade" / "grade.json", {"checks": [{"id": name, "required": True, "passed": name != failing, "data": {}}
                                                       for name in ("a", "b")]})
    write(folder / "command.json", {"argv": ["claude", "-p", "--model", "claude-opus-5-5", "--effort", "high", "--", "prompt"]})
    (folder / "stream.jsonl").write_text(json.dumps(RUN_LINE) + "\n", encoding="utf-8")
    write(folder / "env.json", {"codex_session_model": "gpt-6.1-sol", "codex_session_effort": "high"})
    write(folder / "view.json", {"tool_calls": []})


def seed_campaign(root: Path, sha: str) -> None:
    variants = ["stock", "full", "rm-removed", "rm-kept", "rm-missing"]
    for task in RULES:
        for host in HOSTS:
            seed_run(root, task, "stock", host, 1, failing="a" if (task, host) == ("T93", "codex") else None)
            seed_run(root, task, "full", host, 1)
    for host in HOSTS:
        for rep in (1, 2):
            seed_run(root, "T91", "rm-removed", host, rep)
            seed_run(root, "T92", "rm-kept", host, rep, failing="b" if (host, rep) == ("codex", 2) else None)
            if (host, rep) != ("codex", 2):
                seed_run(root, "T94", "rm-missing", host, rep)
    scheduled = [{"task": task, "variant": name, "host": host} for task in RULES for name in variants for host in HOSTS]
    write(root / "camp" / "campaign.json", {"tasks": list(RULES), "variants": variants, "scheduled": scheduled,
                                            "inputs": {"variant_shas": {"stock": "none", "full": sha, "rm-removed": sha, "rm-kept": sha,
                                                                        "rm-missing": sha}}})


def seed_files(folder: Path) -> tuple[Path, Path]:
    tasks, variants = folder / "tasks", folder / "variants"
    for task, (file, start) in RULES.items():
        write(tasks / f"{task}.json", {"id": task, "checks": [{"id": "a", "required": True}, {"id": "b", "required": True}],
                                       "rules": [{"check": name, "file": SESSION + file, "starts_with": start} for name in ("a", "b")]})
    write(variants / "stock.json", {"name": "stock", "plugin": "none"})
    write(variants / "full.json", {"name": "full", "ref": "HEAD"})
    for name, (file, start) in {"rm-removed": RULES["T91"], "rm-kept": RULES["T92"], "rm-missing": RULES["T94"]}.items():
        write(variants / f"{name}.json", {"name": name, "ref": "HEAD", "remove": [{"file": SESSION + file, "starts_with": start}]})
    return tasks, variants


class RuleGroupRecordTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo, self.sha = make_repo(self.root / "git")
        self.tasks, self.variants = seed_files(self.root)
        seed_campaign(self.root / "runs", self.sha)

    def record(self, *extra: str):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["record", "--run-root", str(self.root / "runs"), "--campaign", "camp", "--issue", "101", "--before", "stock",
                             "--after", "full", "--rule-groups", "--tasks", ",".join(RULES), "--records-dir", str(self.root / "records"),
                             "--repo-root", str(self.repo), "--tasks-root", str(self.tasks), "--variants-root", str(self.variants), *extra])
        return code, out.getvalue(), err.getvalue()

    def groups(self) -> dict[str, dict]:
        written = json.loads((self.root / "records" / "101.json").read_text(encoding="utf-8"))
        self.assertEqual(records.validate_record(written), [])
        return {group["id"].split("::", 1)[1]: group for group in written["rule_groups"]["groups"]}

    def test_한_캠페인의_스톡_플러그인_제거_실행으로_네_판정을_모두_기록에_쓴다(self):
        """given 제거됨, 제거 실패, 스톡 실패, 측정되지 않음 묶음이 시드된 캠페인 when record --rule-groups를 실행하면 then 각 묶음이 그 판정으로 검증을 통과하는 기록에 담긴다."""
        # given / when
        code, out, err = self.record()

        # then
        self.assertEqual((code, err), (0, ""))
        found = self.groups()
        self.assertEqual(found["Rule removed one alpha"]["verdict"], "removed")
        self.assertEqual(found["Rule kept two gamma"]["verdict"], "kept as needed")
        self.assertIn("removal run", found["Rule kept two gamma"]["step"])
        self.assertEqual(found["Rule stock three epsilon"]["verdict"], "kept as needed")
        self.assertIn("stock", found["Rule stock three epsilon"]["step"])
        self.assertEqual(found["Rule unmeasured five iota"]["verdict"], "kept as unmeasured")
        self.assertIn("1 removed", out)

    def test_제거된_묶음의_기록은_바이트와_과제와_호스트별_스톡_결과와_제거_실행별_검사를_담는다(self):
        """given 제거로 판정된 묶음 when 기록을 읽으면 then 바이트, 연결된 과제, 호스트별 스톡 결과, 호스트마다 두 번의 제거 실행과 성립한 비교가 있다."""
        # given
        self.record()

        # when
        group = self.groups()["Rule removed one alpha"]

        # then
        self.assertEqual((group["bytes"], group["tasks"], group["checks"]), (len("- Rule removed one alpha beta."), ["T91"], ["T91/a", "T91/b"]))
        self.assertEqual(group["stock"], {host: {"T91/a": True, "T91/b": True} for host in HOSTS})
        self.assertEqual([(run["host"], run["rep"], set(run["checks"].values())) for run in group["removal_runs"]],
                         [(host, rep, {True}) for host in HOSTS for rep in (1, 2)])
        self.assertIs(group["host_comparison"], True)
        self.assertEqual(group["references"]["relied_on"], None)

    def test_제거_실행_하나가_실패하면_그_묶음은_필요로_남고_실패한_검사가_실행에_보인다(self):
        """given 코덱스 두 번째 제거 실행이 b 검사를 실패한 캠페인 when 기록하면 then 그 묶음은 필요이고 그 검사만 False다."""
        # given
        self.record()

        # when
        runs = self.groups()["Rule kept two gamma"]["removal_runs"]

        # then
        self.assertEqual([run["checks"] for run in runs if (run["host"], run["rep"]) == ("codex", 2)], [{"T92/a": True, "T92/b": False}])

    def test_빠진_제거_실행이_있는_묶음은_측정된_것으로_보고하지_않고_아직_측정되지_않음이다(self):
        """given 코덱스 두 번째 제거 실행이 폴더에 없는 캠페인 when 기록하면 then 그 묶음은 아직 측정되지 않음이고 실행은 한 번만 있다."""
        # given
        self.record()

        # when
        group = self.groups()["Rule missing four eta"]

        # then
        self.assertEqual(group["verdict"], "not yet measured")
        self.assertEqual([(run["host"], run["rep"]) for run in group["removal_runs"] if run["host"] == "codex"], [("codex", 1)])

    def test_끝나지_않은_제거_실행은_검사_값이_null이고_성공으로_세지_않는다(self):
        """given 두 번째 클로드 제거 실행의 상태가 timed_out이 아니라 interrupted인 캠페인 when 기록하면 then 그 실행의 검사는 null이고 묶음은 아직 측정되지 않음이다."""
        # given
        seed_run(self.root / "runs", "T91", "rm-removed", "claude", 2, status="interrupted")

        # when
        self.record()
        group = self.groups()["Rule removed one alpha"]

        # then
        self.assertEqual(group["verdict"], "not yet measured")
        self.assertEqual([set(run["checks"].values()) for run in group["removal_runs"] if (run["host"], run["rep"]) == ("claude", 2)], [{None}])

    def test_제거_변형이_한_묶음이_아니라_여러_묶음이나_다른_개정을_가리키면_기록을_쓰지_않는다(self):
        """given 두 묶음을 지우는 제거 변형과 다른 개정의 변형 when 기록하면 then 각각 오류이고 기록 파일이 없다."""
        # given
        bad = {"name": "rm-kept", "ref": "HEAD", "remove": [{"file": SESSION + "core.md", "starts_with": "Rule kept two"},
                                                            {"file": SESSION + "core.md", "starts_with": "Rule removed one"}]}
        write(self.variants / "rm-kept.json", bad)

        # when
        code, _, err = self.record()

        # then
        self.assertEqual(code, 1)
        self.assertIn("exactly one rule group", err)
        self.assertFalse((self.root / "records" / "101.json").exists())
        subprocess.run(["git", "-c", "user.name=D", "-c", "user.email=d@example.com", "commit", "-q", "--allow-empty", "-m", "next"],
                       cwd=self.repo, check=True)
        write(self.variants / "rm-kept.json", {"name": "rm-kept", "ref": "HEAD", "remove": bad["remove"][:1]})
        code, _, err = self.record()
        self.assertEqual(code, 1)
        self.assertIn("not of another one", err)

    def test_참조_검색은_다른_파일에_첫_단어가_있는_묶음을_의존으로_적고_평가_폴더와_자기_파일은_보지_않는다(self):
        """given 스크립트가 첫 단어를 담은 묶음과 evals 폴더에만 있는 묶음 when 기록하면 then 앞의 것만 의존이 적히고 검색한 폴더에 evals가 없다."""
        # given
        self.record()

        # when
        found = self.groups()

        # then
        self.assertEqual(found["Rule unmeasured five iota"]["references"]["relied_on"], "scripts/reader.py")
        self.assertIn("scripts", found["Rule unmeasured five iota"]["references"]["searched"])
        self.assertNotIn("evals", found["Rule unmeasured five iota"]["references"]["searched"])
        self.assertIsNone(found["Rule missing four eta"]["references"]["relied_on"])
        hits = rule_record.reference_hits(self.repo, "HEAD", [{"id": "g", "file": SESSION + "core.md", "kind": "part", "starts_with": "Rule removed one alpha"}])[1]
        self.assertEqual(hits["g"], [])


if __name__ == "__main__":
    unittest.main()
