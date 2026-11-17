"""Unit tests for the T90 evaluation task: its seeded Git state, reference solution, and the graders that read role runner commands."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
TASKS_ROOT = E2E_ROOT / "tasks"
FIXTURES_ROOT = E2E_ROOT / "fixtures"
sys.path.insert(0, str(E2E_ROOT))

from harness import graders  # noqa: E402

RUNNER = "python3 /plugin/scripts/role_runner.py"
FAST_START = f"{RUNNER} reviewer --service-tier fast --assignment /tmp/work/a.md --result /tmp/work/r.md"
PLAIN_START = f"{RUNNER} reviewer --assignment /tmp/work/a.md --result /tmp/work/r.md"


def make_view(*commands: str) -> dict[str, Any]:
    calls = [{"id": f"c{i}", "name": "Bash", "input": {"command": command}, "result_text": "", "is_error": False,
              "parent": None, "source": "main"} for i, command in enumerate(commands)]
    return {"final_answer": "done", "assistant_texts": [], "tool_calls": calls, "delegations": [], "approvals": [],
            "permission_denials": []}


class ServiceTierTaskTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.task = json.loads((TASKS_ROOT / "T90.json").read_text(encoding="utf-8"))
        self.repo = self.root / "work" / "repo"
        self.base = graders.materialize_fixture(self.task, FIXTURES_ROOT, TASKS_ROOT, self.repo)

    def apply_reference(self) -> None:
        subprocess.run([sys.executable, "-B", str(TASKS_ROOT / "reference" / "T90" / "apply.py"), str(self.repo)],
                       cwd=self.repo, env={**os.environ, "PYTHONPATH": str(TASKS_ROOT / "reference")}, check=True,
                       capture_output=True, text=True)

    def grade(self, *commands: str) -> dict[str, bool]:
        result = graders.grade_run(self.task, self.repo, self.base, make_view(*commands), TASKS_ROOT, self.root / "grade")
        return {check["id"]: check["passed"] for check in result["checks"]}

    def test_과제_정의는_프롬프트와_참조_해법과_검사_함수가_모두_있고_프롬프트는_빠른_등급을_평이하게_요청한다(self):
        """T90의 프롬프트, 참조 해법, 사용자 지정 검사 함수가 있고 프롬프트에 옵션 이름은 없다."""
        # Given
        source = (TASKS_ROOT / "custom" / "T90.py").read_text(encoding="utf-8")

        # When
        prompt = (TASKS_ROOT / self.task["prompt_file"]).read_text(encoding="utf-8")
        functions = [check["function"] for check in self.task["checks"] if check["kind"] == "custom"]

        # Then
        self.assertTrue((TASKS_ROOT / "reference" / "T90" / "apply.py").is_file())
        self.assertEqual([name for name in functions if f"def {name}(" not in source], [])
        self.assertIn("fast", prompt)
        self.assertNotIn("--service-tier", prompt)

    def test_기준_수정에_모든_실행기_시작이_service_tier_fast를_가지면_모든_필수_검사를_통과한다(self):
        """참조 해법과 --service-tier fast가 붙은 실행기 시작만 있는 기록은 필수 검사를 모두 통과한다."""
        # Given
        self.apply_reference()

        # When
        outcome = self.grade(FAST_START, f"cd /tmp/work && {FAST_START}")

        # Then
        self.assertTrue(all(outcome.values()), outcome)

    def test_옵션이_없던_이전_리비전처럼_실행기_시작에_service_tier가_없으면_빠른_등급_검사만_실패한다(self):
        """같은 참조 해법이어도 --service-tier 없이 시작한 실행기가 있으면 fast-tier-on-runner-starts만 실패한다."""
        # Given
        self.apply_reference()

        # When
        outcome = self.grade(PLAIN_START)

        # Then
        self.assertEqual({name for name, passed in outcome.items() if not passed}, {"fast-tier-on-runner-starts"})

    def test_실행기를_한_번도_시작하지_않은_기록은_빠른_등급_검사를_통과하지_못한다(self):
        """위임 없이 직접 고친 기록은 시작이 없으므로 빈 통과가 아니라 실패이다."""
        # Given
        self.apply_reference()

        # When
        outcome = self.grade("git diff", "grep -n role_runner.py AGENTS.md")

        # Then
        self.assertFalse(outcome["fast-tier-on-runner-starts"])

    def test_한_명령줄에_실행기_시작이_둘이면_옵션이_없는_뒤쪽_시작을_찾아낸다(self):
        """앞 시작의 옵션이 뒤 시작의 누락을 가리지 않는다."""
        # Given
        self.apply_reference()

        # When
        outcome = self.grade(f"{FAST_START} && {PLAIN_START}")

        # Then
        self.assertFalse(outcome["fast-tier-on-runner-starts"])

    def test_요청이_고정_모델이나_강도를_바꾸는_user_requested_시작은_고정값_검사에서_실패한다(self):
        """--service-tier fast만으로는 통과하고 --user-requested를 함께 붙인 시작은 request-leaves-pins에서 실패한다."""
        # Given
        self.apply_reference()
        changed = FAST_START + " --user-requested --effort xhigh"

        # When
        passed = self.grade(FAST_START)
        failed = self.grade(changed)

        # Then
        self.assertTrue(passed["request-leaves-pins"])
        self.assertFalse(failed["request-leaves-pins"])

    def test_수정하지_않은_저장소는_결과_검사에서_실패한다(self):
        """실행기 옵션이 맞아도 설정을 바꾸지 않은 저장소는 page-size-50에서 실패한다."""
        # Given
        commands = (FAST_START,)

        # When
        outcome = self.grade(*commands)

        # Then
        self.assertFalse(outcome["page-size-50"])
        self.assertTrue(outcome["fast-tier-on-runner-starts"])


if __name__ == "__main__":
    unittest.main()
