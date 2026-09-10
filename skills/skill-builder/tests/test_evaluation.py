"""Trigger evaluation and description optimization without a real model."""

from __future__ import annotations

import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))

from scripts import generate_report, improve_description, run_eval, run_loop  # noqa: E402
from scripts.model_runner import RunnerError  # noqa: E402


def write_skill(root: Path) -> Path:
    skill = root / "demo"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: demo\ndescription: demo\n---\nBody\n")
    return skill


def fake_eval(**kwargs):
    """Stand-in for run_eval that passes every case and echoes ids."""
    rows = [
        {
            "id": item.get("id", index),
            "query": item["query"],
            "should_trigger": item["should_trigger"],
            "pass": True,
            "triggers": 1,
            "runs": 1,
            "errors": 0,
            "trigger_rate": 1.0,
        }
        for index, item in enumerate(kwargs["eval_set"])
    ]
    return {"results": rows, "summary": {"passed": len(rows), "total": len(rows), "failed": 0, "runner_errors": 0}}


class RunEvalValidationTest(unittest.TestCase):
    def test_zero_runs_is_rejected_before_any_model_call(self):
        with patch.object(run_eval, "run_single_query") as runner:
            with self.assertRaises(ValueError):
                run_eval.run_eval([{"query": "q", "should_trigger": False}], "demo", "demo", 1, 1, "unused", runs_per_query=0)
        runner.assert_not_called()

    def test_empty_eval_set_is_rejected(self):
        with self.assertRaises(ValueError):
            run_eval.validate_eval_set([])

    def test_malformed_cases_are_rejected(self):
        for bad in ([{"query": "", "should_trigger": True}], [{"query": "q", "should_trigger": "yes"}], [{"query": "q"}], ["q"]):
            with self.subTest(case=bad):
                with self.assertRaises(ValueError):
                    run_eval.validate_eval_set(bad)

    def test_conflicting_duplicate_query_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "contradicts"):
            run_eval.validate_eval_set([
                {"query": "same", "should_trigger": True},
                {"query": "same", "should_trigger": False},
            ])

    def test_holdout_and_iterations_are_range_checked(self):
        with self.assertRaises(ValueError):
            run_eval.validate_run_settings(1, max_iterations=0)
        with self.assertRaises(ValueError):
            run_eval.validate_run_settings(1, holdout=1.0)
        with self.assertRaises(ValueError):
            run_eval.validate_run_settings(1, holdout=-0.1)
        run_eval.validate_run_settings(1, max_iterations=1, holdout=0.0)

    def test_threshold_workers_and_timeout_are_checked(self):
        for threshold in (-0.1, 1.1, math.nan, math.inf):
            with self.subTest(threshold=threshold):
                with self.assertRaises(ValueError):
                    run_eval.validate_run_settings(1, trigger_threshold=threshold)
        with self.assertRaises(ValueError):
            run_eval.validate_run_settings(1, num_workers=0)
        with self.assertRaises(ValueError):
            run_eval.validate_run_settings(1, timeout=0)

    def test_invalid_description_is_rejected(self):
        for description in ("", " " * 3, "x" * 1025):
            with self.subTest(length=len(description)):
                with self.assertRaises(ValueError):
                    run_eval.validate_description(description)

    def test_negative_threshold_cannot_turn_false_answer_into_pass(self):
        with patch.object(run_eval, "run_single_query") as runner:
            with self.assertRaises(ValueError):
                run_eval.run_eval(
                    [{"query": "q", "should_trigger": True}],
                    "demo", "demo", 1, 1, "unused",
                    runs_per_query=1, trigger_threshold=-1,
                )
        runner.assert_not_called()

    def test_conflicting_trigger_tags_are_an_error(self):
        with self.assertRaises(RunnerError):
            run_eval.parse_trigger_response("<trigger>true</trigger><trigger>false</trigger>")

    def test_repeated_identical_tags_still_parse(self):
        self.assertTrue(run_eval.parse_trigger_response("<trigger>true</trigger> <trigger>TRUE</trigger>"))
        self.assertFalse(run_eval.parse_trigger_response("<trigger>false</trigger>"))

    def test_conflicting_response_counts_as_error_not_pass(self):
        with patch.object(run_eval, "run_model", return_value="<trigger>true</trigger><trigger>false</trigger>"):
            output = run_eval.run_eval([{"query": "q", "should_trigger": False}], "demo", "demo", 1, 1, "unused", runs_per_query=1)
        result = output["results"][0]
        self.assertEqual(result["errors"], 1)
        self.assertFalse(result["pass"])
        self.assertEqual(result["id"], 0)
        self.assertEqual(output["summary"]["runner_errors"], 1)


