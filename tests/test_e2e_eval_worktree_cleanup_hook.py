"""Unit tests for the T67 evaluation task: its seeded fake Orca and Git state, its graders, and its reference solution."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
TASKS_ROOT = E2E_ROOT / "tasks"
FIXTURES_ROOT = E2E_ROOT / "fixtures"
sys.path.insert(0, str(E2E_ROOT))

from harness import command, graders  # noqa: E402

QUESTION = "이어서 할 일이 있을까요?"
BRANCH = "feature/ABC-123"


def make_view(answer: str = "") -> dict[str, Any]:
    return {"final_answer": answer, "assistant_texts": [], "tool_calls": [], "delegations": [], "approvals": [],
            "permission_denials": []}


class WorktreeCleanupHookTaskTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        patcher = mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.root / "xdg"),
                                               "E2E_CLEANUP_WAIT_SECONDS": "2"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.task = json.loads((TASKS_ROOT / "T67.json").read_text(encoding="utf-8"))
        self.repo = self.root / "work" / "repo"
        self.work = self.repo.parent
        self.base = graders.materialize_fixture(self.task, FIXTURES_ROOT, TASKS_ROOT, self.repo)

    def orca(self, *arguments: str) -> dict[str, Any]:
        env = {**os.environ, "FAKE_ORCA_STATE": str(self.work / "orca-state" / "state.json"),
               "ORCA_TERMINAL_HANDLE": "term_demo_a"}
        done = subprocess.run([str(self.work / "fake-bin" / "orca"), *arguments, "--json"], cwd=self.repo, env=env,
                              capture_output=True, text=True, check=False)
        return json.loads(done.stdout)

    def reference(self) -> None:
        env = {**os.environ, "PYTHONPATH": str(TASKS_ROOT / "reference"), "PYTHONDONTWRITEBYTECODE": "1"}
        subprocess.run([sys.executable, "-B", str(TASKS_ROOT / "reference" / "T67" / "apply.py"), str(self.repo)],
                       cwd=self.repo, env=env, check=True, capture_output=True, text=True)

    def failed(self, answer: str = QUESTION) -> set[str]:
        result = graders.grade_run(self.task, self.repo, self.base, make_view(answer), TASKS_ROOT, self.root / "grade")
        return {check["id"] for check in result["checks"] if not check["passed"]}

    def create_and_run_worker(self) -> str:
        made = self.orca("worktree", "create", "--repo", "name:demo-b", "--name", "ABC-123", "--branch", BRANCH)
        identifier = made["result"]["worktree"]["id"]
        self.orca("orchestration", "worker-start", "--worktree", f"id:{identifier}", "--agent", "claude", "--spec", "x")
        return identifier

    def test_수정하지_않은_실행은_작업_공간을_만들지_않아_필수_검사가_실패하고_참조_해법은_모두_통과한다(self):
        """아무것도 하지 않으면 훅이 지울 것이 없어 실패하고, 참조 해법은 훅의 분리 실행이 지운 뒤 모든 검사를 통과한다."""
        # given
        untouched = self.failed()

        # when
        self.reference()
        solved = self.failed()

        # then
        self.assertEqual(untouched, {"page-size-50", "worker-pushed-branch", "removed-by-hook",
                                     "remote-and-clones-kept"})
        self.assertEqual(solved, set())

    def test_세션이_스스로_지운_작업_공간은_훅이_지운_것으로_인정하지_않는다(self):
        """같은 결과 상태여도 `worktree rm`이 세션의 작업 폴더에서 호출되었으면 removed-by-hook이 실패한다."""
        # given
        identifier = self.create_and_run_worker()

        # when
        self.orca("worktree", "rm", "--worktree", f"id:{identifier}", "--delete-branch")

        # then
        self.assertEqual(self.failed(), {"page-size-50", "removed-by-hook"})

    def test_원격_브랜치나_주_클론이_사라지면_남겨야_할_것을_지킨_검사가_실패한다(self):
        """훅이 원격 브랜치를 지우면 remote-and-clones-kept가 실패한다."""
        # given
        self.reference()
        subprocess.run(["git", "-C", str(self.work / "demo-b-origin.git"), "branch", "-D", BRANCH], check=True,
                       capture_output=True)

        # when
        failed = self.failed()

        # then
        self.assertEqual(failed, {"worker-pushed-branch", "remote-and-clones-kept"})

    def test_과제_환경은_Orca_사용자_데이터_경로를_정하고_그_폴더를_만든다(self):
        """하네스가 ORCA_* 변수를 지우므로 훅의 실행 조건인 ORCA_USER_DATA_PATH를 과제가 정하고, 폴더는 설정이 만든다."""
        # given
        environment = command.task_environment(self.task, self.repo, self.work)

        # when
        path = Path(environment["ORCA_USER_DATA_PATH"])

        # then
        self.assertEqual(path, self.work / "orca-user-data")
        self.assertTrue(path.is_dir())
        self.assertEqual(environment["HEI5ENBUG_CLEANUP_RUN_SECONDS"], "45")

    def test_가짜_Orca는_worker_보고와_Dispatch를_세션이_읽는_명령으로_답한다(self):
        """worker를 시작한 뒤 orchestration check는 worker_done 메시지를, worker-show는 성공한 Dispatch를 돌려준다."""
        # given
        self.create_and_run_worker()

        # when
        checked = self.orca("orchestration", "check")["result"]["messages"]
        shown = self.orca("orchestration", "worker-show", "--dispatch", "ctx_1")["result"]["worker"]

        # then
        self.assertEqual([item["subject"] for item in checked], ["worker_done"])
        self.assertEqual(shown["state"], "succeeded")

    def test_질문으로_끝내지_않고_보고서로_끝내면_실패한다(self):
        """턴을 최종 보고서로 끝내면 ends-with-question이 실패한다."""
        # given
        self.reference()

        # when
        failed = self.failed("완료했습니다. 정리도 끝났습니다.")

        # then
        self.assertEqual(failed, {"ends-with-question"})
