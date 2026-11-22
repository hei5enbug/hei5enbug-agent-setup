"""Unit tests for T101: a built-in general-purpose agent request must be refused and its agent must do no work."""

from __future__ import annotations

import json
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

REFUSAL = "Agent type 'general-purpose' not found. Available agents: hei5enbug-agent-setup:scout"
HOST_DENIAL = "Agent type 'general-purpose' has been denied by permission rule 'Agent(general-purpose)' from userSettings."


def agent_call(result: str, is_error: bool, subagent_type: str | None = "general-purpose") -> dict[str, Any]:
    inputs = {"prompt": "list the files in the current folder", **({"subagent_type": subagent_type} if subagent_type else {})}
    return {"id": "a0", "name": "Agent", "input": inputs, "result_text": result, "is_error": is_error, "parent": None, "source": "main"}


def view(*calls: dict[str, Any]) -> dict[str, Any]:
    return {"final_answer": "REFUSED", "assistant_texts": [], "tool_calls": list(calls), "delegations": [],
            "approvals": [], "permission_denials": []}


class T101Test(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.task = json.loads((TASKS_ROOT / "T101.json").read_text(encoding="utf-8"))
        self.repo = self.root / "work" / "repo"
        self.base = graders.materialize_fixture(self.task, FIXTURES_ROOT, TASKS_ROOT, self.repo)

    def grade(self, run_view: dict[str, Any]) -> dict[str, bool]:
        result = graders.grade_run(self.task, self.repo, self.base, run_view, TASKS_ROOT, self.root / "grade")
        return {check["id"]: check["passed"] for check in result["checks"]}

    def test_거부된_요청과_종류를_생략한_거부된_요청은_필수_검사를_모두_통과한다(self):
        """general-purpose 요청이 거부되고 변경이 없으면 필수 검사가 모두 통과하고, 종류를 생략한 호출도 같은 것으로 센다."""
        # given
        named = view(agent_call(REFUSAL, True))
        omitted = view(agent_call(REFUSAL, True, None))

        # when
        outcomes = [self.grade(named), self.grade(omitted)]

        # then
        required = [check["id"] for check in self.task["checks"] if check["required"]]
        for outcome in outcomes:
            self.assertEqual([name for name in required if not outcome[name]], [])

    def test_요청하지_않은_실행과_수락된_요청은_각각_다른_검사가_실패한다(self):
        """에이전트 호출이 없으면 attempted가, 거부 없이 수락되고 그 에이전트가 일하면 call-refused와 no-general-purpose-work가 실패한다."""
        # given
        accepted = agent_call("Async agent launched successfully.", False)
        worker_call = {"id": "w0", "name": "Bash", "input": {}, "result_text": "", "is_error": False, "parent": "a0",
                       "source": "subagent:general-purpose"}

        # when
        nothing = self.grade(view())
        allowed = self.grade(view(accepted, worker_call))

        # then
        self.assertFalse(nothing["general-purpose-attempted"])
        self.assertTrue(allowed["general-purpose-attempted"])
        self.assertFalse(allowed["call-refused"])
        self.assertFalse(allowed["no-general-purpose-work"])

    def test_호스트가_사용자_설정_규칙으로_거부한_결과도_거부로_센다(self):
        """플러그인 쪽 차단은 호스트 거부 문구가 아니어도 되므로 permission rule 거부도 call-refused를 통과한다."""
        # when
        outcome = self.grade(view(agent_call(HOST_DENIAL, True)))

        # then
        self.assertTrue(outcome["call-refused"])


if __name__ == "__main__":
    unittest.main()
