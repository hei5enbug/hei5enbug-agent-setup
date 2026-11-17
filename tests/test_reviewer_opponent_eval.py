"""The Claude reviewer and opponent evaluation keeps its cases well formed and pins each candidate in the runner."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = REPO_ROOT / "evals" / "claude-reviewer-opponent"
sys.path.insert(0, str(EVAL_DIR))
sys.dont_write_bytecode = True

import cr_run  # noqa: E402


class CasesTest(unittest.TestCase):
    def test_사례는_고정된_문제_목록과_자료를_가진다(self):
        """리뷰 사례 3개와 토론 사례 2개가 각각 고정 문제 목록과 자료 파일을 가진다."""
        # Given
        data = cr_run.load()

        # When
        roles = [case["role"] for case in data["cases"]]

        # Then
        self.assertEqual(sorted(roles), ["debate", "debate", "review", "review", "review"])
        for case in data["cases"]:
            with self.subTest(case=case["id"]):
                self.assertTrue(case["real_problems"])
                self.assertTrue((EVAL_DIR / "cases" / case["id"] / "workspace").is_dir())
                if case["role"] == "review":
                    self.assertTrue((EVAL_DIR / "cases" / case["id"] / case["draft_file"]).is_file())
                else:
                    self.assertTrue((EVAL_DIR / "cases" / case["id"] / "workspace" / case["start"]).is_file())

    def test_후보는_모델과_사고_강도_네_가지다(self):
        """후보는 opus와 fable을 high와 xhigh로 하나씩 묶은 네 가지다."""
        # Given
        data = cr_run.load()

        # When
        pairs = {(item["model"], item["effort"]) for item in data["candidates"]}

        # Then
        self.assertEqual(len(data["candidates"]), 4)
        self.assertEqual(
            pairs,
            {("claude-opus-5-5", "high"), ("claude-opus-5-5", "xhigh"),
             ("claude-fable-5-2", "high"), ("claude-fable-5-2", "xhigh")},
        )


class CandidatePinTest(unittest.TestCase):
    def test_임시_플러그인의_실행기는_후보의_모델과_강도를_출력한다(self):
        """후보를 기록한 임시 플러그인 사본에서 tiki-taka 실행기가 그 후보의 모델과 강도를 보고한다."""
        # Given
        candidate = {"id": "x", "model": "claude-opus-5-5", "effort": "high"}
        with tempfile.TemporaryDirectory() as base:
            script = cr_run.temp_plugin(Path(base), candidate)

            # When
            done = subprocess.run(
                ["bash", str(script), "--show-config", "--opponent", "claude"],
                capture_output=True, text=True, check=False,
            )

        # Then
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "opponent=claude model=claude-opus-5-5 effort=high")


class CandidateRunnerTest(unittest.TestCase):
    def test_리뷰어_실행기는_네_후보를_각자의_모델과_강도로_실행_계획에_올린다(self):
        """역할 실행기의 reviewer가 네 후보를 모두 Claude 경로로 받아 후보의 모델과 강도를 명령에 그대로 담는다."""
        # Given
        scripts = str(REPO_ROOT / "scripts")
        sys.path.insert(0, scripts)
        try:
            import role_runner
            from role_runner_command import claude_command
            from role_runner_config import build_parser
        finally:
            sys.path.remove(scripts)
        data = cr_run.load()
        plans = []

        # When
        with tempfile.TemporaryDirectory() as base:
            assignment = Path(base) / "assignment.txt"
            assignment.write_text("review", encoding="utf-8")
            for candidate in data["candidates"]:
                args = build_parser().parse_args([
                    "reviewer", "--model", candidate["model"], "--effort", candidate["effort"],
                    "--assignment", str(assignment), "--result", str(Path(base) / "answer.txt"),
                ])
                run = role_runner.plan(args)
                command = claude_command(run)
                plans.append((run.runner, command[command.index("--model") + 1], command[command.index("--effort") + 1]))

        # Then
        self.assertEqual(plans, [("claude", item["model"], item["effort"]) for item in data["candidates"]])


class DecideTest(unittest.TestCase):
    def write_runs(self, out: Path, runs: dict) -> None:
        for (candidate, case), row in runs.items():
            folder = out / candidate / case
            folder.mkdir(parents=True)
            (folder / "status.json").write_text(json.dumps(row), encoding="utf-8")

    def row(self, cost: float, verified: bool = True) -> dict:
        return {"verified": verified, "model_matches": verified, "cost": {"list_cost_usd": cost, "model_ok": True}}

    def test_통과가_같으면_비용이_낮은_후보가_이기고_통과가_적은_후보는_싸도_진다(self):
        """역할별로 통과 수가 많은 후보가 이기고, 통과가 같을 때만 그 역할 사례의 비용이 낮은 후보가 이긴다."""
        # Given
        candidates = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        cases = [{"id": "r1", "role": "review"}, {"id": "r2", "role": "review"}, {"id": "d1", "role": "debate"}]
        costs = {"a": (2.0, 2.0, 1.0), "b": (1.0, 1.0, 5.0), "c": (0.1, 0.1, 0.1)}
        grades = {"a": {"r1": True, "r2": True, "d1": True}, "b": {"r1": True, "r2": True, "d1": True},
                  "c": {"r1": True, "r2": False, "d1": False}}
        with tempfile.TemporaryDirectory() as base:
            out = Path(base)
            self.write_runs(out, {(name, case["id"]): self.row(costs[name][index])
                                  for name in costs for index, case in enumerate(cases)})

            # When
            result = cr_run.decide(out, candidates, cases, grades)

        # Then
        self.assertEqual(result["review"]["winner"], "b")
        self.assertEqual(result["debate"]["winner"], "a")

    def test_검증되지_않은_실행이나_채점_없는_사례가_있으면_승자를_정하지_않는다(self):
        """모델과 강도가 검증되지 않은 실행이 있는 역할은 통과 수가 앞서도 승자 없이 문제로 남는다."""
        # Given
        candidates = [{"id": "a"}, {"id": "b"}]
        cases = [{"id": "r1", "role": "review"}]
        grades = {"a": {"r1": True}, "b": {"r1": False}}
        with tempfile.TemporaryDirectory() as base:
            out = Path(base)
            self.write_runs(out, {("a", "r1"): self.row(1.0, verified=False), ("b", "r1"): self.row(1.0)})

            # When
            result = cr_run.decide(out, candidates, cases, grades)

        # Then
        self.assertIsNone(result["review"]["winner"])
        self.assertEqual(result["review"]["problems"], ["a/r1: model or effort not verified"])


class TranscriptCostTest(unittest.TestCase):
    def test_기록의_사용량으로_목록_가격_비용을_계산한다(self):
        """같은 메시지 id는 한 번만 세고 모델별 목록 가격으로 비용을 합산한다."""
        # Given
        usage = {"input_tokens": 1000, "output_tokens": 500, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        entry = {"type": "assistant", "uuid": "u1", "message": {"id": "m1", "model": "claude-opus-5-5", "usage": usage}}
        with tempfile.TemporaryDirectory() as config:
            folder = Path(config) / "projects" / "demo"
            folder.mkdir(parents=True)
            (folder / "s1.jsonl").write_text("\n".join(json.dumps(item) for item in (entry, entry)), encoding="utf-8")

            # When
            with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": config}):
                cost = cr_run.transcript_cost("s1", "claude-opus-5-5")

        # Then
        self.assertEqual(cost["requests"], 1)
        self.assertAlmostEqual(cost["list_cost_usd"], (1000 * 4.0 + 500 * 20.0) / 1_000_000, places=4)
        self.assertTrue(cost["model_ok"])


if __name__ == "__main__":
    unittest.main()
