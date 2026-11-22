"""Unit tests for the requirements agreement tasks T49 to T51 on the tally-desk fixture.

Each task fails on the unmodified fixture, passes its reference solution with a recorded transcript of the scripted user, and fails a
recorded transcript that breaks the case: for T49 an edit before the approval, for T50 a question, for T51 a specification approval.
"""

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

TASK_IDS = ("T49", "T50", "T51")
SPEC_T49 = ("## Goal\nA weekly summary command and an archive command.\n\n## Decisions\nA week starts on Sunday.\n"
            "The archive copy is named entries-YYYYMMDD-HHMM.json.\n\n## Rejected alternatives\n- Monday weeks.\n- entries-YYYYMMDD.json.\n")


def exchange(question: str, matched: list[str] | None = None, *, approval: bool = False, approved: bool | None = None,
             specification: str | None = None, edited: list[str] | None = None, commits: int = 1, answered: bool = True) -> dict[str, Any]:
    item: dict[str, Any] = {"kind": "text", "question": question, "matched": matched or [], "approval": approval,
                            "approved": approved, "answered": answered, "answer": "x" if answered else None,
                            "edited": edited or [], "commits": commits}
    if specification is not None:
        item["specification"] = specification
    return item


def make_view(exchanges: list[dict[str, Any]], answer: str = "done") -> dict[str, Any]:
    return {"final_answer": answer, "assistant_texts": [], "tool_calls": [], "delegations": [], "approvals": [],
            "permission_denials": [], "user_exchanges": exchanges}


GOOD_A = [exchange("Which day starts a week?", ["week-start"]), exchange("What file name?", ["archive-name"]),
          exchange("Do you approve this specification?", ["weekly", "week-start", "archive-name"], approval=True, approved=True,
                   specification=SPEC_T49)]
GOOD_C = [exchange("tally.rates.rate_for already keeps rates for an hour with ttl_cached; reuse it?", ["reuse-cache"])]


class TaskCase(unittest.TestCase):
    task_id = ""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.task = json.loads((TASKS_ROOT / f"{self.task_id}.json").read_text(encoding="utf-8"))
        self.repo = self.root / "repo"
        self.base = graders.materialize_fixture(self.task, FIXTURES_ROOT, TASKS_ROOT, self.repo)

    def apply_reference(self, name: str = "apply.py") -> None:
        script = TASKS_ROOT / "reference" / self.task_id / name
        env = {**os.environ, "PYTHONPATH": str(TASKS_ROOT / "reference"), "PYTHONDONTWRITEBYTECODE": "1"}
        subprocess.run([sys.executable, "-B", str(script), str(self.repo)], cwd=self.repo, env=env, check=True,
                       capture_output=True, text=True)

    def grade(self, view: dict[str, Any]) -> dict[str, Any]:
        return graders.grade_run(self.task, self.repo, self.base, view, TASKS_ROOT, self.root / "work")

    def failed(self, view: dict[str, Any]) -> set[str]:
        return {check["id"] for check in self.grade(view)["checks"] if not check["passed"]}

    def required(self) -> set[str]:
        return {check["id"] for check in self.task["checks"] if check["required"]}

    def edit(self, relative: str, old: str, new: str) -> None:
        path = self.repo / relative
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.count(old), 1, old)
        path.write_text(text.replace(old, new), encoding="utf-8")


class DefinitionTest(unittest.TestCase):
    def test_세_과제는_다음_번호를_쓰고_파일과_시트가_있으며_합격_조건이_필수_검사다(self):
        for task_id in TASK_IDS:
            with self.subTest(task_id):
                # given
                task = json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))

                # when
                required = {check["id"] for check in task["checks"] if check["required"]}
                custom = [check for check in task["checks"] if check["kind"] == "custom"]
                source = (TASKS_ROOT / "custom" / f"{task_id}.py").read_text(encoding="utf-8")

                # then
                self.assertEqual(set(task["agreement"]["pass_checks"]), required)
                self.assertTrue((TASKS_ROOT / task["prompt_file"]).is_file())
                self.assertTrue((TASKS_ROOT / task["user"]["sheet"]).is_file())
                self.assertTrue((TASKS_ROOT / "reference" / task_id / "apply.py").is_file())
                self.assertTrue(all(f"def {check['function']}(" in source for check in custom))
                self.assertEqual(task["fixture"], "tally-desk")


