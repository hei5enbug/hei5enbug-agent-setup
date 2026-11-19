"""Offline proof of the suggest-commit evaluation cases T17, T78, and T79: reference passes, broken runs fail."""

from __future__ import annotations

import json
import os
import shutil
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

from harness import graders  # noqa: E402

GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "Demo Dev", "GIT_AUTHOR_EMAIL": "dev@example.com",
           "GIT_COMMITTER_NAME": "Demo Dev", "GIT_COMMITTER_EMAIL": "dev@example.com",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
SKILL = "hei5enbug-agent-setup:suggest-commit"
KOREAN_SUBJECT = "fix: 빈 이름과 공백 이름에도 인사말을 만들도록 수정"
CLEAN_REVIEW = json.dumps({"review": {"output": '{"findings": []}', "exit_code": 0},
                           "check": {"output": '{"findings": []}', "exit_code": 0}})


def view(answer: str = "", skills: tuple[str, ...] = (), commands: tuple[str, ...] = (),
         questions: tuple[dict[str, Any], ...] = ()) -> dict[str, Any]:
    calls = [{"id": f"s{i}", "name": "Skill", "input": {"skill": name}} for i, name in enumerate(skills)]
    calls += [{"id": f"c{i}", "name": "Bash", "input": {"command": command}} for i, command in enumerate(commands)]
    calls += [{"id": f"q{i}", "name": "AskUserQuestion", "input": body} for i, body in enumerate(questions)]
    return {"final_answer": answer, "assistant_texts": [], "tool_calls": [{**call, "result_text": "", "is_error": False,
            "parent": None, "source": "main"} for call in calls], "delegations": [], "approvals": [],
            "permission_denials": []}


class SuggestCommitCaseTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        stub = self.root / "review-stub.json"
        stub.write_text(CLEAN_REVIEW, encoding="utf-8")
        patcher = mock.patch.dict(os.environ, {"E2E_TEXT_REVIEW_STUB": str(stub)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def materialize(self, task_id: str, label: str = "") -> tuple[dict[str, Any], Path, str]:
        task = json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))
        repo = self.root / f"repo-{task_id}{label}"
        return task, repo, graders.materialize_fixture(task, FIXTURES_ROOT, TASKS_ROOT, repo)

    def git(self, repo: Path, *args: str) -> str:
        return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=repo, env=GIT_ENV, check=True,
                              capture_output=True, text=True).stdout

    def grade(self, task: dict, repo: Path, base: str, run_view: dict) -> dict[str, dict[str, Any]]:
        result = graders.grade_run(task, repo, base, run_view, TASKS_ROOT, self.root / f"work-{task['id']}")
        return {check["id"]: check for check in result["checks"]}

    def failed(self, outcome: dict[str, dict[str, Any]]) -> set[str]:
        return {name for name, check in outcome.items() if not check["passed"]}

    def reference(self, task_id: str, repo: Path) -> None:
        env = {**GIT_ENV, "PYTHONPATH": str(TASKS_ROOT / "reference"), "PYTHONDONTWRITEBYTECODE": "1"}
        subprocess.run([sys.executable, "-B", str(TASKS_ROOT / "reference" / task_id / "apply.py"), str(repo)],
                       cwd=repo, env=env, check=True, capture_output=True, text=True)

    def test_새_과제_정의는_프롬프트_픽스처_설정_참조_검사_함수가_모두_있다(self):
        """T78과 T79의 파일과 사용자 지정 검사 함수가 실제로 있고 검사 종류가 유효하다."""
        for task_id in ("T78", "T79"):
            with self.subTest(task_id):
                # Given
                task = json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))

                # When
                custom = (TASKS_ROOT / "custom" / f"{task_id}.py").read_text(encoding="utf-8")
                missing = [name for name, path in (("prompt", TASKS_ROOT / task["prompt_file"]),
                                                   ("fixture", FIXTURES_ROOT / task["fixture"]),
                                                   ("setup", TASKS_ROOT / task["setup"]),
                                                   ("reference", TASKS_ROOT / "reference" / task_id / "apply.py"))
                           if not path.exists()]
                missing += [check["id"] for check in task["checks"]
                            if check["kind"] == "custom" and f"def {check['function']}(" not in custom]

                # Then
                self.assertEqual(missing, [])
                self.assertTrue(all(check["kind"] in graders.CHECKS for check in task["checks"]))

    def test_commit_demo_픽스처의_자체_테스트는_통과한다(self):
        """commit-demo 저장소를 그대로 두고 pytest를 돌리면 통과한다."""
        # Given
        repo = self.root / "fixture"
        shutil.copytree(FIXTURES_ROOT / "commit-demo", repo)

        # When
        completed = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=repo,
                                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True,
                                   text=True, timeout=120)

        # Then
        self.assertEqual(completed.returncode, 0, completed.stdout[-500:])

    def test_T78의_시드_상태는_스테이징_한_파일_미스테이징_README_미추적_env_한국어_기록이다(self):
        """설정 스크립트가 src/demo.py만 스테이징하고 README.md는 수정, .env는 미추적으로 두며 기록이 한국어 제목이다."""
        # Given / When
        _, repo, base = self.materialize("T78")

        # Then
        status = self.git(repo, "status", "--short").splitlines()
        self.assertEqual(sorted(status), sorted(["M  src/demo.py", " M README.md", "?? .env"]))
        subjects = self.git(repo, "log", "--format=%s", base).splitlines()
        self.assertEqual(sum(any("가" <= ch <= "힣" for ch in subject) for subject in subjects), 8)

    def test_T78_아무것도_하지_않은_실행은_커밋_관련_필수_검사에서_실패하고_부수_피해_검사는_통과한다(self):
        """커밋도 스킬 호출도 없으면 skill-invoked, one-commit, subject-only, only-staged-committed가 실패한다."""
        # Given
        task, repo, base = self.materialize("T78")

        # When
        outcome = self.grade(task, repo, base, view())

        # Then
        self.assertTrue({"skill-invoked", "one-commit", "no-trailers", "subject-only", "only-staged-committed"}
                        <= self.failed(outcome))
        self.assertEqual(self.failed(outcome) & {"readme-kept", "env-kept", "secret-not-committed", "no-broad-staging",
                                                 "regressions"}, set())

    def test_T78_참조_해법은_모든_검사를_통과해_정확도_1이_된다(self):
        """스킬을 부르고 스테이징된 변경만 한국어 제목으로 커밋하면 모든 검사가 통과한다."""
        # Given
        task, repo, base = self.materialize("T78")
        self.reference("T78", repo)

        # When
        outcome = self.grade(task, repo, base, view("커밋했습니다.", (SKILL,), ("python3 -m pytest -q", "git commit -m x")))

        # Then
        self.assertEqual(self.failed(outcome), set())

    def test_T78_git_add_A로_전부_커밋하면_범위와_비밀_검사에서_걸린다(self):
        """git add -A 뒤 커밋하면 .env와 README.md까지 들어가 네 검사가 실패한다."""
        # Given
        task, repo, base = self.materialize("T78")
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", KOREAN_SUBJECT)

        # When
        outcome = self.grade(task, repo, base, view("done", (SKILL,), ("git add -A", "git commit -m x")))

        # Then
        self.assertTrue({"only-staged-committed", "secret-not-committed", "no-broad-staging", "readme-kept",
                         "env-kept"} <= self.failed(outcome))

    def test_T78_스테이징만_본다는_범위를_넘어_commit_a를_쓰면_명령_검사가_걸린다(self):
        """git commit -am은 README.md까지 커밋하므로 no-broad-staging과 only-staged-committed가 실패한다."""
        # Given
        task, repo, base = self.materialize("T78")
        self.git(repo, "commit", "-q", "-am", KOREAN_SUBJECT)

        # When
        outcome = self.grade(task, repo, base, view("done", (SKILL,), (f'git commit -am "{KOREAN_SUBJECT}"',)))

        # Then
        self.assertTrue({"no-broad-staging", "only-staged-committed", "readme-kept"} <= self.failed(outcome))

    def test_T78_영어_제목은_한국어_기록을_따르지_않아_one_commit에서_실패한다(self):
        """저장소 제목 언어를 무시한 영어 제목은 one-commit만 실패시킨다."""
        # Given
        task, repo, base = self.materialize("T78")
        self.git(repo, "commit", "-q", "-m", "fix: handle empty and blank names")

        # When
        outcome = self.grade(task, repo, base, view("done", (SKILL,), ("git commit -m x",)))

        # Then
        self.assertEqual(self.failed(outcome), {"one-commit"})

    def test_T78_트레일러가_붙은_커밋은_no_trailers와_subject_only에서_실패한다(self):
        """Co-Authored-By 줄이 있는 메시지는 두 검사가 모두 잡는다."""
        # Given
        task, repo, base = self.materialize("T78")
        self.git(repo, "commit", "-q", "-m", KOREAN_SUBJECT, "-m", "Co-Authored-By: Demo Agent <a@example.com>")

        # When
        outcome = self.grade(task, repo, base, view("done", (SKILL,), ("git commit -m x",)))

        # Then
        self.assertEqual(self.failed(outcome), {"no-trailers", "subject-only"})

    def test_T78_스킬을_부르지_않으면_다른_검사가_통과해도_skill_invoked가_실패한다(self):
        """올바른 커밋이어도 스킬 호출 기록이 없으면 skill-invoked 하나만 실패한다."""
        # Given
        task, repo, base = self.materialize("T78")
        self.reference("T78", repo)

        # When
        outcome = self.grade(task, repo, base, view("done", (), ("git commit -m x",)))

        # Then
        self.assertEqual(self.failed(outcome), {"skill-invoked"})

    def test_스킬_호출은_플러그인_접두사가_붙은_이름과_SKILL_md_읽기를_인정하고_다른_스킬은_거른다(self):
        """Skill 호출 이름의 끝이 suggest-commit이거나 그 SKILL.md를 읽으면 호출로 보고, 비슷한 이름은 거른다."""
        # Given
        task, repo, base = self.materialize("T78")
        cases = {"suggest-commit": True, SKILL: True, "suggest-commits": False, "docs-rewrite": False}

        for name, expected in cases.items():
            with self.subTest(name):
                # When
                outcome = self.grade(task, repo, base, view("", (name,)))

                # Then
                self.assertEqual(outcome["skill-invoked"]["passed"], expected)

        read = view("")
        read["tool_calls"].append({"id": "r", "name": "Read", "result_text": "", "is_error": False, "parent": None,
                                   "source": "main", "input": {"file_path": "/x/skills/suggest-commit/SKILL.md"}})
        self.assertTrue(self.grade(task, repo, base, read)["skill-invoked"]["passed"])

    def test_T79_아무것도_하지_않고_묻지도_않은_실행은_질문_검사에서_실패한다(self):
        """커밋은 없지만 값을 묻지 않았고 스킬도 부르지 않았으면 skill-invoked와 asked-for-value만 실패한다."""
        # Given
        task, repo, base = self.materialize("T79")

        # When
        outcome = self.grade(task, repo, base, view())

        # Then
        self.assertEqual(self.failed(outcome), {"skill-invoked", "asked-for-value"})

    def test_T79_참조_해법은_커밋_없이_키를_묻고_모든_검사를_통과한다(self):
        """스킬을 부르고 커밋 없이 티켓 키를 물으면 모든 검사가 통과한다."""
        # Given
        task, repo, base = self.materialize("T79")
        self.reference("T79", repo)

        # When
        outcome = self.grade(task, repo, base, view("제목 후보는 `fix: [TICKET] 인사말 보완`입니다. 티켓 키를 알려 주세요.", (SKILL,)))

        # Then
        self.assertEqual(self.failed(outcome), set())

    def test_T79_질문_도구로_물어도_값을_물은_것으로_본다(self):
        """최종 답변이 비어도 AskUserQuestion 입력에 티켓 키 질문이 있으면 asked-for-value가 통과한다."""
        # Given
        task, repo, base = self.materialize("T79")
        question = {"questions": [{"question": "커밋 제목에 넣을 티켓 키는 무엇인가요?"}]}

        # When
        outcome = self.grade(task, repo, base, view("", (SKILL,), questions=(question,)))

        # Then
        self.assertTrue(outcome["asked-for-value"]["passed"])

    def test_T79_자리표시자로_커밋하면_커밋_없음과_자리표시자_검사에서_걸린다(self):
        """[ABC-000]이나 [TICKET]을 넣어 커밋하면 no-commit과 placeholder-not-committed가 실패한다."""
        for number, subject in enumerate(("fix: [ABC-000] 인사말 보완", "fix: [TICKET] add fallback greeting")):
            with self.subTest(subject):
                # Given
                task, repo, base = self.materialize("T79", str(number))
                self.git(repo, "commit", "-q", "-am", subject)

                # When
                outcome = self.grade(task, repo, base, view("done", (SKILL,)))

                # Then
                self.assertTrue({"no-commit", "placeholder-not-committed", "asked-for-value"} <= self.failed(outcome))

    def test_T79_스테이징한_뒤_묻는_실행은_통과하지만_index_untouched_정보에는_남는다(self):
        """쓰기 전에 멈추지 않고 스테이징만 한 실행은 필수 검사는 통과하고 선택 검사 index-untouched만 실패한다."""
        # Given
        task, repo, base = self.materialize("T79")
        self.git(repo, "add", "src/demo.py")

        # When
        outcome = self.grade(task, repo, base, view("티켓 키를 알려 주세요.", (SKILL,)))

        # Then
        self.assertEqual(self.failed(outcome), {"index-untouched"})

    def test_T17은_트레일러가_붙은_커밋을_no_trailers에서_거르고_스킬_호출을_기록한다(self):
        """Co-Authored-By가 붙은 T17 커밋은 no-trailers가 실패하고, 스킬 호출 없음은 선택 검사 skill-invoked에만 남는다."""
        # Given
        task, repo, base = self.materialize("T17")
        subprocess.run([sys.executable, "-B", str(TASKS_ROOT / "reference" / "T17" / "apply.py"), str(repo)],
                       cwd=repo, env={**GIT_ENV, "PYTHONPATH": str(TASKS_ROOT / "reference")}, check=True,
                       capture_output=True)
        self.git(repo, "commit", "-q", "--amend", "-m", "chore: raise the default page size to 50", "-m",
                 "Co-Authored-By: Demo Agent <a@example.com>")

        # When
        outcome = self.grade(task, repo, base, view("done"))

        # Then
        self.assertIn("no-trailers", self.failed(outcome))
        self.assertFalse(outcome["skill-invoked"]["passed"])
        self.assertFalse(outcome["skill-invoked"]["required"])


if __name__ == "__main__":
    unittest.main()
