"""Tests for the record command of the end-to-end evaluation harness."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))

from harness import cli, records, verdict  # noqa: E402

RUN_LINE = {"type": "system", "subtype": "init", "model": "claude-opus-5-5"}
RUNNER_STATUS = {"runner": "codex", "role": "reviewer", "model": "gpt-6.1-sol", "effort": "high", "exit": 0}


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")


def seed_run(root: Path, task: str, variant: str, host: str, rep: int, passed: bool, wall, cost, status: str = "complete",
             grade_error: str | None = None) -> None:
    """One run folder shaped like the harness writes it; `cost` is Claude spend on Claude Code, the Codex estimate on Codex."""
    folder = root / "camp" / "results" / task / variant / ("codex" if host == "codex" else "") / f"rep{rep}"
    run_id = f"{task}-{variant}-{host + '-' if host == 'codex' else ''}r{rep}"
    write(folder / "run.json", {"run_id": run_id, "task": task, "variant": variant, "rep": rep, "status": status, "host": host})
    claude = host == "claude"
    write(folder / "metrics.json", {
        "success": passed, "wall_seconds": wall, "host": host, **({"grade_error": grade_error} if grade_error else {}), "plugin": {"subagent_models": {"worker": "claude-sonnet-5-5"} if claude else {}},
        "session": {"model": "gpt-6.1-sol", "effort": "high"},
        "cost": {"claude_total_cost_usd": cost if claude else None, "claude_runner_list_cost_usd": 0.0,
                 "claude_list_cost_usd": 0.0, "codex_list_cost_usd_estimate": None if claude else cost}})
    write(folder / "grade" / "grade.json", {"checks": [
        {"id": "hidden-tests", "required": True, "passed": passed, "data": {}},
        {"id": "ran-review", "required": False, "passed": True, "data": {}}]})
    write(folder / "command.json", {"argv": ["claude", "-p", "--model", "claude-opus-5-5", "--effort", "high", "--", "prompt"]})
    (folder / "stream.jsonl").write_text(json.dumps(RUN_LINE) + "\n", encoding="utf-8")
    write(folder / "env.json", {"codex_session_model": "gpt-6.1-sol", "codex_session_effort": "high"})
    write(folder / "view.json", {"tool_calls": [{"result_text": json.dumps(RUNNER_STATUS)}]})


def seed_campaign(root: Path) -> None:
    write(root / "camp" / "campaign.json", {"inputs": {"variant_shas": {"base": "0123456789abcdef", "changed": "fedcba9876543210"}}})
    for task, after_codex_passes, after_codex_cost in (("T08", True, 1.6), ("T02", False, 1.0)):
        for host, wall_before, wall_after, cost_before, cost_after in (
            ("claude", 100.0, 100.0, 1.0, 1.0), ("codex", 120.0, 110.0, 1.3, after_codex_cost)):
            seed_run(root, task, "base", host, 1, True, wall_before, cost_before)
            passes = after_codex_passes if host == "codex" else True
            seed_run(root, task, "changed", host, 1, passes, wall_after, cost_after)


def run_cli(root: Path, *extra: str):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["record", "--run-root", str(root), "--campaign", "camp", "--issue", "92", "--before", "base",
                         "--after", "changed", "--records-dir", str(root / "records"), *extra])
    return code, out.getvalue(), err.getvalue()


class RecordCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_두_호스트의_끝난_실행으로_검증을_통과하는_기록을_쓰고_판정이_비교_함수와_같다(self):
        """given 두 사례의 전후 변형이 두 호스트에서 끝난 캠페인 when record를 실행하면 then 검증을 통과하는 기록이 쓰이고 판정이 compare와 같다."""
        # given
        seed_campaign(self.root)
        expected = verdict.compare([
            {"id": "T02", "before": {"claude": [{"passed": True, "wall_seconds": 100.0, "cost_usd": 1.0}],
                                     "codex": [{"passed": True, "wall_seconds": 120.0, "cost_usd": 1.3}]},
             "after": {"claude": [{"passed": True, "wall_seconds": 100.0, "cost_usd": 1.0}],
                       "codex": [{"passed": False, "wall_seconds": 110.0, "cost_usd": 1.0}]}},
            {"id": "T08", "before": {"claude": [{"passed": True, "wall_seconds": 100.0, "cost_usd": 1.0}],
                                     "codex": [{"passed": True, "wall_seconds": 120.0, "cost_usd": 1.3}]},
             "after": {"claude": [{"passed": True, "wall_seconds": 100.0, "cost_usd": 1.0}],
                       "codex": [{"passed": True, "wall_seconds": 110.0, "cost_usd": 1.6}]}}])

        # when
        code, out, err = run_cli(self.root)

        # then
        self.assertEqual((code, err), (0, ""))
        written = json.loads((self.root / "records" / "92.json").read_text(encoding="utf-8"))
        self.assertEqual(records.validate_record(written), [])
        self.assertEqual(written["cases"], ["T02", "T08"])
        by_case = {(item["case"], item.get("measure")): item["verdict"] for item in written["verdicts"]}
        for item in expected["cases"]:
            self.assertEqual(by_case[(item["case"], None)], item["verdict"])
            self.assertEqual(by_case[(item["case"], "quality")], item["quality"]["verdict"])
            for measure in item["measures"]:
                self.assertEqual(by_case[(item["case"], measure["measure"])], measure["verdict"])
        self.assertEqual((by_case[("T02", None)], by_case[("T08", None)]), ("fail", "repeat"))
        self.assertEqual(by_case[("T08", "cost_usd")], "repeat")
        self.assertEqual(by_case[("T08", "wall_seconds")], "pass")
        self.assertIn("repeat: T08 cost_usd", out)
        self.assertNotIn("repeat: T08 wall_seconds", out)
        self.assertIn("T02: fail", out)

    def test_기록은_변형별_개정과_실행별_역할_모델과_노력도를_호스트_기록에서_읽어_담는다(self):
        """given 호스트 기록에 모델이 적힌 실행 when record를 실행하면 then 기록의 모델과 개정이 그 기록과 같다."""
        # given
        seed_campaign(self.root)

        # when
        run_cli(self.root, "--tasks", "T08")

        # then
        written = json.loads((self.root / "records" / "92.json").read_text(encoding="utf-8"))
        self.assertEqual(written["variants"], {"base": {"revision": "0123456789ab"}, "changed": {"revision": "fedcba987654"}})
        models = {(run["variant"], run["host"]): run["models"] for run in written["runs"]}
        self.assertEqual(models[("changed", "claude")]["main"], {"model": "claude-opus-5-5", "effort": "high"})
        self.assertEqual(models[("changed", "claude")]["subagent:worker"], {"model": "claude-sonnet-5-5", "effort": "not measured"})
        self.assertEqual(models[("changed", "codex")]["main"], {"model": "gpt-6.1-sol", "effort": "high"})
        self.assertEqual(models[("changed", "codex")]["role_runner:reviewer"], {"model": "gpt-6.1-sol", "effort": "high"})
        self.assertEqual({run["case"] for run in written["runs"]}, {"T08"})

    def test_비용_값이_없는_실행은_통과가_아니라_측정되지_않음으로_판정한다(self):
        """given 한 실행의 비용이 기록에 없는 캠페인 when record를 실행하면 then 비용 판정은 not measured이고 통과가 아니다."""
        # given
        seed_campaign(self.root)
        seed_run(self.root, "T08", "changed", "codex", 1, True, 110.0, None)

        # when
        code, out, _ = run_cli(self.root, "--tasks", "T08")

        # then
        self.assertEqual(code, 0)
        written = json.loads((self.root / "records" / "92.json").read_text(encoding="utf-8"))
        by_measure = {item.get("measure"): item["verdict"] for item in written["verdicts"]}
        self.assertEqual((by_measure["cost_usd"], by_measure[None]), ("not measured", "not measured"))
        self.assertIn("overall: not measured", out)

    def test_개선_주장은_첫_쌍이_낮으면_다섯_번까지_계속하라고_알린다(self):
        """given 첫 쌍이 낮은 호스트 두 곳 when --claim wall_seconds로 record를 실행하면 then continue to five를 판정과 출력에 남긴다."""
        # given
        seed_campaign(self.root)
        seed_run(self.root, "T08", "changed", "claude", 1, True, 90.0, 1.0)
        seed_run(self.root, "T08", "changed", "codex", 1, True, 100.0, 1.3)

        # when
        code, out, _ = run_cli(self.root, "--tasks", "T08", "--claim", "wall_seconds")

        # then
        self.assertEqual(code, 0)
        written = json.loads((self.root / "records" / "92.json").read_text(encoding="utf-8"))
        claim = next(item for item in written["verdicts"] if item.get("measure") == "claim")
        self.assertEqual(claim["verdict"], "continue to five")
        self.assertIn("repeat: T08 claim: continue to five", out)

    def test_허용_밖_모델이_기록에_있으면_기록을_쓰지_않고_실패한다(self):
        """given 호스트 기록의 주 모델이 상한 밖인 실행 when record를 실행하면 then 종료 코드 1이고 기록 파일이 없다."""
        # given
        seed_campaign(self.root)
        folder = self.root / "camp" / "results" / "T08" / "changed" / "rep1"
        (folder / "stream.jsonl").write_text(json.dumps({**RUN_LINE, "model": "claude-fable-5-2"}) + "\n", encoding="utf-8")

        # when
        code, _, err = run_cli(self.root, "--tasks", "T08")

        # then
        self.assertEqual(code, 1)
        self.assertIn("outside the allowed models", err)
        self.assertFalse((self.root / "records" / "92.json").exists())

    def test_같은_변형을_전후로_주거나_모르는_측정값을_주면_거부한다(self):
        """given 같은 이름의 전후 변형 또는 모르는 측정값 when record를 실행하면 then 종료 코드 1이다."""
        # given
        seed_campaign(self.root)

        # when
        same = run_cli(self.root, "--after", "base")
        unknown = run_cli(self.root, "--claim", "tokens")

        # then
        self.assertEqual((same[0], unknown[0]), (1, 1))


def rollout(role: str | None, model: str, effort: str, start: str) -> str:
    rows = [{"type": "session_meta", "payload": {"timestamp": start, **({"agent_role": role} if role else {})}},
            {"type": "turn_context", "payload": {"model": model, "effort": effort}}]
    return "".join(json.dumps(row) + "\n" for row in rows)


def seed_attempt(root: Path, task: str, variant: str, host: str, rep: int, number: int, run: dict | None, metrics: dict | None) -> None:
    folder = (root / "camp" / "results" / task / variant / ("codex" if host == "codex" else "") / "attempts" / f"rep{rep}" / str(number))
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in (("run.json", run), ("metrics.json", metrics)):
        if data is not None:
            write(folder / name, data)


class RequestedCasesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        seed_campaign(self.root)

    def test_끝나지_않은_요청_사례는_빠지지_않고_측정되지_않음으로_남아_전체가_통과가_아니다(self):
        """given T08은 통과하고 요청한 T20의 모든 실행이 아직 running일 때 when --tasks T08,T20으로 record하면 then T20이 사례에 남고 not measured이며 overall은 pass가 아니다."""
        # given
        for variant in ("base", "changed"):
            for host in ("claude", "codex"):
                seed_run(self.root, "T20", variant, host, 1, True, None, None, status="running")
        seed_run(self.root, "T08", "changed", "codex", 1, True, 110.0, 1.0)

        # when
        code, out, _ = run_cli(self.root, "--tasks", "T08,T20")

        # then
        self.assertEqual(code, 0)
        written = json.loads((self.root / "records" / "92.json").read_text(encoding="utf-8"))
        self.assertEqual(written["cases"], ["T08", "T20"])
        by_case = {(item["case"], item.get("measure")): item["verdict"] for item in written["verdicts"]}
        self.assertEqual((by_case[("T08", None)], by_case[("T20", None)]), ("pass", "not measured"))
        self.assertIn("overall: not measured", out)

    def test_채점이_실패했거나_실행이_하나도_없는_요청_사례도_측정되지_않음으로_남는다(self):
        """given 요청한 T05는 채점 오류가 있고 T11은 실행이 없을 때 when record하면 then 두 사례 모두 기록에 있고 not measured다."""
        # given
        for host in ("claude", "codex"):
            seed_run(self.root, "T05", "base", host, 1, True, 100.0, 1.0)
            seed_run(self.root, "T05", "changed", host, 1, True, 100.0, 1.0, grade_error="rubric failed" if host == "codex" else None)

        seed_run(self.root, "T08", "changed", "codex", 1, True, 110.0, 1.0)

        # when
        code, out, _ = run_cli(self.root, "--tasks", "T08,T05,T11")

        # then
        self.assertEqual(code, 0)
        written = json.loads((self.root / "records" / "92.json").read_text(encoding="utf-8"))
        self.assertEqual(written["cases"], ["T05", "T08", "T11"])
        by_case = {(item["case"], item.get("measure")): item["verdict"] for item in written["verdicts"]}
        self.assertEqual((by_case[("T05", None)], by_case[("T11", None)]), ("not measured", "not measured"))
        self.assertIn("overall: not measured", out)


class ClaimOverallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        write(self.root / "camp" / "campaign.json", {"inputs": {"variant_shas": {"base": "0123456789abcdef", "changed": "fedcba9876543210"}}})

    def test_기각된_개선_주장은_사례와_전체_판정을_통과로_두지_않는다(self):
        """given 다섯 번 모두 통과하지만 이후가 두 호스트에서 똑같이 느려져 격차는 그대로일 때 when --claim wall_seconds로 record하면 then 사례와 overall이 reject다."""
        # given
        for rep in range(1, 6):
            for host in ("claude", "codex"):
                seed_run(self.root, "T08", "base", host, rep, True, 100.0, 1.0)
                seed_run(self.root, "T08", "changed", host, rep, True, 120.0, 1.0)

        # when
        code, out, _ = run_cli(self.root, "--tasks", "T08", "--claim", "wall_seconds")

        # then
        self.assertEqual(code, 0)
        written = json.loads((self.root / "records" / "92.json").read_text(encoding="utf-8"))
        by_measure = {item.get("measure"): item["verdict"] for item in written["verdicts"]}
        self.assertEqual((by_measure["wall_seconds"], by_measure["claim"], by_measure[None]), ("pass", "reject", "reject"))
        self.assertIn("T08: reject", out)
        self.assertIn("overall: reject", out)

    def test_끝나지_않은_개선_주장은_그_상태가_사례와_전체_판정이다(self):
        """given 첫 쌍만 낮아 아직 다섯 번을 채우지 않은 주장일 때 when record하면 then 사례와 overall이 continue to five이고 pass가 아니다."""
        # given
        for host in ("claude", "codex"):
            seed_run(self.root, "T08", "base", host, 1, True, 100.0, 1.0)
            seed_run(self.root, "T08", "changed", host, 1, True, 80.0, 1.0)

        # when
        _, out, _ = run_cli(self.root, "--tasks", "T08", "--claim", "wall_seconds")

        # then
        self.assertIn("overall: continue to five", out)


class CodexChildModelsTest(unittest.TestCase):
    def test_Codex_자식_세션의_역할_모델_노력도를_롤아웃에서_읽고_같은_역할의_두_번째는_따로_둔다(self):
        """given 메인과 scout 둘, worker 하나의 롤아웃이 있을 때 when 실행의 모델을 읽으면 then 자식마다 역할과 모델과 노력도가 들어가고 두 번째 scout는 #2로 따로 남는다."""
        # given
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for name, text in (("rollout-1-main.jsonl", rollout(None, "gpt-6.1-sol", "high", "2026-11-13T01:00:00Z")),
                               ("rollout-2-scout.jsonl", rollout("scout", "gpt-5.6-luna", "xhigh", "2026-11-13T01:01:00Z")),
                               ("rollout-3-worker.jsonl", rollout("worker", "gpt-6.1-sol", "high", "2026-11-13T01:02:00Z")),
                               ("rollout-4-scout.jsonl", rollout("scout", "gpt-5.6-luna", "high", "2026-11-13T01:03:00Z"))):
                (folder / "codex").mkdir(exist_ok=True)
                (folder / "codex" / name).write_text(text, encoding="utf-8")
            write(folder / "env.json", {"codex_session_model": "gpt-6.1-sol", "codex_session_effort": "high"})

            # when
            roles = records.run_models(folder, "codex", {})

        # then
        self.assertEqual(roles["main"], {"model": "gpt-6.1-sol", "effort": "high"})
        self.assertEqual(roles["codex_child:scout"], {"model": "gpt-5.6-luna", "effort": "xhigh"})
        self.assertEqual(roles["codex_child:scout#2"], {"model": "gpt-5.6-luna", "effort": "high"})
        self.assertEqual(roles["codex_child:worker"], {"model": "gpt-6.1-sol", "effort": "high"})
        self.assertEqual(len(roles), 4)


class AttemptWallTimeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        seed_campaign(self.root)

    def written(self):
        return json.loads((self.root / "records" / "92.json").read_text(encoding="utf-8"))

    def test_앞선_시도의_측정된_시간은_기록의_실행_시간에_더해진다(self):
        """given 첫 시도가 1000초에 시간 초과로 보관되고 다시 돌린 실행이 100초일 때 when record하면 then 그 실행의 wall_seconds는 1100이다."""
        # given
        seed_attempt(self.root, "T08", "changed", "codex", 1, 1, {"status": "timed_out"}, {"wall_seconds": 1000.0})

        # when
        run_cli(self.root, "--tasks", "T08")

        # then
        runs = {(run["variant"], run["host"]): run["wall_seconds"] for run in self.written()["runs"]}
        self.assertEqual((runs[("changed", "codex")], runs[("changed", "claude")]), (1110.0, 100.0))

    def test_시간을_알_수_없는_앞선_시도가_있으면_시간은_측정되지_않음이다(self):
        """given 기간을 알 수 없는 앞선 시도가 보관된 실행일 때 when record하면 then 그 실행의 wall_seconds는 null이고 시간 판정은 not measured다."""
        # given
        seed_attempt(self.root, "T08", "changed", "codex", 1, 1, {"status": "infra_failed"}, None)

        # when
        run_cli(self.root, "--tasks", "T08")

        # then
        written = self.written()
        runs = {(run["variant"], run["host"]): run["wall_seconds"] for run in written["runs"]}
        by_measure = {item.get("measure"): item["verdict"] for item in written["verdicts"] if item["case"] == "T08"}
        self.assertIsNone(runs[("changed", "codex")])
        self.assertEqual(by_measure["wall_seconds"], "not measured")


class CommittedRecordsTest(unittest.TestCase):
    def test_저장소에_커밋된_기록은_모두_검증을_통과한다(self):
        """given evals/e2e/records 폴더 when 모든 기록 파일을 검증하면 then 문제가 없다. 폴더가 비어 있어도 통과한다."""
        # given
        folder = records.RECORDS_DIR

        # when
        problems = records.validate_directory(folder)

        # then
        self.assertEqual(problems, {})


if __name__ == "__main__":
    unittest.main()