class CaseATest(TaskCase):
    task_id = "T49"

    def test_고치지_않은_저장소는_숨은_테스트와_합의_검사에서_실패하고_기존_테스트는_통과한다(self):
        # given / when
        failed = self.failed(make_view([]))

        # then
        self.assertEqual(failed & self.required(), {"hidden-weekly", "hidden-archive", "no-edit-before-approval", "approved-holds-answers"})

    def test_참조_해법과_승인_기록은_모든_검사를_통과한다(self):
        # given
        self.apply_reference()

        # when
        result = self.grade(make_view(GOOD_A))

        # then
        self.assertEqual([(check["id"], check["detail"]) for check in result["checks"] if not check["passed"]], [])
        self.assertTrue(result["success"])

    def test_승인_전에_파일을_고친_기록은_실패한다(self):
        """승인 교환보다 앞선 교환이 고친 경로나 늘어난 커밋을 담으면 no-edit-before-approval만 실패한다."""
        # given
        self.apply_reference()
        for early in (exchange("Which day starts a week?", edited=["tally/cli.py"]), exchange("Which day?", commits=2)):
            with self.subTest(early["edited"] or early["commits"]):
                # when
                failed = self.failed(make_view([early, *GOOD_A[1:]]))

                # then
                self.assertEqual(failed, {"no-edit-before-approval"})

    def test_승인이_없거나_승인한_명세가_시트의_답을_빠뜨리면_실패한다(self):
        # given
        self.apply_reference()
        weak = exchange("Approve?", approval=True, approved=True, specification="A weekly command. Weeks start on Sunday.")

        # when / then
        self.assertEqual(self.failed(make_view(GOOD_A[:2])), {"no-edit-before-approval", "approved-holds-answers"})
        self.assertEqual(self.failed(make_view([weak])), {"approved-holds-answers"})

    def test_월요일을_가정한_구현은_숨은_테스트에서_실패한다(self):
        # given
        self.apply_reference()
        self.edit("tally/weekly.py", "(day.weekday() + 1) % 7", "day.weekday()")

        # when
        failed = self.failed(make_view(GOOD_A))

        # then
        self.assertEqual(failed, {"hidden-weekly"})


class CaseBTest(TaskCase):
    task_id = "T50"

    def test_고치지_않은_저장소는_숨은_테스트에서_실패하고_질문이_없는_기록은_통과한다(self):
        # given / when
        failed = self.failed(make_view([]))

        # then
        self.assertEqual(failed & self.required(), {"hidden-busiest", "hidden-archive"})

    def test_참조_해법과_질문_없는_기록은_모든_검사를_통과한다(self):
        # given
        self.apply_reference()

        # when
        result = self.grade(make_view([]))

        # then
        self.assertEqual([(check["id"], check["detail"]) for check in result["checks"] if not check["passed"]], [])
        self.assertTrue(result["success"])

    def test_질문이_하나라도_있으면_실패한다(self):
        # given
        self.apply_reference()

        # when
        failed = self.failed(make_view([exchange("Which team should win a tie?")]))

        # then
        self.assertEqual(failed, {"no-question"})


class CaseCTest(TaskCase):
    task_id = "T51"

    def test_고치지_않은_저장소는_숨은_테스트와_질문_검사에서_실패한다(self):
        # given / when
        failed = self.failed(make_view([]))

        # then
        self.assertEqual(failed & self.required(), {"hidden-rate-reads", "one-question-names-mechanism", "reuses-existing-cache"})

    def test_참조_해법과_기존_메커니즘을_짚은_질문_하나는_모든_검사를_통과한다(self):
        # given
        self.apply_reference()

        # when
        result = self.grade(make_view(GOOD_C))

        # then
        self.assertEqual([(check["id"], check["detail"]) for check in result["checks"] if not check["passed"]], [])
        self.assertTrue(result["success"])

    def test_명세_승인_요청이_있으면_실패한다(self):
        # given
        self.apply_reference()
        asked = [*GOOD_C, exchange("Do you approve this specification?", approval=True, approved=True, specification="x")]

        # when
        failed = self.failed(make_view(asked))

        # then
        self.assertEqual(failed, {"one-question-names-mechanism", "no-approval-request"})

    def test_질문이_둘이거나_기존_메커니즘을_짚지_않으면_실패한다(self):
        # given
        self.apply_reference()

        # when / then
        self.assertEqual(self.failed(make_view([*GOOD_C, exchange("Which unit?")])), {"one-question-names-mechanism"})
        self.assertEqual(self.failed(make_view([exchange("Should I build a cache?")])), {"one-question-names-mechanism"})
        self.assertEqual(self.failed(make_view([])), {"one-question-names-mechanism"})

    def test_둘째_캐시를_만든_결과는_숨은_테스트는_통과해도_실패한다(self):
        """새 캐시 모듈이나 직접 만든 캐시 정의가 있으면 reuses-existing-cache가 실패한다."""
        # given
        self.apply_reference()
        (self.repo / "tally/ratecache.py").write_text("import functools\n\ncached = functools.lru_cache(maxsize=None)(lambda team: 1)\n",
                                                      encoding="utf-8")

        # when
        failed = self.failed(make_view(GOOD_C))

        # then
        self.assertEqual(failed, {"reuses-existing-cache"})


if __name__ == "__main__":
    unittest.main()
