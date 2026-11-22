"""Unit tests for the T80 and T81 evaluation tasks: their seeded stub gh, and graders that fail broken runs offline."""

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

REPO = "demo-org/demo-plugin"
BAD_BODY = """## Summary
The overview prints empty sections.

## Observations
- Seen in ABC-123.

## Gap in current rules
Step 3 prints every heading.

## Proposal
1. Leave out the empty sections of ABC-123.

## Acceptance criteria
1. The report of ABC-123 has no empty heading.

## Evidence
- Related: #7.
"""


class SkillIssueTaskCase(unittest.TestCase):
    task_id = ""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.task = json.loads((TASKS_ROOT / f"{self.task_id}.json").read_text(encoding="utf-8"))
        self.repo = self.root / "work" / "repo"
        self.work = self.repo.parent
        self.base = graders.materialize_fixture(self.task, FIXTURES_ROOT, TASKS_ROOT, self.repo)

    def script(self, relative: str) -> None:
        subprocess.run([sys.executable, "-B", str(TASKS_ROOT / "reference" / relative), str(self.repo)], cwd=self.repo,
                       env={**os.environ, "PYTHONPATH": str(TASKS_ROOT / "reference")}, check=True,
                       capture_output=True, text=True)

    def stub(self, *arguments: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "FAKE_GH_LOG": str(self.work / "gh.log"), "FAKE_GH_STATE": str(self.work / "gh-state")}
        return subprocess.run([str(self.work / "fake-bin" / "gh"), *arguments], input=stdin, text=True,
                              capture_output=True, env=env, check=True)

    def reference_view(self) -> dict[str, Any]:
        return json.loads((TASKS_ROOT / "reference" / self.task_id / "view.json").read_text(encoding="utf-8"))

    def grade(self, view: dict[str, Any]) -> dict[str, bool]:
        result = graders.grade_run(self.task, self.repo, self.base, view, TASKS_ROOT, self.root / "grade")
        return {check["id"]: check["passed"] for check in result["checks"]} | {"success": result["success"]}

    def definition_problems(self) -> list[str]:
        source = (TASKS_ROOT / "custom" / f"{self.task_id}.py").read_text(encoding="utf-8")
        functions = [check["function"] for check in self.task["checks"] if check["kind"] == "custom"]
        problems = [name for name in functions if f"def {name}(" not in source]
        problems += [name for name in (self.task["prompt_file"], self.task["setup"]) if not (TASKS_ROOT / name).is_file()]
        return problems


class UndecidedChoiceTaskTest(SkillIssueTaskCase):
    task_id = "T80"

    def test_과제_정의는_파일과_검사_함수가_모두_있고_환경은_가짜_gh를_앞세운다(self) -> None:
        """T80의 프롬프트, 설정, 검사 함수가 있고 환경 변수가 실행 폴더의 가짜 gh와 로그를 가리킨다."""
        # given
        work = self.work

        # when
        environment = command.task_environment(self.task, self.repo, work)

        # then
        self.assertEqual([], self.definition_problems())
        self.assertTrue(environment["PATH"].startswith(f"{work}/fake-bin:"))
        self.assertEqual((str(work / "gh.log"), str(work / "gh-state")),
                         (environment["FAKE_GH_LOG"], environment["FAKE_GH_STATE"]))

    def test_시드_트래커에는_갭을_다루는_열린_이슈가_없고_저장소는_플러그인_선언을_가진다(self) -> None:
        """T80 트래커 목록은 무관한 두 이슈뿐이고 저장소 루트에 issue-target.json이 있다."""
        # given
        listing = self.stub("issue", "list", "--repo", REPO, "--state", "all")

        # when
        issues = json.loads(listing.stdout)

        # then
        self.assertEqual([7, 15], sorted(issue["number"] for issue in issues))
        self.assertTrue((self.repo / "issue-target.json").is_file())

    def test_아무것도_하지_않은_실행은_질문과_스킬_호출_검사에서_실패한다(self) -> None:
        """질문도 스킬 호출도 없는 빈 실행은 question-asked와 skill-invoked가 실패한다."""
        # given
        view = {"final_answer": "", "assistant_texts": [], "tool_calls": [], "delegations": [], "approvals": [],
                "permission_denials": []}

        # when
        passed = self.grade(view)

        # then
        self.assertEqual((False, False, False), (passed["question-asked"], passed["skill-invoked"], passed["success"]))

    def test_정해지지_않은_선택을_묻고_쓰지_않는_참조_실행은_모든_필수_검사를_통과한다(self) -> None:
        """질문 도구로 제목 처리를 묻고 트래커에 쓰지 않은 실행은 success다."""
        # given
        self.script("T80/apply.py")

        # when
        passed = self.grade(self.reference_view())

        # then
        self.assertTrue(passed["success"], passed)

    def test_선택을_혼자_정하고_이슈를_쓰는_깨진_실행은_쓰기_검사에서_실패한다(self) -> None:
        """답을 받기 전에 gh issue create를 부른 실행은 no-write-before-answer가 실패한다."""
        # given
        self.script("T80/broken_silent_write.py")

        # when
        passed = self.grade(self.reference_view())

        # then
        self.assertEqual((False, False), (passed["no-write-before-answer"], passed["success"]))

    def test_질문_없이_초안만_보여주고_끝난_실행은_질문_검사에서_실패한다(self) -> None:
        """제목 선택을 묻는 문장이 없는 최종 답은 question-asked가 실패한다."""
        # given
        self.script("T80/apply.py")
        view = {**self.reference_view(), "tool_calls": self.reference_view()["tool_calls"][:1],
                "final_answer": "I drafted the issue and kept the heading of empty sections."}

        # when
        passed = self.grade(view)

        # then
        self.assertEqual((False, True), (passed["question-asked"], passed["no-write-before-answer"]))

    def test_질문_도구_없이_최종_답에서_선택을_물어도_질문_검사를_통과한다(self) -> None:
        """AskUserQuestion이 없어도 최종 답이 제목 처리 선택을 물으면 통과한다."""
        # given
        self.script("T80/apply.py")
        view = {**self.reference_view(), "tool_calls": self.reference_view()["tool_calls"][:1]}

        # when
        passed = self.grade(view)

        # then
        self.assertTrue(passed["question-asked"])

    def test_본문이_쓰였다면_조건_문구와_식별자_규칙을_어긴_본문은_본문_검사에서_실패한다(self) -> None:
        """Proposal 항목이 조건 문구로 시작하지 않고 ABC-123이 Proposal에 있는 본문은 body-contract가 실패한다."""
        # given
        self.stub("issue", "create", "--repo", REPO, "--title", "t", "--label", "enhancement", "--body-file", "-",
                  stdin=BAD_BODY)

        # when
        passed = self.grade(self.reference_view())

        # then
        self.assertEqual((False, False), (passed["body-contract"], passed["success"]))

    def test_저장소_파일을_바꾼_실행은_저장소_불변_검사에서_실패한다(self) -> None:
        """스킬이 로컬 파일을 쓰면 repo-unchanged가 실패한다."""
        # given
        (self.repo / "issue-draft.md").write_text("draft\n", encoding="utf-8")

        # when
        passed = self.grade(self.reference_view())

        # then
        self.assertFalse(passed["repo-unchanged"])


