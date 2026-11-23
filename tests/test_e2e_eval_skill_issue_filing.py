"""Unit tests for the answered filing tasks T110 and T111: graders that tell a run that filed and read back from one that
stopped, and that mark the check_filed.py run after the write as the check that separates the two variants."""

from __future__ import annotations

import json
import unittest
from typing import Any

import test_e2e_eval_skill_issue_cases as cases

REPO = cases.REPO
OPTIONAL = ("check-filed-ran-after-write",)
GOOD_110 = """## Summary
The weekly overview prints empty team sections as a heading followed by `(none)`.

## Observations
- Three of five sections were empty in one report.

## Gap in current rules
Step 3 of `skills/weekly-report/SKILL.md` prints every heading.

## Proposal
1. Under the condition that a team section has no items, leave that section out of the overview, heading included, in
   `instructions/shared-writing.md`, and apply the same rule to the monthly report.

## Acceptance criteria
1. A page with an empty section produces an overview that has no heading for it.

## Evidence
- Related: #7.
"""
MERGE_NOTE = ("\n- Under the condition that every team section of a week is empty, print one line that says no team "
              "section has items.\n")


def call(identifier: str, name: str, tool_input: dict[str, Any], source: str = "main") -> dict[str, Any]:
    return {"id": identifier, "name": name, "input": tool_input, "result_text": "ok", "is_error": False, "parent": None,
            "source": source}


def bash(identifier: str, text: str) -> dict[str, Any]:
    return call(identifier, "Bash", {"command": text})


SKILL = call("s1", "Skill", {"skill": "hei5enbug-agent-setup:skill-issue-creator"})
SEARCH = bash("b1", f"gh issue list --repo {REPO} --state all --search 'empty sections'")
CHECK = bash("b9", f"python3 scripts/check_filed.py github --repo {REPO} --number 200 --title t --label enhancement")


class FilingTaskCase(cases.SkillIssueTaskCase):
    def view(self, calls: list[dict[str, Any]], answer: str) -> dict[str, Any]:
        return {"final_answer": answer, "assistant_texts": [], "tool_calls": calls, "approvals": [],
                "permission_denials": []}

    def optional_results(self, passed: dict[str, bool]) -> tuple[bool, ...]:
        return tuple(passed[name] for name in OPTIONAL)

    def required_failures(self) -> list[str]:
        return [check["id"] for check in self.task["checks"] if check.get("required")]


