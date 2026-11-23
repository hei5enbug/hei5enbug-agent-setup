"""Tests for the loop-record command and for the rule that candidate text exists exactly when the record adopts it."""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))

from harness import cli, loop_verdict, records  # noqa: E402

RECORD = REPO_ROOT / "evals/e2e/records/102.json"
CANDIDATE_TEXT = {
    "a": lambda root: "role_runner.py language" in (root / "instructions/shared-text.md").read_text(encoding="utf-8"),
    "b": lambda root: re.search(r"^DEFAULT_REVIEWS = 2$", (root / "scripts/text_review.py").read_text(encoding="utf-8"), re.M) is not None,
    "c": lambda root: "CHANGED_HEADING" in (root / "scripts/text_review.py").read_text(encoding="utf-8")
    and "changed since the previous run" in (root / "instructions/shared-text.md").read_text(encoding="utf-8"),
    "d": lambda root: "Report every problem you find in this run" in " ".join((root / "scripts/text_review.py").read_text(encoding="utf-8").split()),
}
LOOP = {"reviewer_runs": 2, "check_stops": 1, "main_turns": 4, "main_tokens": {"input": 1, "output": 2, "cache_read": 3, "cache_write": 4},
        "main_tokens_loop": {"input": 1, "output": 1, "cache_read": 1, "cache_write": 1}}


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")


def seed_run(root: Path, task: str, variant: str, host: str, cost: float, clean: bool = True) -> None:
    folder = root / "camp" / "results" / task / variant / ("codex" if host == "codex" else "") / "rep1"
    write(folder / "run.json", {"run_id": f"{task}-{variant}-{host}-r1", "task": task, "variant": variant, "rep": 1, "status": "complete",
                                "host": host})
    claude = host == "claude"
    write(folder / "metrics.json", {
        "success": clean, "wall_seconds": 100.0, "host": host, "review_loop": LOOP, "plugin": {"subagent_models": {}},
        "session": {"model": "gpt-6.1-sol", "effort": "high"},
        "cost": {"claude_total_cost_usd": cost if claude else None, "claude_runner_list_cost_usd": 0.0, "claude_list_cost_usd": 0.0,
                 "codex_list_cost_usd_estimate": None if claude else cost}})
    write(folder / "grade" / "grade.json", {"checks": [
        {"id": "text-review-clean", "required": True, "passed": clean, "data": {}},
        {"id": "ran-text-review", "required": False, "passed": True, "data": {}}]})
    write(folder / "command.json", {"argv": ["claude", "-p", "--model", "claude-opus-5-5", "--effort", "high", "--", "prompt"]})
    (folder / "stream.jsonl").write_text(json.dumps({"type": "system", "subtype": "init", "model": "claude-opus-5-5"}) + "\n", encoding="utf-8")
    write(folder / "env.json", {"codex_session_model": "gpt-6.1-sol", "codex_session_effort": "high"})
    write(folder / "view.json", {"tool_calls": []})


def run_cli(root: Path, *extra: str):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["loop-record", "--run-root", str(root), "--campaign", "camp", "--issue", "102", "--baseline", "base",
                         "--records-dir", str(root / "records"), *extra])
    return code, out.getvalue(), err.getvalue()


class LoopRecordCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        write(self.root / "camp" / "campaign.json", {"inputs": {"variant_shas": {"base": "0123456789abcdef", "a": "fedcba9876543210"}}})
        for task in ("T13", "T15", "T20"):
            for host in ("claude", "codex"):
                seed_run(self.root, task, "base", host, 1.0)
                seed_run(self.root, task, "a", host, 0.5, clean=task != "T15")

    def test_기준선과_후보의_실행으로_검증을_통과하는_기록을_쓰고_loop_수치와_후보_판정을_담는다(self):
        """given T13, T15, T20을 기준선과 후보 a로 두 호스트에서 돌린 캠페인 when loop-record를 실행하면 then 검증을 통과하는 기록에 loop와 a의 판정이 있다."""
        # given
        tasks = ("--candidate", "a=a", "--tasks", "T13,T15,T20")

        # when
        code, out, err = run_cli(self.root, *tasks)

        # then
        self.assertEqual((code, err), (0, ""))
        written = json.loads((self.root / "records" / "102.json").read_text(encoding="utf-8"))
        self.assertEqual(records.validate_record(written), [])
        self.assertEqual(written["runs"][0]["loop"], LOOP)
        self.assertEqual([(item["candidate"], item["variant"]) for item in written["candidates"]], [("a", "a")])
        self.assertIn("a: reject (writing rule", out)
        self.assertIn("adopted: none", out)

    def test_후보_이름이_잘못되면_기록을_쓰지_않고_오류로_끝난다(self):
        """given NAME=VARIANT 모양이 아닌 --candidate when 실행하면 then 종료 코드 1이고 기록이 없다."""
        # given
        bad = ("--candidate", "a", "--tasks", "T13")

        # when
        code, _, err = run_cli(self.root, *bad)

        # then
        self.assertEqual(code, 1)
        self.assertIn("--candidate takes NAME=VARIANT", err)
        self.assertFalse((self.root / "records" / "102.json").exists())


class CandidateTextTest(unittest.TestCase):
    def test_후보의_글은_기록이_채택한_후보에만_있고_기록이_없으면_어느_후보에도_없다(self):
        """given 이슈 102의 기록이 있거나 아직 없을 때 when 저장소의 후보 글을 찾으면 then 채택한 후보에만 있고 기록이 없으면 하나도 없다."""
        # given
        record = json.loads(RECORD.read_text(encoding="utf-8")) if RECORD.is_file() else {"candidates": []}
        adopted = set(loop_verdict.final_adopted(record["candidates"]))

        # when
        present = {name for name, found in CANDIDATE_TEXT.items() if found(REPO_ROOT)}

        # then
        self.assertEqual(present, adopted & set(CANDIDATE_TEXT))


if __name__ == "__main__":
    unittest.main()