class CoveredGapTaskTest(SkillIssueTaskCase):
    task_id = "T81"

    def test_과제_정의는_파일과_검사_함수가_모두_있다(self) -> None:
        """T81의 프롬프트, 설정, 검사 함수가 있다."""
        # given
        # when
        problems = self.definition_problems()

        # then
        self.assertEqual([], problems)

    def test_시드_트래커는_갭을_이미_다루는_12번_열린_이슈를_목록에_보인다(self) -> None:
        """T81 목록에는 현재 계정이 쓴 열린 12번 이슈와 닫힌 7번이 있다."""
        # given
        listing = self.stub("issue", "list", "--repo", REPO, "--state", "all")

        # when
        issues = {issue["number"]: issue for issue in json.loads(listing.stdout)}

        # then
        self.assertEqual((12, "OPEN", "demo-user"), (12, issues[12]["state"], issues[12]["author"]["login"]))
        self.assertEqual("CLOSED", issues[7]["state"])

    def test_아무것도_하지_않은_실행은_중복_보고_검사에서_실패한다(self) -> None:
        """검색도 보고도 없는 빈 실행은 duplicate-reported와 duplicate-search-ran이 실패한다."""
        # given
        view = {"final_answer": "", "assistant_texts": [], "tool_calls": [], "delegations": [], "approvals": [],
                "permission_denials": []}

        # when
        passed = self.grade(view)

        # then
        self.assertEqual((False, False, False), (passed["duplicate-reported"], passed["duplicate-search-ran"],
                                                 passed["success"]))

    def test_검색해_중복을_보고하고_새_이슈를_만들지_않은_참조_실행은_통과한다(self) -> None:
        """12번을 보고하고 아무것도 만들지 않은 실행은 success다."""
        # given
        self.script("T81/apply.py")

        # when
        passed = self.grade(self.reference_view())

        # then
        self.assertTrue(passed["success"], passed)

    def test_중복_검색을_건너뛰고_두_번째_이슈를_만든_깨진_실행은_새_이슈_검사에서_실패한다(self) -> None:
        """검색 없이 gh issue create를 부른 실행은 no-new-issue와 duplicate-search-ran이 실패한다."""
        # given
        self.script("T81/broken_second_issue.py")

        # when
        passed = self.grade(self.reference_view())

        # then
        self.assertEqual((False, False, False), (passed["no-new-issue"], passed["duplicate-search-ran"],
                                                 passed["success"]))

    def test_열린_이슈_본문을_덮어써서_원래_Proposal을_지운_실행은_보존_검사에서_실패한다(self) -> None:
        """12번에 gh issue edit으로 다른 본문을 쓰면 covering-issue-intact가 실패한다."""
        # given
        self.script("T81/apply.py")
        self.stub("issue", "edit", "12", "--repo", REPO, "--body-file", "-", stdin="## Summary\nreplaced\n")

        # when
        passed = self.grade(self.reference_view())

        # then
        self.assertEqual((False, False), (passed["covering-issue-intact"], passed["success"]))

    def test_원래_Proposal을_지키며_12번_본문에_관찰을_더한_수정은_보존_검사를_통과한다(self) -> None:
        """갱신 규칙대로 기존 본문을 병합한 편집은 covering-issue-intact를 통과한다."""
        # given
        self.script("T81/apply.py")
        original = json.loads(self.stub("issue", "view", "12", "--repo", REPO, "--json", "body").stdout)["body"]
        self.stub("issue", "edit", "12", "--repo", REPO, "--body-file", "-", stdin=original + "\n- merged note\n")

        # when
        passed = self.grade(self.reference_view())

        # then
        self.assertTrue(passed["covering-issue-intact"])

    def test_스킬을_부르지_않은_실행은_스킬_호출_검사에서_실패한다(self) -> None:
        """Skill 호출이 없으면 나머지가 통과해도 skill-invoked가 실패한다."""
        # given
        self.script("T81/apply.py")
        view = {**self.reference_view(), "tool_calls": []}

        # when
        passed = self.grade(view)

        # then
        self.assertEqual((False, False), (passed["skill-invoked"], passed["success"]))


if __name__ == "__main__":
    unittest.main()
