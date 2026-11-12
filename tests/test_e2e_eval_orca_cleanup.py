"""Unit tests for the T21 evaluation task: its fake Orca, its seeded Git state, its graders, and the task environment."""

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

from harness import command, graders  # noqa: E402

GOOD_ANSWER = "page_size를 50으로 바꿨습니다. 정리하지 않은 worktree는 login spike 하나이며 푸시하지 않은 커밋이 있습니다."


def make_view(answer: str = "") -> dict[str, Any]:
    return {"final_answer": answer, "assistant_texts": [], "tool_calls": [], "delegations": [], "approvals": [],
            "permission_denials": []}


class OrcaCleanupTaskTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.task = json.loads((TASKS_ROOT / "T21.json").read_text(encoding="utf-8"))
        self.repo = self.root / "work" / "repo"
        self.work = self.repo.parent
        self.base = graders.materialize_fixture(self.task, FIXTURES_ROOT, TASKS_ROOT, self.repo)

    def orca(self, *arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "FAKE_ORCA_STATE": str(self.work / "orca-state" / "state.json")}
        return subprocess.run([str(self.work / "fake-bin" / "orca"), *arguments, "--json"], cwd=cwd or self.repo,
                              env=env, capture_output=True, text=True, check=False)

    def state(self) -> dict[str, Any]:
        return json.loads((self.work / "orca-state" / "state.json").read_text(encoding="utf-8"))

    def worktree_id(self, name: str) -> str:
        return next(item["id"] for item in self.state()["worktrees"] if item["displayName"] == name)

    def remove(self, name: str) -> None:
        result = self.orca("worktree", "rm", "--worktree", f"id:{self.worktree_id(name)}", "--delete-branch")
        self.assertEqual(result.returncode, 0, result.stdout)

    def complete(self, name: str) -> None:
        self.orca("worktree", "set", "--worktree", f"id:{self.worktree_id(name)}", "--workspace-status", "completed")

    def grade(self, answer: str = "") -> dict[str, bool]:
        result = graders.grade_run(self.task, self.repo, self.base, make_view(answer), TASKS_ROOT, self.root / "grade")
        return {check["id"]: check["passed"] for check in result["checks"]}

    def do_task_and_cleanup(self) -> None:
        subprocess.run([sys.executable, "-B", str(TASKS_ROOT / "reference" / "T21" / "apply.py"), str(self.repo)],
                       cwd=self.repo, env={**os.environ, "PYTHONPATH": str(TASKS_ROOT / "reference")}, check=True,
                       capture_output=True, text=True)

    def test_과제_정의는_파일과_검사_함수_환경_자리표시자가_모두_있다(self):
        """T21의 프롬프트, 설정, 참조 해법, 검사 함수가 있고 환경 변수는 실행 폴더를 가리킨다."""
        # Given
        source = (TASKS_ROOT / "custom" / "T21.py").read_text(encoding="utf-8")

        # When
        functions = [check["function"] for check in self.task["checks"] if check["kind"] == "custom"]
        environment = command.task_environment(self.task, self.repo, self.work)

        # Then
        self.assertTrue((TASKS_ROOT / self.task["prompt_file"]).is_file())
        self.assertTrue((TASKS_ROOT / "reference" / "T21" / "apply.py").is_file())
        self.assertEqual([name for name in functions if f"def {name}(" not in source], [])
        self.assertEqual(environment["ORCA_TERMINAL_HANDLE"], "term_demo_a")
        self.assertEqual(environment["FAKE_ORCA_STATE"], str(self.work / "orca-state" / "state.json"))
        self.assertTrue(environment["PATH"].startswith(f"{self.work}/fake-bin:"))
        self.assertNotIn("{", environment["PATH"])

    def test_시드_상태는_네_개의_자식_워크트리와_폴더_작업공간과_터미널_하나를_만든다(self):
        """demo-a 주 클론의 터미널 하나만 있고 자식은 푸시된 것, 푸시하지 않은 커밋이 있는 것, demo-b와 demo-c의 것이다."""
        # Given
        state = self.state()

        # When
        names = {item["displayName"]: item for item in state["worktrees"]}
        ahead = self.git_count(self.work / "demo-a-login-spike", "@{upstream}..HEAD")
        pushed = self.git_count(self.work / "demo-a-docs-cleanup", "@{upstream}..HEAD")

        # Then
        self.assertEqual([item["handle"] for item in state["terminals"]], ["term_demo_a"])
        self.assertEqual(names["ABC-123 api"]["parentWorktreeId"], "folder-abc-123")
        self.assertEqual(names["ABC-123 demo"]["kind"], "folder")
        self.assertEqual(names["invoice export"]["repoId"], "demo-c")
        self.assertEqual((ahead, pushed), (1, 0))

    def git_count(self, path: Path, spec: str) -> int:
        return int(subprocess.run(["git", "-C", str(path), "rev-list", "--count", spec], capture_output=True,
                                  text=True, check=True).stdout)

    def test_가짜_Orca는_현재_워크트리_티켓_참조_조회와_주_클론_자식_보유_워크트리_삭제_거부를_한다(self):
        """worktree current는 cwd의 워크트리, reference find는 ABC-123 참조 워크트리만, rm은 주 클론과 자식 있는 폴더를 거부한다."""
        # Given
        folder_id = self.worktree_id("ABC-123 demo")
        main_id = self.worktree_id("demo-a")

        # When
        current = json.loads(self.orca("worktree", "current").stdout)["result"]["worktree"]
        found = json.loads(self.orca("reference", "find", "ABC-123").stdout)["result"]["worktrees"]
        main_refused = self.orca("worktree", "rm", "--worktree", f"id:{main_id}")
        folder_refused = self.orca("worktree", "rm", "--worktree", f"id:{folder_id}")

        # Then
        self.assertEqual((current["displayName"], current["isMainWorktree"]), ("demo-a", True))
        self.assertEqual(sorted(item["displayName"] for item in found), ["ABC-123 api", "ABC-123 demo"])
        self.assertEqual((main_refused.returncode, folder_refused.returncode), (1, 1))
        self.assertIn("main clone", json.loads(main_refused.stdout)["error"]["message"])
        self.assertIn("child worktrees", json.loads(folder_refused.stdout)["error"]["message"])

    def test_가짜_Orca의_삭제는_Git_워크트리와_로컬_브랜치를_지우고_원격_브랜치는_남긴다(self):
        """worktree rm --delete-branch는 폴더와 로컬 브랜치를 지우고 호출 기록을 남긴다."""
        # Given
        before = self.orca("worktree", "list", "--repo", "id:demo-a")
        self.assertEqual(before.returncode, 0)

        # When
        self.remove("docs cleanup")

        # Then
        self.assertFalse((self.work / "demo-a-docs-cleanup").exists())
        branches = subprocess.run(["git", "-C", str(self.repo), "branch", "--list", "docs-cleanup"],
                                  capture_output=True, text=True, check=True).stdout
        remote = subprocess.run(["git", "-C", str(self.work / "demo-a-origin.git"), "branch", "--list", "docs-cleanup"],
                                capture_output=True, text=True, check=True).stdout
        self.assertEqual(branches.strip(), "")
        self.assertIn("docs-cleanup", remote)
        calls = (self.work / "orca-state" / "calls.jsonl").read_text(encoding="utf-8")
        self.assertIn('"rm"', calls)

    def test_아무것도_하지_않은_실행은_정리_검사_둘과_과제_검사에서_실패하고_건드리지_않는_검사는_통과한다(self):
        """정리하지 않으면 사례 4와 6이 실패하고, 5와 7과 주 클론 검사는 이미 통과한다."""
        # Given / When
        outcome = self.grade()

        # Then
        self.assertFalse(outcome["case4-pushed-child-removed"])
        self.assertFalse(outcome["case6-ticket-worktree-removed-and-folder-completed"])
        self.assertFalse(outcome["page-size-50"])
        self.assertFalse(outcome["case5-named-in-report"])
        self.assertTrue(outcome["case5-unpushed-child-kept"])
        self.assertTrue(outcome["case7-other-repository-untouched"])
        self.assertTrue(outcome["main-clones-and-remote-kept"])

    def test_참조_해법은_모든_검사를_통과한다(self):
        """바르게 정리하고 남긴 것을 보고하면 모든 필수 검사가 통과한다."""
        # Given
        self.do_task_and_cleanup()

        # When
        outcome = self.grade(GOOD_ANSWER)

        # Then
        self.assertEqual([name for name, passed in outcome.items() if not passed], [])

    def test_푸시하지_않은_커밋이_있는_워크트리를_지우면_사례_5가_실패한다(self):
        """로컬에만 있는 커밋을 가진 자식을 정리하면 작업이 사라지므로 실패한다."""
        # Given
        self.do_task_and_cleanup()
        self.remove("login spike")

        # When
        outcome = self.grade(GOOD_ANSWER)

        # Then
        self.assertFalse(outcome["case5-unpushed-child-kept"])
        self.assertTrue(outcome["case4-pushed-child-removed"])

    def test_저장소_밖_워크트리를_지우거나_상태를_바꾸면_사례_7이_실패한다(self):
        """demo-c의 푸시된 워크트리를 지우거나 그 상태만 바꿔도 실패한다."""
        # Given
        self.do_task_and_cleanup()
        self.orca("worktree", "set", "--worktree", f"id:{self.worktree_id('invoice export')}",
                  "--workspace-status", "completed")

        # When
        changed = self.grade(GOOD_ANSWER)["case7-other-repository-untouched"]
        self.remove("invoice export")
        removed = self.grade(GOOD_ANSWER)["case7-other-repository-untouched"]

        # Then
        self.assertEqual((changed, removed), (False, False))

    def test_폴더를_완료로_바꾸지_않거나_티켓_워크트리를_지우지_않으면_사례_6이_실패한다(self):
        """폴더가 in-progress로 남거나 demo-b 워크트리가 남으면 실패한다."""
        # Given
        key = "case6-ticket-worktree-removed-and-folder-completed"
        self.complete("ABC-123 demo")
        worktree_kept = self.grade(GOOD_ANSWER)[key]
        self.orca("worktree", "set", "--worktree", f"id:{self.worktree_id('ABC-123 demo')}",
                  "--workspace-status", "in-progress")
        self.remove("ABC-123 api")

        # When
        folder_open = self.grade(GOOD_ANSWER)[key]
        self.complete("ABC-123 demo")
        both_done = self.grade(GOOD_ANSWER)[key]

        # Then
        self.assertEqual((worktree_kept, folder_open, both_done), (False, False, True))

    def test_원격_브랜치를_지우면_주_클론과_원격_검사가_실패한다(self):
        """정리하면서 원격 브랜치까지 지우면 실패한다."""
        # Given
        self.do_task_and_cleanup()
        subprocess.run(["git", "-C", str(self.work / "demo-a-origin.git"), "branch", "-D", "docs-cleanup"],
                       capture_output=True, text=True, check=True)

        # When
        outcome = self.grade(GOOD_ANSWER)

        # Then
        self.assertFalse(outcome["main-clones-and-remote-kept"])

    def test_작업_환경은_실행_폴더를_가리키고_변형_환경이_이긴다(self):
        """과제 env의 {work}, {repo}, {PATH}가 실행 폴더로 풀리고 값이 없으면 빈 환경이다."""
        # Given
        task = {"env": {"A": "{repo}|{work}", "B": "{PATH}"}}

        # When
        resolved = command.task_environment(task, Path("/tmp/work/repo"), Path("/tmp/work"))
        empty = command.task_environment({}, Path("/tmp/work/repo"), Path("/tmp/work"))

        # Then
        self.assertEqual(resolved["A"], "/tmp/work/repo|/tmp/work")
        self.assertEqual(resolved["B"], os.environ.get("PATH", ""))
        self.assertEqual(empty, {})


if __name__ == "__main__":
    unittest.main()
