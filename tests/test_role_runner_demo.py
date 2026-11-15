from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("role_runner_demo", REPO_ROOT / "evals/role-runner-scratch/demo.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


def codex_rollout(path: Path, calls: list[tuple[str, str]]) -> Path:
    """Write a Codex rollout whose function calls and outputs are the given (command, output) pairs."""
    lines = []
    for command, output in calls:
        call = {"type": "function_call", "arguments": json.dumps({"cmd": command})}
        lines.append(json.dumps({"type": "response_item", "payload": call}))
        lines.append(json.dumps({"type": "response_item", "payload": {"type": "function_call_output", "output": output}}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class RoleRunnerDemoTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "demo-a"
        demo.seed(self.repo, with_env=False)
        self.before = self.base / "before.txt"
        self.before.write_text(demo.snapshot(self.repo), encoding="utf-8")
        self.answer = self.base / "answer.md"

    def run_check(self, kind, calls, answer):
        self.answer.write_text(answer, encoding="utf-8")
        records = codex_rollout(self.base / "rollout.jsonl", calls)
        return demo.check(kind, self.repo, records, self.answer, self.before)

    def test_시드한_저장소는_한_테스트만_시드한_결함으로_실패한다(self):
        """시드한 저장소에서 pytest는 test_bulk_discount만 실패하고 저장소는 pytest 캐시를 남기지 않는다."""
        # When
        done = subprocess.run(
            [sys.executable, "-B", "-m", "pytest", "-q"], cwd=self.repo, capture_output=True, text=True,
        )

        # Then
        self.assertEqual(1, done.returncode, done.stdout)
        self.assertIn("FAILED tests/test_pricing.py::test_bulk_discount", done.stdout)
        self.assertIn("2 passed", done.stdout)
        self.assertEqual(self.before.read_text(encoding="utf-8"), demo.snapshot(self.repo))

    def test_검증_실행은_테스트_명령과_실패_출력과_지적과_변경_없음이_모두_있어야_통과한다(self):
        """테스트 실행 기록, 시드한 단언 실패 출력, 실패 테스트 이름이 든 답, 변하지 않은 저장소가 있으면 통과한다."""
        # When
        failures = self.run_check(
            "validation", [("uv run pytest -q", "FAILED tests/test_pricing.py::test_bulk_discount - assert 5000 == 4500")],
            "test_bulk_discount fails: ten units are not discounted.",
        )

        # Then
        self.assertEqual([], failures)

    def test_검증_실행은_테스트를_돌리지_않았거나_저장소가_바뀌면_실패한다(self):
        """테스트 명령 기록이 없거나 답이 실패 테스트를 말하지 않거나 저장소가 바뀌면 각각 실패 사유가 나온다."""
        # Given
        (self.repo / "scratch.txt").write_text("x", encoding="utf-8")

        # When
        failures = self.run_check("validation", [("rg pricing", "pricing.py")], "No findings.")

        # Then
        self.assertEqual(4, len(failures), failures)

    def test_scout_실행은_heredoc_계산_값과_변경_없음이_있고_테스트나_설치가_없어야_통과한다(self):
        """heredoc Python 명령과 기대 값이 있고 테스트와 설치 명령이 없으면 통과하며, 설치 명령이 있거나 heredoc이 실패하면 실패한다."""
        # Given
        command = "python3 - <<'PY'\nprint(sum(1 for _ in range(3)))\nPY"
        passing = [(command, str(demo.EXPECTED_TOTAL))]
        broken = [(command, "zsh:1: can't create temp file for here document: operation not permitted"), ("uv sync", "")]

        # When
        passed = self.run_check("scout", passing, f"The total is {demo.EXPECTED_TOTAL} cents.")
        failed = self.run_check("scout", broken, "The total could not be computed.")

        # Then
        self.assertEqual([], passed)
        self.assertEqual(3, len(failed), failed)


if __name__ == "__main__":
    unittest.main()