class AnsweredUndecidedChoiceTest(FilingTaskCase):
    task_id = "T110"

    def file_issue(self, body: str = GOOD_110) -> None:
        self.stub("issue", "list", "--repo", REPO, "--state", "all", "--search", "empty sections")
        self.stub("issue", "create", "--repo", REPO, "--title", "weekly-report: leave out empty sections", "--label",
                  "enhancement", "--body-file", "-", stdin=body)
        self.stub("issue", "view", "200", "--repo", REPO, "--json", "title,body")

    def filed_calls(self, with_check: bool) -> list[dict[str, Any]]:
        write = bash("b5", f"gh issue create --repo {REPO} --title t --label enhancement --body-file - <<'EOF'\nbody\nEOF")
        if with_check:
            return [SKILL, SEARCH, write, CHECK]
        return [SKILL, write, bash("b6", f"gh issue view 200 --repo {REPO}")]

    def test_과제_정의는_파일과_검사_함수가_모두_있고_T80과_같은_시드를_쓴다(self) -> None:
        """T110의 프롬프트, 설정 파일, 검사 함수가 있고 T80과 같은 가짜 트래커를 시드한다."""
        # given
        # when
        problems = self.definition_problems()

        # then
        self.assertEqual([], problems)
        self.assertEqual("setup/T80.py", self.task["setup"])

    def test_정리한_이슈를_쓰고_다시_읽은_check_filed_없는_실행은_필수_검사를_모두_통과하고_선택_검사는_실패한다(self) -> None:
        """base처럼 check_filed.py 없이 작성하고 읽어 본 실행은 success이고 check-filed-ran-after-write는 거짓이다."""
        # given
        self.file_issue()
        view = self.view(self.filed_calls(False), "Filed issue #200: https://github.com/demo-org/demo-plugin/issues/200")

        # when
        passed = self.grade(view)

        # then
        self.assertTrue(passed["success"], passed)
        self.assertEqual((False,), self.optional_results(passed))

    def test_쓴_뒤_check_filed를_돌린_실행은_선택_검사도_통과한다(self) -> None:
        """쓴 뒤 check_filed.py를 돌린 실행은 선택 검사가 참이다."""
        # given
        self.file_issue()
        view = self.view(self.filed_calls(True), "Filed issue #200: https://github.com/demo-org/demo-plugin/issues/200")

        # when
        passed = self.grade(view)

        # then
        self.assertEqual((True,), self.optional_results(passed))
        self.assertTrue(passed["success"], passed)

    def test_스킬_문서를_셸로_읽은_Codex_실행은_skill_invoked를_통과하고_목록만_본_실행은_실패한다(self) -> None:
        """Skill 도구 호출이 없어도 cat으로 SKILL.md를 읽으면 skill-invoked가 참이고, 파일 목록만 본 실행은 거짓이다."""
        # given
        self.file_issue()
        path = "/home/test/.codex/plugins/cache/demo/demo-plugin/1.0.0/skills/skill-issue-creator/SKILL.md"
        rest = self.filed_calls(False)[1:]
        answer = "Filed issue #200: https://github.com/demo-org/demo-plugin/issues/200"

        # when
        read = self.grade(self.view([bash("r1", f"cat {path}"), *rest], answer))["skill-invoked"]
        listed = self.grade(self.view([bash("r1", "rg --files -g 'SKILL.md'"), *rest], answer))["skill-invoked"]

        # then
        self.assertEqual((True, False), (read, listed))

    def test_check_filed가_쓰기_전에_돈_실행은_순서_검사에서_실패한다(self) -> None:
        """쓰기 전에 check_filed를 돌린 실행은 check-filed-ran-after-write가 거짓이다."""
        # given
        self.file_issue()
        write = self.filed_calls(True)[3]
        view = self.view([SKILL, SEARCH, CHECK, write], "Filed #200 issues/200")

        # when
        passed = self.grade(view)

        # then
        self.assertFalse(passed["check-filed-ran-after-write"])

    def test_답을_받고도_질문에서_멈춘_실행은_쓰기_검사에서_실패한다(self) -> None:
        """AskUserQuestion으로 끝나고 쓰지 않은 실행은 no-blocking-question, filed-once, body-contract가 실패한다."""
        # given
        view = self.view([SKILL, call("q1", "AskUserQuestion", {"questions": [{"question": "which?"}]})], "Which one?")

        # when
        passed = self.grade(view)

        # then
        self.assertEqual((False, False, False, False), (passed["no-blocking-question"], passed["filed-once"],
                                                        passed["body-contract"], passed["success"]))

    def test_사용자가_버린_고정_문구를_남기거나_공통_파일을_빼고_쓴_본문은_답_검사에서_실패한다(self) -> None:
        """Proposal이 고정 문구를 유지하고 shared-writing.md를 말하지 않으면 answers-carried가 실패한다."""
        # given
        body = GOOD_110.replace("leave that section out of the overview, heading included, in\n   `instructions/shared-writing.md`,",
                                'keep the heading with the fixed line "No change this week" in')
        self.file_issue(body)
        view = self.view(self.filed_calls(False), "Filed issue #200 issues/200")

        # when
        passed = self.grade(view)

        # then
        self.assertEqual((False, False), (passed["answers-carried"], passed["success"]))

    def test_버린_고정_문구를_쓰지_말라는_부정_문장_속_예시는_답_검사에서_통과한다(self) -> None:
        """Proposal이 고정 문구를 부정문의 예시로만 들면 answers-carried가 통과한다."""
        # given
        body = GOOD_110.replace("heading included, in", 'heading included, and write no line such as "No change this week" in')
        self.file_issue(body)
        view = self.view(self.filed_calls(False), "Filed issue #200 issues/200")

        # when
        passed = self.grade(view)

        # then
        self.assertTrue(passed["answers-carried"], passed)

    def test_비공개_트래커에서_Proposal에_사례_식별자를_적은_본문은_본문_계약을_통과한다(self) -> None:
        """public이 false인 대상에서는 Proposal의 ABC-123이 body-contract를 깨지 않고, true이면 깬다."""
        # given
        body = GOOD_110.replace("1. Under the condition", "These rules come from ABC-123.\n1. Under the condition")
        self.file_issue(body)
        view = self.view(self.filed_calls(False), "Filed issue #200 issues/200")

        # when
        private = self.grade(view)["body-contract"]
        target = self.repo / "issue-target.json"
        target.write_text(target.read_text(encoding="utf-8").replace('"public": false', '"public": true'), encoding="utf-8")
        public = self.grade(view)["body-contract"]

        # then
        self.assertEqual((True, False), (private, public))

    def test_쓰고_다시_읽지_않은_실행은_읽기_검사에서_실패한다(self) -> None:
        """gh issue create 뒤에 어떤 읽기 호출도 없으면 read-back-after-write가 실패한다."""
        # given
        self.stub("issue", "create", "--repo", REPO, "--title", "t", "--label", "enhancement", "--body-file", "-",
                  stdin=GOOD_110)
        view = self.view(self.filed_calls(False)[:2], "Filed issue #200 issues/200")

        # when
        passed = self.grade(view)

        # then
        self.assertEqual((False, False), (passed["read-back-after-write"], passed["success"]))

    def test_같은_이슈를_두_번_만든_실행은_한_번만_쓰는_검사에서_실패한다(self) -> None:
        """gh issue create가 두 번이면 filed-once가 실패한다."""
        # given
        self.file_issue()
        self.stub("issue", "create", "--repo", REPO, "--title", "t2", "--label", "enhancement", "--body-file", "-",
                  stdin=GOOD_110)
        view = self.view(self.filed_calls(False), "Filed issue #200 issues/200")

        # when
        passed = self.grade(view)

        # then
        self.assertFalse(passed["filed-once"])


