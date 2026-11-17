"""Tests for the Opus worker tier rule, the worker-case results file, and the shipped state they decide."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))
sys.path.insert(0, str(REPO_ROOT / "evals/e2e/worker-cases"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import opus_candidate  # noqa: E402
from harness import cli, records, worker_cases  # noqa: E402
from test_claude_worker_contract import differing_bodies, split_definition  # noqa: E402

OPUS_NAME = "hei5enbug-agent-setup:opus-worker"
ROUTE_FILES = ("instructions/claude-agents.md", "instructions/model-routing.md")

CASES = {
    "A1": ["security", "concurrency"], "A2": ["security"], "A3": ["security", "hook-guard"],
    "B1": ["concurrency"], "B2": ["components", "public-contract"], "B3": ["hook-guard"],
}


def opus_state(root: Path) -> tuple[tuple[bool, bool, bool], list[str]]:
    """Whether the checkout holds the Opus agent, its registry entry, and route text, and the criteria that text names."""
    registry = json.loads((root / "config/model-registry.json").read_text(encoding="utf-8"))["claude_agents"]
    sentences = []
    for relative in ROUTE_FILES:
        text = " ".join((root / relative).read_text(encoding="utf-8").split())
        sentences.extend(part for part in re.split(r"(?<=[.;])\s", text) if "opus-worker" in part)
    named = " ".join(sentences)
    present = ((root / "agents/opus-worker.md").is_file(), OPUS_NAME in registry, bool(sentences))
    return present, [item for item in worker_cases.CRITERIA if worker_cases.CRITERION_PHRASES[item] in named]


def results_of(opus: set[str], sonnet: set[str], measured: bool = True) -> dict:
    cases = {task: {"sonnet": {"passed": task in sonnet}, "opus": {"passed": task in opus}} for task in CASES}
    return {"issue": 87, "measured": measured, "cases": cases}


def full_results(passed: dict[str, set[str]], cost: dict[str, float | None]) -> dict:
    """A complete results file for the CASES ids, for the validator."""
    cases = {task: {name: {"passed": task in passed[name], "model": model, "effort": "high",
                           "cost_usd": cost[name] if cost[name] is None else cost[name] / len(CASES)}
                    for name, model in worker_cases.MODELS.items()} for task in CASES}
    totals = {}
    for name in worker_cases.MODELS:
        solved = len(passed[name])
        total = cost[name]
        totals[name] = {"cost_usd": total, "solved": solved,
                        "cost_per_solved_task": round(total / solved, 6) if solved and total is not None else None}
    return {"issue": 87, "measured": True,
            "models": {name: {"model": model, "effort": "high"} for name, model in worker_cases.MODELS.items()},
            "cases": cases, "totals": totals}


class TierRuleTest(unittest.TestCase):
    def test_Opus가_더_많이_통과한_기준만_어려운_작업으로_센다(self):
        """Opus 2건 대 Sonnet 1건은 어려운 작업이고, 동률, Opus 패배, 해당 사례가 없는 기준은 아니다."""
        # given
        opus = {"A1", "A2", "B1", "B3"}
        sonnet = {"A1", "B1", "B2", "B3"}

        # when
        hard = worker_cases.hard_criteria(results_of(opus, sonnet), CASES)

        # then
        self.assertEqual(hard, ["security"])

    def test_동률과_Opus_패배와_사례_없음은_어려운_작업이_아니다(self):
        """같은 수를 통과하거나 Sonnet이 더 많이 통과하거나 그 기준의 사례가 없으면 빈 목록이다."""
        # given
        tie = results_of({"B1"}, {"A1"})
        lost = results_of({"B1"}, {"B1", "B3"})
        no_cases = {task: criteria for task, criteria in CASES.items() if "security" not in criteria}

        # when
        outcomes = (worker_cases.hard_criteria(tie, CASES), worker_cases.hard_criteria(lost, CASES),
                    worker_cases.hard_criteria(results_of({"B1"}, set()), no_cases))

        # then
        self.assertEqual(outcomes[:2], ([], []))
        self.assertEqual(outcomes[2], ["concurrency"])
        self.assertNotIn("security", outcomes[2])

    def test_측정하지_않은_결과와_기록_없는_사례는_어려운_작업을_만들지_않는다(self):
        """measured가 False이거나 결과에 사례가 없으면 Opus가 이긴 것으로 세지 않는다."""
        # given
        unmeasured = results_of(set(CASES), set(), measured=False)
        empty = {"issue": 87, "measured": True, "cases": {}}

        # when
        outcomes = (worker_cases.hard_criteria(unmeasured, CASES), worker_cases.hard_criteria(empty, CASES))

        # then
        self.assertEqual(outcomes, ([], []))


class ShippedStateTest(unittest.TestCase):
    def test_저장소는_규칙이_어려운_기준을_돌려줄_때만_Opus_worker_파일_등록_경로_문구를_가진다(self):
        """출하된 결과에 규칙을 적용해, 기준이 하나라도 있을 때에만 정의, 레지스트리 항목, 경로 문구가 있고 문구는 그 기준만 말한다."""
        # given
        cases = worker_cases.load_cases()
        results = worker_cases.read_results()

        # when
        hard = worker_cases.hard_criteria(results, cases)
        present, named = opus_state(REPO_ROOT)

        # then
        self.assertEqual(worker_cases.results_problems(results, cases), [])
        self.assertEqual(present, (bool(hard),) * 3)
        self.assertEqual(named, hard)

    def test_기준_이름과_사례_라벨은_한_곳에서_정의된다(self):
        """모든 사례의 기준 라벨이 규칙의 다섯 기준 안에 있고, 어느 기준도 빠지지 않는다."""
        # given
        cases = worker_cases.load_cases()

        # when
        labelled = {criterion for criteria in cases.values() for criterion in criteria}

        # then
        self.assertEqual(labelled, set(worker_cases.CRITERIA))
        self.assertEqual(set(worker_cases.CRITERION_PHRASES), set(worker_cases.CRITERIA))


class ResultsFileTest(unittest.TestCase):
    PASSED = {"sonnet": {"A1", "B1"}, "opus": {"A1", "A2", "B1", "B3"}}

    def test_검증은_모델별_합계_해결_수_해결당_비용을_사례와_맞춰_본다(self):
        """사례별 통과·비용으로 계산한 합계와 해결당 비용이 맞는 파일은 문제가 없다."""
        # given
        results = full_results(self.PASSED, {"sonnet": 6.0, "opus": 12.0})

        # when
        problems = worker_cases.results_problems(results, CASES)

        # then
        self.assertEqual(problems, [])
        self.assertEqual(results["totals"]["opus"]["cost_per_solved_task"], 3.0)

    def test_한_건도_풀지_못한_모델의_해결당_비용은_null이다(self):
        """해결 수가 0이면 cost_per_solved_task는 null이어야 하고 숫자를 적으면 문제로 잡힌다."""
        # given
        results = full_results({"sonnet": set(), "opus": {"A1"}}, {"sonnet": 6.0, "opus": 12.0})
        wrong = copy.deepcopy(results)
        wrong["totals"]["sonnet"]["cost_per_solved_task"] = 0.0

        # when
        outcomes = (worker_cases.results_problems(results, CASES), worker_cases.results_problems(wrong, CASES))

        # then
        self.assertIsNone(results["totals"]["sonnet"]["cost_per_solved_task"])
        self.assertEqual(outcomes[0], [])
        self.assertEqual(len(outcomes[1]), 1)

    def test_합계_모델_사고_강도_지역_경로가_틀린_파일은_문제로_잡힌다(self):
        """합계가 사례와 다르거나 기록된 모델과 effort가 고정값과 다르거나 지역 경로가 있으면 각각 문제가 된다."""
        # given
        base = full_results(self.PASSED, {"sonnet": 6.0, "opus": 12.0})
        bad_total, bad_model, bad_path = (copy.deepcopy(base) for _ in range(3))
        bad_total["totals"]["opus"]["solved"] += 1
        bad_model["cases"]["A1"]["opus"]["effort"] = "xhigh"
        bad_path["note"] = "/home/test/run"

        # when
        problems = [worker_cases.results_problems(item, CASES) for item in (bad_total, bad_model, bad_path)]

        # then
        self.assertTrue(all(problems), problems)

    def test_측정_전_파일은_대기_형태만_허용한다(self):
        """measured가 False인 파일은 대기 형태와 정확히 같을 때만 유효하다."""
        # given
        pending = dict(worker_cases.PENDING)
        filled = {**pending, "cases": {"A1": {}}}

        # when
        outcomes = (worker_cases.results_problems(pending, CASES), worker_cases.results_problems(filled, CASES))

        # then
        self.assertEqual(outcomes[0], [])
        self.assertTrue(outcomes[1])


def seed(root: Path, task: str, variant: str, model: str, effort: str, passed: bool, cost: float | None,
         roles: dict | None = None) -> None:
    folder = root / "camp" / "results" / task / variant / "rep1"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run.json").write_text(json.dumps(
        {"run_id": f"{task}-{variant}-r1", "task": task, "variant": variant, "rep": 1, "status": "complete",
         "host": "claude"}), encoding="utf-8")
    (folder / "metrics.json").write_text(json.dumps({
        "success": passed, "wall_seconds": 60.0, "host": "claude", "plugin": {"subagent_models": roles or {}},
        "cost": {"claude_total_cost_usd": cost, "claude_runner_list_cost_usd": 0.0, "claude_list_cost_usd": 0.0,
                 "codex_list_cost_usd_estimate": None}}), encoding="utf-8")
    (folder / "grade").mkdir(exist_ok=True)
    (folder / "grade" / "grade.json").write_text(json.dumps({"checks": [
        {"id": "hidden-tests", "required": True, "passed": passed, "data": {}}]}), encoding="utf-8")
    (folder / "command.json").write_text(json.dumps({"argv": ["claude", "-p", "--model", model, "--effort", effort]}),
                                         encoding="utf-8")
    (folder / "stream.jsonl").write_text(json.dumps({"type": "system", "subtype": "init", "model": model}) + "\n",
                                         encoding="utf-8")
    (folder / "env.json").write_text("{}", encoding="utf-8")
    (folder / "view.json").write_text(json.dumps({"tool_calls": []}), encoding="utf-8")


class WorkerResultsCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.cases = worker_cases.load_cases()

    def seed_all(self, opus_passes: set[str], **override) -> None:
        for task in self.cases:
            seed(self.root, task, "worker-sonnet", "claude-sonnet-5-5", "high", False, 1.0)
            kwargs = {"model": "claude-opus-5-5", "effort": "high", "passed": task in opus_passes, "cost": 2.0,
                      **(override if task == "T68" else {})}
            seed(self.root, task, "worker-opus", **kwargs)

    def run_cli(self) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        target = self.root / "results.json"
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["worker-results", "--run-root", str(self.root), "--campaign", "camp", "--out", str(target)])
        return code, out.getvalue(), err.getvalue()

    def test_끝난_실행의_호스트_기록에서_결과_파일과_어려운_기준을_쓴다(self):
        """모델과 effort를 호스트 기록에서 읽어 사례별 통과, 총비용, 해결당 비용을 쓰고, 한 건도 못 푼 Sonnet의 해결당 비용은 null이다."""
        # given
        self.seed_all({"T68", "T70"})

        # when
        code, out, err = self.run_cli()

        # then
        results = json.loads((self.root / "results.json").read_text(encoding="utf-8"))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(worker_cases.results_problems(results, self.cases), [])
        self.assertEqual(results["cases"]["T68"]["opus"],
                         {"passed": True, "model": "claude-opus-5-5", "effort": "high", "cost_usd": 2.0})
        self.assertEqual(results["totals"]["sonnet"], {"cost_usd": 10.0, "solved": 0, "cost_per_solved_task": None})
        self.assertEqual(results["totals"]["opus"], {"cost_usd": 20.0, "solved": 2, "cost_per_solved_task": 10.0})
        self.assertIn("hard work criteria: security, hook-guard", out)

    def test_호스트_기록의_모델이나_effort가_고정값과_다르면_결과를_쓰지_않는다(self):
        """Opus 실행의 기록이 다른 모델이나 다른 effort를 보이면 오류로 끝나고 파일을 만들지 않는다."""
        for override in ({"model": "claude-sonnet-5-5"}, {"effort": "xhigh"}):
            with self.subTest(override):
                # given
                self.seed_all({"T68"}, **override)

                # when
                code, _, err = self.run_cli()

                # then
                self.assertEqual(code, 1)
                self.assertIn("T68", err)
                self.assertFalse((self.root / "results.json").exists())

    def test_다른_역할을_시작했거나_실행이_빠진_사례는_결과를_쓰지_않는다(self):
        """서브에이전트가 돈 실행이나 실행이 없는 사례가 있으면 오류로 끝나고 파일을 만들지 않는다."""
        for name, expected in (("roles", "started other roles"), ("missing", "no finished, graded run")):
            with self.subTest(name):
                # given
                self.seed_all({"T68"}, **({"roles": {"worker": "claude-sonnet-5-5"}} if name == "roles" else {}))
                if name == "missing":
                    for path in (self.root / "camp" / "results" / "T70" / "worker-opus").rglob("*"):
                        if path.is_file():
                            path.unlink()

                # when
                code, _, err = self.run_cli()

                # then
                self.assertEqual(code, 1)
                self.assertIn(expected, err)
                self.assertFalse((self.root / "results.json").exists())


class OpusCandidateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        for folder in ("agents", "config", "instructions", "docs/ko/agents"):
            shutil.copytree(REPO_ROOT / folder, self.root / folder, ignore=shutil.ignore_patterns("session", "__pycache__"))

    def test_후보를_적용하면_본문이_같은_Opus_high_정의와_Sonnet과_같은_대체_항목과_기준만_말하는_문구가_생긴다(self):
        """qualified 기준 둘로 적용하면 정의, 레지스트리, 경로 문구가 생기고 저장소 상태 규칙(셋 모두 있음, 문구는 그 기준만)을 만족한다."""
        # given
        criteria = ["security", "concurrency"]
        before = opus_state(self.root)

        # when
        changed = opus_candidate.apply(self.root, criteria)

        # then
        registry = json.loads((self.root / "config/model-registry.json").read_text(encoding="utf-8"))["claude_agents"]
        sonnet = registry["hei5enbug-agent-setup:sonnet-worker"]
        opus = registry[OPUS_NAME]
        metadata, _ = split_definition(self.root / "agents/opus-worker.md")
        self.assertEqual(before, ((False, False, False), []))
        self.assertEqual(sorted(changed), sorted([
            "agents/opus-worker.md", "docs/ko/agents/opus-worker.ko.md", "config/model-registry.json",
            "instructions/claude-agents.md", "instructions/model-routing.md"]))
        self.assertEqual(opus_state(self.root), ((True, True, True), criteria))
        self.assertEqual(differing_bodies(self.root / "agents/worker.md", [self.root / "agents/opus-worker.md"]), [])
        self.assertEqual((metadata["name"], metadata["model"], metadata["effort"]), ("opus-worker", "claude-opus-5-5", "high"))
        self.assertEqual({**opus, "model": sonnet["model"]}, sonnet)
        self.assertEqual(list(registry)[list(registry).index("hei5enbug-agent-setup:sonnet-worker") + 1], OPUS_NAME)

    def test_후보는_빈_기준이나_모르는_기준이나_이미_있는_정의를_거부하고_아무것도_쓰지_않는다(self):
        """기준이 없거나 모르는 이름이거나 정의가 이미 있으면 오류이고 어떤 파일도 바뀌지 않는다."""
        # given
        def snapshot() -> dict[Path, bytes]:
            return {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

        before = snapshot()

        # when / then
        for criteria in ([], ["speed"]):
            with self.subTest(criteria):
                with self.assertRaises(opus_candidate.ApplyError):
                    opus_candidate.apply(self.root, criteria)
                self.assertEqual(snapshot(), before)
        opus_candidate.apply(self.root, ["security"])
        applied = snapshot()
        with self.assertRaises(opus_candidate.ApplyError):
            opus_candidate.apply(self.root, ["security"])
        self.assertEqual(snapshot(), applied)

    def test_후보_파일은_현재_worker_정의에서_이름과_모델만_다르다(self):
        """후보 본문이 worker.md와 달라지거나 Sonnet 정의에서 갈라지면 이 테스트가 잡아 적용 전에 후보를 다시 만들게 한다."""
        # given
        candidate = REPO_ROOT / "evals/e2e/worker-cases/opus-candidate/opus-worker.md.candidate"
        mirror = REPO_ROOT / "evals/e2e/worker-cases/opus-candidate/opus-worker.ko.md.candidate"

        # when
        expected = (REPO_ROOT / "agents/sonnet-worker.md").read_text(encoding="utf-8").replace(
            "name: sonnet-worker", "name: opus-worker").replace("model: claude-sonnet-5-5", "model: claude-opus-5-5")
        expected_mirror = (REPO_ROOT / "docs/ko/agents/sonnet-worker.ko.md").read_text(encoding="utf-8").replace(
            "sonnet-worker", "opus-worker").replace("claude-sonnet-5-5", "claude-opus-5-5")

        # then
        self.assertEqual(candidate.read_text(encoding="utf-8"), expected)
        self.assertEqual(mirror.read_text(encoding="utf-8"), expected_mirror)
        self.assertEqual(differing_bodies(REPO_ROOT / "agents/worker.md", [candidate]), [])


if __name__ == "__main__":
    unittest.main()