class RunLoopSplitTest(unittest.TestCase):
    def test_duplicate_queries_stay_together_and_counts_match(self):
        eval_set = [
            {"query": "same", "should_trigger": True},
            {"query": "same", "should_trigger": True},
            {"query": "other", "should_trigger": True},
            {"query": "third", "should_trigger": True},
            {"query": "neg-a", "should_trigger": False},
            {"query": "neg-b", "should_trigger": False},
        ]
        with tempfile.TemporaryDirectory() as td:
            skill = write_skill(Path(td))
            with patch.object(run_loop, "run_eval", fake_eval):
                loop = run_loop.run_loop(eval_set, skill, None, 1, 1, 1, 1, 0.5, 0.5, "unused", None, False)

        self.assertEqual(loop["train_size"] + loop["test_size"], len(eval_set))
        self.assertEqual(loop["history"][0]["train_total"], loop["train_size"])
        self.assertEqual(loop["history"][0]["test_total"], loop["test_size"])
        train_queries = {r["query"] for r in loop["history"][0]["train_results"]}
        test_queries = {r["query"] for r in loop["history"][0]["test_results"]}
        self.assertFalse(train_queries & test_queries)
        self.assertNotEqual(loop["best_test_score"], "0/0")

    def test_two_identical_cases_are_not_split_into_empty_holdout(self):
        eval_set = [{"query": "same", "should_trigger": True}] * 2
        with tempfile.TemporaryDirectory() as td:
            skill = write_skill(Path(td))
            with patch.object(run_loop, "run_eval", fake_eval):
                loop = run_loop.run_loop(eval_set, skill, None, 1, 1, 1, 1, 0.5, 0.5, "unused", None, False)
        self.assertEqual((loop["train_size"], loop["test_size"]), (2, 0))
        self.assertEqual(loop["history"][0]["train_total"], 2)
        self.assertIsNone(loop["history"][0]["test_total"])
        self.assertIsNone(loop["best_test_score"])

    def test_invalid_settings_never_reach_the_model(self):
        with tempfile.TemporaryDirectory() as td:
            skill = write_skill(Path(td))
            with patch.object(run_loop, "run_eval") as runner:
                for kwargs in (
                    {"eval_set": []},
                    {"max_iterations": 0},
                    {"holdout": 1.5},
                ):
                    args = {
                        "eval_set": [{"query": "q", "should_trigger": True}],
                        "max_iterations": 1,
                        "holdout": 0.0,
                    }
                    args.update(kwargs)
                    with self.subTest(**kwargs):
                        with self.assertRaises(ValueError):
                            run_loop.run_loop(args["eval_set"], skill, None, 1, 1, args["max_iterations"], 1, 0.5, args["holdout"], "unused", None, False)
            runner.assert_not_called()


class ImproveDescriptionTest(unittest.TestCase):
    def improve(self, responses):
        with patch.object(improve_description, "run_model", side_effect=responses) as runner:
            result = improve_description.improve_description(
                "demo", "Body", "demo", {"summary": {"passed": 0, "total": 1}, "results": []}, [], "unused", None
            )
        return result, runner.call_count

    def test_over_limit_is_rewritten_once(self):
        long = "<new_description>" + "x" * 1100 + "</new_description>"
        short = "<new_description>short</new_description>"
        result, calls = self.improve([long, short])
        self.assertEqual(result, "short")
        self.assertEqual(calls, 2)

    def test_still_over_limit_after_retry_is_rejected(self):
        long = "<new_description>" + "x" * 1100 + "</new_description>"
        with self.assertRaises(RunnerError):
            self.improve([long, long])

    def test_empty_rewrite_is_rejected(self):
        with self.assertRaises(RunnerError):
            self.improve(["<new_description></new_description>", "   "])


class ReportTest(unittest.TestCase):
    def test_empty_test_set_shows_na_not_zero_over_zero(self):
        data = {
            "original_description": "a",
            "best_description": "b",
            "best_score": "1/1",
            "best_train_score": "1/1",
            "best_test_score": None,
            "iterations_run": 1,
            "holdout": 0.5,
            "train_size": 1,
            "test_size": 0,
            "history": [
                {
                    "iteration": 1,
                    "description": "b",
                    "train_passed": 1,
                    "train_failed": 0,
                    "train_total": 1,
                    "train_results": [{"query": "q", "should_trigger": True, "pass": True, "triggers": 1, "runs": 1}],
                    "test_passed": None,
                    "test_failed": None,
                    "test_total": None,
                    "test_results": None,
                }
            ],
        }
        html = generate_report.generate_html(data)
        self.assertNotIn("0/0", html)
        self.assertIn("N/A", html)


if __name__ == "__main__":
    unittest.main()
