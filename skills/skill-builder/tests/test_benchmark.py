"""Benchmark aggregation: token units, incomplete runs, and paired deltas."""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))

from scripts import aggregate_benchmark as ab  # noqa: E402


def write_run(root: Path, eval_id: int, config: str, run: int, grading: dict | None, timing: dict | None = None) -> Path:
    run_dir = root / f"eval-{eval_id}" / config / f"run-{run}"
    run_dir.mkdir(parents=True, exist_ok=True)
    if grading is not None:
        (run_dir / "grading.json").write_text(json.dumps(grading))
    if timing is not None:
        (run_dir / "timing.json").write_text(json.dumps(timing))
    return run_dir


def grading(pass_rate: float, output_chars: int | None = None, seconds: float | None = None) -> dict:
    passed = int(pass_rate)
    data = {
        "expectations": [
            {"text": "criterion", "passed": bool(passed), "evidence": "synthetic"}
        ],
        "summary": {
            "pass_rate": pass_rate,
            "total": 1,
            "passed": passed,
            "failed": 1 - passed,
        },
    }
    if output_chars is not None:
        data["execution_metrics"] = {"output_chars": output_chars}
    if seconds is not None:
        data["timing"] = {"total_duration_seconds": seconds}
    return data


class TokenUnitTest(unittest.TestCase):
    def test_tokens_come_from_timing_json_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_run(root, 1, "with_skill", 1, grading(1.0, output_chars=1234, seconds=2), {"total_duration_seconds": 2, "total_tokens": 99})
            result = ab.load_run_results(root)["with_skill"][0]
        self.assertEqual(result["tokens"], 99)
        self.assertEqual(result["output_chars"], 1234)

    def test_missing_tokens_are_null_not_chars(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_run(root, 1, "with_skill", 1, grading(1.0, output_chars=1234, seconds=2))
            results = ab.load_run_results(root)
            summary = ab.aggregate_results(results)
            benchmark = ab.generate_benchmark(root)
        self.assertIsNone(results["with_skill"][0]["tokens"])
        self.assertIsNone(summary["with_skill"]["tokens"]["mean"])
        self.assertIsNone(benchmark["runs"][0]["result"]["tokens"])
        self.assertIn("| Tokens | N/A |", ab.generate_markdown(benchmark))


class IncompleteRunTest(unittest.TestCase):
    def test_missing_and_broken_grading_are_listed_and_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_run(root, 1, "with_skill", 1, grading(1.0, seconds=10))
            write_run(root, 1, "with_skill", 2, None)
            broken = write_run(root, 1, "without_skill", 1, None)
            (broken / "grading.json").write_text("{not json")
            write_run(root, 1, "without_skill", 2, grading(0.0, seconds=5))
            benchmark = ab.generate_benchmark(root)

        self.assertEqual(len(benchmark["incomplete"]), 2)
        reasons = {(i["configuration"], i["run_number"]): i["reason"] for i in benchmark["incomplete"]}
        self.assertEqual(reasons[("with_skill", 2)], "grading.json not found")
        self.assertTrue(reasons[("without_skill", 1)].startswith("grading.json unreadable"))
        self.assertEqual(len(benchmark["runs"]), 2)
        self.assertEqual(benchmark["run_summary"]["with_skill"]["pass_rate"], {"mean": 1.0, "stddev": 0.0, "min": 1.0, "max": 1.0})
        self.assertEqual(benchmark["run_summary"]["without_skill"]["pass_rate"]["mean"], 0.0)
        self.assertIn("## Incomplete Runs", ab.generate_markdown(benchmark))

    def test_config_without_complete_runs_reports_null_not_zero(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_run(root, 1, "with_skill", 1, grading(1.0))
            write_run(root, 1, "without_skill", 1, None)
            benchmark = ab.generate_benchmark(root)
        without = benchmark["run_summary"]["without_skill"]
        self.assertIsNone(without["pass_rate"]["mean"])
        self.assertIsNone(without["time_seconds"]["mean"])
        self.assertIsNone(benchmark["run_summary"]["delta"]["pass_rate"])

    def test_empty_grading_is_invalid_not_a_completed_zero(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_run(root, 1, "with_skill", 1, {})
            benchmark = ab.generate_benchmark(root)
        self.assertEqual(benchmark["runs"], [])
        self.assertEqual(len(benchmark["incomplete"]), 1)
        self.assertIn("summary must be", benchmark["incomplete"][0]["reason"])

    def test_inconsistent_grading_counts_are_invalid(self):
        bad = grading(1.0)
        bad["summary"]["failed"] = 1
        self.assertIn("must equal", ab.validate_grading(bad))

    def test_expectations_must_match_summary(self):
        bad = grading(1.0)
        bad["expectations"] = []
        self.assertIn("one entry per", ab.validate_grading(bad))

    def test_invalid_optional_sections_are_rejected(self):
        for field in ("timing", "execution_metrics", "user_notes_summary"):
            bad = grading(1.0)
            bad[field] = []
            with self.subTest(field=field):
                self.assertIn("must be a JSON object", ab.validate_grading(bad))

    def test_non_object_timing_file_does_not_crash_aggregation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_run(root, 1, "with_skill", 1, grading(1.0), [])
            benchmark = ab.generate_benchmark(root)
        self.assertEqual(len(benchmark["runs"]), 1)
        self.assertIsNone(benchmark["runs"][0]["result"]["tokens"])

    def test_invalid_timing_values_are_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_run(
                root,
                1,
                "with_skill",
                1,
                grading(1.0),
                {"total_duration_seconds": -1, "total_tokens": "many"},
            )
            benchmark = ab.generate_benchmark(root)
        result = benchmark["runs"][0]["result"]
        self.assertIsNone(result["time_seconds"])
        self.assertIsNone(result["tokens"])


class DeltaPairingTest(unittest.TestCase):
    def test_delta_uses_only_shared_eval_ids(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_run(root, 1, "with_skill", 1, grading(1.0))
            write_run(root, 1, "without_skill", 1, grading(0.0))
            write_run(root, 2, "with_skill", 1, grading(1.0))
            summary = ab.aggregate_results(ab.load_run_results(root))
        self.assertEqual(summary["delta"]["shared_eval_ids"], [1])
        self.assertEqual(summary["delta"]["pass_rate"], "+1.00")
        self.assertIsNone(summary["delta"]["tokens"])

    def test_no_shared_eval_ids_gives_null_delta(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_run(root, 1, "with_skill", 1, grading(1.0))
            write_run(root, 2, "without_skill", 1, grading(0.0))
            summary = ab.aggregate_results(ab.load_run_results(root))
        self.assertEqual(summary["delta"]["shared_eval_ids"], [])
        self.assertIsNone(summary["delta"]["pass_rate"])


class SchemaDocumentTest(unittest.TestCase):
    def setUp(self):
        self.text = (SKILL_DIR / "references" / "schemas.md").read_text()
        self.blocks = re.findall(r"```json\n(.*?)```", self.text, re.DOTALL)

    def test_every_json_example_parses(self):
        self.assertGreaterEqual(len(self.blocks), 7)
        for block in self.blocks:
            json.loads(block)

    def test_summary_counts_and_timing_add_up(self):
        for block in self.blocks:
            data = json.loads(block)
            if "summary" in data and "expectations" in data:
                summary = data["summary"]
                self.assertEqual(summary["passed"] + summary["failed"], summary["total"])
                self.assertEqual(len(data["expectations"]), summary["total"])
                self.assertEqual(sum(1 for e in data["expectations"] if e["passed"]), summary["passed"])
                timing = data["timing"]
                self.assertAlmostEqual(
                    timing["executor_duration_seconds"] + timing["grader_duration_seconds"],
                    timing["total_duration_seconds"],
                )
            if "duration_ms" in data:
                self.assertAlmostEqual(data["duration_ms"] / 1000, data["total_duration_seconds"], places=1)
                self.assertAlmostEqual(
                    data["executor_duration_seconds"] + data["grader_duration_seconds"],
                    data["total_duration_seconds"],
                )
            if "runs" in data and "run_summary" in data:
                for run in data["runs"]:
                    result = run["result"]
                    self.assertEqual(result["passed"] + result["failed"], result["total"])
                    self.assertAlmostEqual(result["pass_rate"], result["passed"] / result["total"], places=2)
                self.assertIn("incomplete", data)
                self.assertIn("shared_eval_ids", data["run_summary"]["delta"])

    def test_tie_is_documented_for_comparator_and_analyzer(self):
        self.assertIn('"TIE"', self.text)
        self.assertIn('"TIE"', (SKILL_DIR / "agents" / "analyzer.md").read_text())
        self.assertIn('"TIE"', (SKILL_DIR / "agents" / "comparator.md").read_text())


if __name__ == "__main__":
    unittest.main()
