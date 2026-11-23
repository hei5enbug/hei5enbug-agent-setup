"""Unit tests for the T161 evaluation task: a seeded Korean design document, and graders that tell the reads and the format script apart."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import test_e2e_eval_skill_issue_cases as cases

DOC = "docs/design/cache-expiry.ko.md"
PATTERNS_READ = {"id": "r2", "name": "Read", "input": {"file_path": "skills/docs-rewrite/references/patterns.md"},
                 "result_text": "", "is_error": False, "parent": None, "source": "main"}


SKILL_PATH = "/home/test/.codex/plugins/cache/demo/demo-plugin/1.0.0/skills/technical-design-writer/SKILL.md"


def shell_call(command: str) -> dict[str, Any]:
    return {"id": "c1", "name": "Bash", "input": {"command": command}, "result_text": "", "is_error": False,
            "parent": None, "source": "main"}


class DesignReviewTaskTest(cases.SkillIssueTaskCase):
    task_id = "T161"

    def reference(self) -> dict[str, Any]:
        return self.reference_view()

    def test_과제_정의는_파일과_검사_함수가_모두_있다(self) -> None:
        """T161의 프롬프트와 검사 함수가 있다."""
        # given
        # when
        problems = [name for name in [check["function"] for check in self.task["checks"] if check["kind"] == "custom"]
                    if f"def {name}(" not in (cases.TASKS_ROOT / "custom" / "T161.py").read_text(encoding="utf-8")]

        # then
        self.assertEqual([], problems)
        self.assertTrue((cases.TASKS_ROOT / self.task["prompt_file"]).is_file())

    def test_시드_문서는_긴_줄과_네_번째_제목_수준과_줄_끝_공백을_가진다(self) -> None:
        """시드 문서에 check_format.py가 세 위반을 정확히 보고한다."""
        # given
        script = cases.REPO_ROOT / "skills/technical-design-writer/scripts/check_format.py"

        # when
        completed = subprocess.run([sys.executable, str(script), str(self.repo / DOC)], capture_output=True, text=True,
                                   check=False)
        rules = sorted({line.split('"')[3] for line in completed.stdout.replace("{", "\n").split("\n") if '"rule"' in line})

        # then
        self.assertEqual((1, ["heading_level", "long_line", "trailing_space"]), (completed.returncode, rules))

    def test_아무것도_하지_않은_실행은_스킬_호출과_보고_검사에서_실패한다(self) -> None:
        """빈 실행은 skill-invoked와 보고 검사가 실패한다."""
        # given
        empty = {**self.reference(), "final_answer": "", "tool_calls": []}

        # when
        passed = self.grade(empty)

        # then
        self.assertEqual((False, False, False), (passed["skill-invoked"], passed["translationese-reported"],
                                                  passed["success"]))

    def test_번역투_참조를_읽고_스크립트를_돌려_세_문제를_보고한_참조_실행은_모든_검사를_통과한다(self) -> None:
        """참조 실행은 필수 검사와 선택 검사 넷이 모두 참이다."""
        # given
        # when
        passed = self.grade(self.reference())

        # then
        self.assertTrue(passed["success"], passed)
        self.assertEqual((True, True, True, True), (passed["read-translationese"], passed["patterns-not-read"],
                                                    passed["format-script-ran"], passed["trailing-space-reported"]))

    def test_patterns_전체를_읽고_스크립트를_쓰지_않은_변경_전_경로는_필수_검사를_통과하고_선택_검사만_거짓이다(self) -> None:
        """변경 전 경로는 success이고 read-translationese, patterns-not-read, format-script-ran, trailing-space-reported가 거짓이다."""
        # given
        before = {**self.reference(), "tool_calls": [self.reference()["tool_calls"][0], PATTERNS_READ],
                  "final_answer": "11번째 줄이 120자를 넘는 긴 줄이고 19번째 줄은 #### 제목이며 에 의해를 쓴 문장이 있다."}

        # when
        passed = self.grade(before)

        # then
        self.assertTrue(passed["success"], passed)
        self.assertEqual((False, False, False, False), (passed["read-translationese"], passed["patterns-not-read"],
                                                        passed["format-script-ran"], passed["trailing-space-reported"]))

    def test_문서를_고친_실행은_저장소_불변_검사에서_실패한다(self) -> None:
        """검토 과제에서 설계 문서를 고치면 repo-unchanged가 실패한다."""
        # given
        path = self.repo / DOC
        path.write_text(path.read_text(encoding="utf-8").replace("캐시", "캐쉬"), encoding="utf-8")

        # when
        passed = self.grade(self.reference())

        # then
        self.assertFalse(passed["repo-unchanged"])

    def test_스킬_문서를_셸로_읽은_Codex_실행은_skill_invoked를_통과한다(self) -> None:
        """Skill 도구 호출이 없어도 cat, sed, rg로 SKILL.md를 읽으면 skill-invoked가 참이다."""
        # given
        rest = [call for call in self.reference()["tool_calls"] if call["name"] != "Skill"]
        commands = [f"cat {SKILL_PATH}", f"sed -n '1,120p' {SKILL_PATH}", f"rg -n review {SKILL_PATH}"]

        # when
        passed = [self.grade({**self.reference(), "tool_calls": [shell_call(command), *rest]})["skill-invoked"]
                  for command in commands]

        # then
        self.assertEqual([True, True, True], passed)

    def test_스킬_문서를_읽지_않고_목록만_본_실행은_skill_invoked에서_실패한다(self) -> None:
        """SKILL.md를 이름으로 찾기만 하거나 다른 스킬의 SKILL.md를 읽으면 skill-invoked가 거짓이다."""
        # given
        rest = [call for call in self.reference()["tool_calls"] if call["name"] != "Skill"]
        commands = ["pwd && rg --files -g AGENTS.md -g 'SKILL.md'", f"ls {SKILL_PATH}",
                    "cat /home/test/skills/docs-rewrite/SKILL.md"]

        # when
        passed = [self.grade({**self.reference(), "tool_calls": [shell_call(command), *rest]})["skill-invoked"]
                  for command in commands]

        # then
        self.assertEqual([False, False, False], passed)
