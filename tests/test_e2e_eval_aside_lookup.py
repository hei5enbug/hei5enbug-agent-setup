"""Unit tests for the T160 evaluation task: its stub aside, and graders that fail broken runs offline."""

from __future__ import annotations

import os
import subprocess
from typing import Any

import test_e2e_eval_skill_issue_cases as cases
from harness import command

AGENT = "hei5enbug-agent-setup:browser-reader"
ANSWER = "Status: In Review. Source: https://example.com/tracker/ABC-123"
SKILL_CALL = {"id": "s1", "name": "Skill", "input": {"skill": "hei5enbug-agent-setup:aside-browser-tasks"},
              "result_text": "", "is_error": False, "parent": None, "source": "main"}
MAIN_ASIDE = {"id": "b1", "name": "Bash", "input": {"command": "aside exec 'find ABC-123'"}, "result_text": "",
              "is_error": False, "parent": None, "source": "main"}


def view(calls: list[dict[str, Any]], answer: str = ANSWER, agents: int = 0) -> dict[str, Any]:
    return {"final_answer": answer, "assistant_texts": [], "tool_calls": calls, "approvals": [],
            "permission_denials": [], "delegations": [{"type": AGENT}] * agents}


class AsideLookupTaskTest(cases.SkillIssueTaskCase):
    task_id = "T160"

    def aside(self, *arguments: str, mode: str = "") -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "FAKE_ASIDE_LOG": str(self.work / "aside.log"), "FAKE_ASIDE_MODE": mode}
        return subprocess.run([str(self.work / "fake-bin" / "aside"), *arguments], text=True, capture_output=True,
                              env=env, cwd=self.repo, check=False)

    def test_과제_정의는_파일과_검사_함수가_모두_있고_환경은_가짜_aside를_앞세운다(self) -> None:
        """T160의 프롬프트, 설정, 검사 함수가 있고 환경 변수가 실행 폴더의 가짜 aside와 로그를 가리킨다."""
        # given
        work = self.work

        # when
        environment = command.task_environment(self.task, self.repo, work)

        # then
        self.assertEqual([], self.definition_problems())
        self.assertTrue(environment["PATH"].startswith(f"{work}/fake-bin:"))
        self.assertEqual(str(work / "aside.log"), environment["FAKE_ASIDE_LOG"])

    def test_가짜_aside는_exec에서_도구_기록과_세션을_내고_실패_모드에서는_세션_없이_끝난다(self) -> None:
        """exec는 기록 줄 40개와 세션 줄을 출력하고 fail 모드는 세션 없이 1로 끝나며 두 호출 모두 로그에 남는다."""
        # given
        # when
        done = self.aside("exec", "find ABC-123")
        failed = self.aside("exec", "find ABC-123", mode="fail")

        # then
        self.assertEqual((0, 40, True), (done.returncode, done.stdout.count("TRACE-NOISE"),
                                          "created new session: sess-demo-001" in done.stdout))
        self.assertEqual((1, False), (failed.returncode, "created new session" in failed.stdout))
        self.assertEqual(2, len((self.work / "aside.log").read_text(encoding="utf-8").splitlines()))

    def test_아무것도_하지_않은_실행은_스킬_호출과_조회_검사에서_실패한다(self) -> None:
        """스킬도 aside도 없고 답도 비어 있으면 skill-invoked, aside-ran, status-and-source가 실패한다."""
        # given
        empty = view([], "")

        # when
        passed = self.grade(empty)

        # then
        self.assertEqual((False, False, False, False), (passed["skill-invoked"], passed["aside-ran"],
                                                        passed["status-and-source"], passed["success"]))

    def test_에이전트에_맡기고_상태와_출처만_답한_참조_실행은_필수_검사와_위임_검사를_모두_통과한다(self) -> None:
        """browser-reader에 맡긴 참조 실행은 success이고 위임 관련 선택 검사 둘도 참이다."""
        # given
        self.script("T160/apply.py")

        # when
        passed = self.grade(self.reference_view())

        # then
        self.assertTrue(passed["success"], passed)
        self.assertEqual((True, True), (passed["browser-reader-used"], passed["main-ran-no-aside"]))

    def test_메인_세션이_직접_조회한_실행도_필수_검사를_통과하고_위임_검사만_거짓이다(self) -> None:
        """위임 없이 메인이 aside를 돌린 변경 전 경로는 success이고 browser-reader-used와 main-ran-no-aside가 거짓이다."""
        # given
        self.script("T160/apply.py")

        # when
        passed = self.grade(view([SKILL_CALL, MAIN_ASIDE]))

        # then
        self.assertTrue(passed["success"], passed)
        self.assertEqual((False, False), (passed["browser-reader-used"], passed["main-ran-no-aside"]))

    def test_도구_기록이_최종_답에_섞이면_기록_검사에서_실패한다(self) -> None:
        """가짜 exec의 기록 줄이 최종 답에 있으면 no-trace-in-answer가 실패한다."""
        # given
        self.script("T160/apply.py")
        noisy = view(self.reference_view()["tool_calls"], ANSWER + "\n[tool] TRACE-NOISE step 3", 1)

        # when
        passed = self.grade(noisy)

        # then
        self.assertEqual((False, False), (passed["no-trace-in-answer"], passed["success"]))

    def test_스크린샷을_찍은_실행은_읽기_전용_검사에서_실패한다(self) -> None:
        """aside repl에 screenshot이 든 호출이 로그에 있으면 read-only가 실패한다."""
        # given
        self.script("T160/apply.py")
        self.aside("repl", "await page.screenshot({ path: 'shot.png' })")

        # when
        passed = self.grade(self.reference_view())

        # then
        self.assertEqual((False, False), (passed["read-only"], passed["success"]))

    def test_저장소_파일을_바꾼_실행은_저장소_불변_검사에서_실패한다(self) -> None:
        """조회 과제에서 로컬 파일을 쓰면 repo-unchanged가 실패한다."""
        # given
        self.script("T160/apply.py")
        (self.repo / "answer.md").write_text("In Review\n", encoding="utf-8")

        # when
        passed = self.grade(self.reference_view())

        # then
        self.assertFalse(passed["repo-unchanged"])