class AnsweredCoveredGapTest(FilingTaskCase):
    task_id = "T111"

    def original(self) -> str:
        return json.loads(self.stub("issue", "view", "12", "--repo", REPO, "--json", "body").stdout)["body"]

    def update(self, note: str = MERGE_NOTE) -> None:
        self.stub("issue", "list", "--repo", REPO, "--state", "all", "--search", "empty sections")
        self.stub("api", "user", "--jq", ".login")
        self.stub("issue", "edit", "12", "--repo", REPO, "--body-file", "-", stdin=self.original() + note)
        self.stub("issue", "view", "12", "--repo", REPO, "--json", "body")

    def updated_calls(self, with_check: bool) -> list[dict[str, Any]]:
        write = bash("b5", f"gh issue edit 12 --repo {REPO} --body-file - <<'EOF'\nbody\nEOF")
        if with_check:
            return [SKILL, SEARCH, write, CHECK]
        return [SKILL, SEARCH, write, bash("b6", f"gh issue view 12 --repo {REPO}")]

    def test_과제_정의는_파일과_검사_함수가_모두_있고_T81과_같은_시드를_쓴다(self) -> None:
        """T111의 프롬프트, 설정 파일, 검사 함수가 있고 T81과 같은 가짜 트래커를 시드한다."""
        # given
        # when
        problems = self.definition_problems()

        # then
        self.assertEqual([], problems)
        self.assertEqual("setup/T81.py", self.task["setup"])

    def test_12번에_답을_합쳐_고치고_읽어_본_check_filed_없는_실행은_필수_검사를_모두_통과하고_선택_검사는_실패한다(self) -> None:
        """base처럼 check_filed.py 없이 12번을 병합 수정한 실행은 success이고 check-filed-ran-after-write는 거짓이다."""
        # given
        self.update()
        view = self.view(self.updated_calls(False), "Updated #12 with the decision: https://github.com/demo-org/demo-plugin/issues/12")

        # when
        passed = self.grade(view)

        # then
        self.assertTrue(passed["success"], passed)
        self.assertEqual((False,), self.optional_results(passed))

    def test_고친_뒤_check_filed를_쓴_실행은_선택_검사도_통과한다(self) -> None:
        """쓴 뒤 check_filed.py를 돌린 실행은 선택 검사가 참이다."""
        # given
        self.update()
        view = self.view(self.updated_calls(True), "Updated #12 issues/12")

        # when
        passed = self.grade(view)

        # then
        self.assertEqual((True,), self.optional_results(passed))
        self.assertTrue(passed["success"], passed)

    def test_고치지_않고_질문에서_멈춘_실행은_병합_검사와_질문_검사에서_실패한다(self) -> None:
        """12번을 바꾸지 않고 AskUserQuestion으로 끝난 실행은 answer-merged와 no-blocking-question이 실패한다."""
        # given
        self.stub("issue", "list", "--repo", REPO, "--state", "all", "--search", "empty sections")
        view = self.view([SKILL, SEARCH, call("q1", "AskUserQuestion", {"questions": [{"question": "all empty?"}]})],
                         "Issue #12 already covers this; what should an all-empty week print?")

        # when
        passed = self.grade(view)

        # then
        self.assertEqual((False, False, False), (passed["answer-merged"], passed["no-blocking-question"], passed["success"]))

    def test_원래_규칙을_같은_뜻의_다른_문장으로_다시_쓴_수정은_원본_유지_검사를_통과한다(self) -> None:
        """Proposal이 원래 규칙을 낱말만 바꿔 유지하면 covering-issue-intact가 통과한다."""
        # given
        self.update()
        body = self.original().replace("leave that section out of the overview, heading included",
                                       "leave that section out of the overview completely, heading and paragraph included")
        self.stub("issue", "edit", "12", "--repo", REPO, "--body-file", "-", stdin=body + MERGE_NOTE)
        view = self.view(self.updated_calls(False), "Updated #12 issues/12")

        # when
        passed = self.grade(view)

        # then
        self.assertTrue(passed["covering-issue-intact"], passed)

    def test_스킬_문서를_셸로_읽은_Codex_실행은_skill_invoked를_통과한다(self) -> None:
        """T111에서도 cat으로 SKILL.md를 읽은 실행은 skill-invoked가 참이다."""
        # given
        self.update()
        path = "/home/test/.codex/plugins/cache/demo/demo-plugin/1.0.0/skills/skill-issue-creator/SKILL.md"
        view = self.view([bash("r1", f"cat {path}"), *self.updated_calls(False)[1:]], "Updated #12 issues/12")

        # when
        passed = self.grade(view)

        # then
        self.assertTrue(passed["skill-invoked"], passed)

    def test_원래_규칙을_heading_포함_없이_다른_낱말로_다시_쓴_수정은_원본_유지_검사를_통과한다(self) -> None:
        """no heading, 또는 omit과 including its heading으로 같은 규칙을 쓴 Proposal은 covering-issue-intact가 참이다."""
        # given
        rewrites = ("leave that section out of the overview completely: no heading, no `(none)`",
                    "omit that section from the overview completely, including its heading and any `(none)` placeholder")
        results = []

        # when
        for rewrite in rewrites:
            self.update()
            body = self.original().replace("leave that section out of the overview, heading included", rewrite)
            self.stub("issue", "edit", "12", "--repo", REPO, "--body-file", "-", stdin=body + MERGE_NOTE)
            results.append(self.grade(self.view(self.updated_calls(False), "Updated #12 issues/12"))["covering-issue-intact"])

        # then
        self.assertEqual([True, True], results)

    def test_Proposal을_모든_제목을_출력하라는_반대_규칙으로_바꾼_수정은_원본_유지_검사에서_실패한다(self) -> None:
        """원래 규칙을 빼고 heading과 (none)을 계속 쓰라는 Proposal은 covering-issue-intact가 거짓이다."""
        # given
        self.update()
        body = self.original().replace("leave that section out of the overview, heading included",
                                       "keep printing every section with its heading and write `(none)` under an empty one")
        self.stub("issue", "edit", "12", "--repo", REPO, "--body-file", "-", stdin=body + MERGE_NOTE)

        # when
        passed = self.grade(self.view(self.updated_calls(False), "Updated #12 issues/12"))

        # then
        self.assertFalse(passed["covering-issue-intact"], passed)

    def test_한_명령에서_고친_뒤_check_filed를_이어_돌린_실행은_쓴_뒤_실행으로_센다(self) -> None:
        """gh issue edit 뒤에 같은 Bash 호출 안에서 check_filed.py가 있으면 check-filed-ran-after-write가 참이다."""
        # given
        self.update()
        joined = bash("b5", f"gh issue edit 12 --repo {REPO} --body-file - < body.md; python3 scripts/check_filed.py github --repo {REPO} --number 12")
        view = self.view([SKILL, SEARCH, joined], "Updated #12 issues/12")

        # when
        passed = self.grade(view)

        # then
        self.assertTrue(passed["check-filed-ran-after-write"], passed)

    def test_답을_넣지_않고_다른_말만_덧붙인_수정은_병합_검사에서_실패한다(self) -> None:
        """12번 본문에 모든 섹션이 빈 경우의 규칙이 없으면 answer-merged가 실패한다."""
        # given
        self.update("\n- Seen again on a second page.\n")
        view = self.view(self.updated_calls(False), "Updated #12 issues/12")

        # when
        passed = self.grade(view)

        # then
        self.assertEqual((False, False), (passed["answer-merged"], passed["success"]))

    def test_답을_받고도_새_이슈를_만든_실행은_새_이슈_검사에서_실패한다(self) -> None:
        """gh issue create로 둘째 이슈를 만들면 no-new-issue가 실패한다."""
        # given
        self.update()
        self.stub("issue", "create", "--repo", REPO, "--title", "t", "--label", "enhancement", "--body-file", "-",
                  stdin=GOOD_110)
        view = self.view(self.updated_calls(False), "Updated #12 issues/12")

        # when
        passed = self.grade(view)

        # then
        self.assertEqual((False, False), (passed["no-new-issue"], passed["success"]))


if __name__ == "__main__":
    unittest.main()
