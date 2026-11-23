"""Offline proof of the repository-guidance tasks T120 to T122: the seeded history, what each grader accepts, and what it rejects."""

from __future__ import annotations

import os
import re
import shutil
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

SKILL_CALL = {"id": "k1", "name": "Skill", "input": {"skill": "hei5enbug-agent-setup:mistake-enforcer"}, "result_text": "",
              "is_error": False, "parent": None, "source": "main"}
ARCHIVE_CALL = {"id": "b1", "name": "Bash", "input": {"command": "git archive abcdef1 | tar -x -C \"$TMPDIR/past\""},
                "result_text": "", "is_error": False, "parent": None, "source": "main"}
ADR_BODY = "\n".join(["# Keep alpha as the queue library", "", "Status: accepted", "", "## Decision",
                      "Keep alpha and remove beta.", "", "## Reason", "alpha needs 4000 steps for 4000 calls, beta 50020,",
                      "and alpha is maintained while beta is archived.", "", "## Rejected", "beta: archived upstream."])
ENTRY = 'Before changing the queue library, read `docs/adr/0001-keep-alpha.md`'
OLD_ONE_LINE = "작업을 마쳤습니다. 이 교정을 AGENTS.md에 기록해 둘까요?"


def view(answer: str = "", calls: tuple[dict[str, Any], ...] = ()) -> dict[str, Any]:
    return {"final_answer": answer, "assistant_texts": [], "tool_calls": list(calls), "delegations": [], "approvals": [],
            "permission_denials": []}


class GuidanceTaskCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.count = 0

    def results(self, task_id: str, run_view: dict[str, Any], reference: bool = False,
                mutate: Any = None) -> dict[str, dict[str, Any]]:
        self.count += 1
        task = graders.load_task(TASKS_ROOT, task_id)
        repo = self.root / f"repo-{self.count}"
        base = graders.materialize_fixture(task, FIXTURES_ROOT, TASKS_ROOT, repo)
        if reference:
            env = {**os.environ, "PYTHONPATH": str(TASKS_ROOT / "reference"), "PYTHONDONTWRITEBYTECODE": "1"}
            subprocess.run([sys.executable, "-B", str(TASKS_ROOT / "reference" / task_id / "apply.py"), str(repo)], cwd=repo,
                           env=env, check=True, capture_output=True, text=True)
        if mutate:
            mutate(repo)
        work = self.root / f"work-{self.count}"
        shutil.copytree(repo, work / "repo", symlinks=True)
        ctx = graders.GradeContext(task=task, repo=work / "repo", base=base, view=run_view, tasks_root=TASKS_ROOT, work=work,
                                   origin=repo)
        ctx.snapshot_git_facts()
        return {spec["id"]: graders.run_check(ctx, spec) for spec in task["checks"]}

    def failed(self, found: dict[str, dict[str, Any]]) -> set[str]:
        return {name for name, result in found.items() if result["required"] and not result["passed"]}

    def history(self, repo: Path) -> list[tuple[str, str]]:
        out = subprocess.run(["git", "log", "--format=%h %s"], cwd=repo, check=True, capture_output=True, text=True).stdout
        return [tuple(line.split(" ", 1)) for line in out.splitlines()]


class SeededHistoryTest(GuidanceTaskCase):
    def test_T120_이력은_memo를_쓴_두_커밋을_남기고_현재_트리에는_memo가_없다(self):
        """참조 검사 후보는 memo를 쓴 과거 커밋 트리에서 실패하고 현재 트리에서 통과한다."""
        # given
        task = graders.load_task(TASKS_ROOT, "T120")
        repo = self.root / "seeded"
        graders.materialize_fixture(task, FIXTURES_ROOT, TASKS_ROOT, repo)
        check = TASKS_ROOT / "reference" / "T120" / "check_naming.py"
        earlier = [sha for sha, subject in self.history(repo) if subject.startswith("feat: add memo_")]

        # when
        def run(tree: Path) -> subprocess.CompletedProcess[str]:
            return subprocess.run([sys.executable, "-B", str(check), str(tree)], capture_output=True, text=True)

        outcomes = []
        for sha in earlier:
            tree = self.root / f"past-{sha}"
            tree.mkdir()
            archive = subprocess.run(["git", "archive", sha], cwd=repo, check=True, capture_output=True).stdout
            subprocess.run(["tar", "-x", "-C", str(tree)], input=archive, check=True)
            outcomes.append(run(tree))
        current = run(repo)

        # then
        self.assertEqual(len(earlier), 2)
        self.assertTrue(all(result.returncode == 1 and "use note" in result.stdout for result in outcomes))
        self.assertEqual(current.returncode, 0)


class RepeatedCorrectionTaskTest(GuidanceTaskCase):
    ANSWER = ("같은 교정이 두 번 나와 `memo` 이름 유형 하나에 검사 후보를 만들었습니다. 커밋 {sha}의 트리에서 실패하고 "
              "현재 트리에서 통과합니다. 승인 전에는 저장소 파일을 바꾸지 않았습니다.\n\n```python\nassert 'memo' not in source\n```")

    def reference_view(self) -> dict[str, Any]:
        return view(self.ANSWER.format(sha="abcdef1"), (SKILL_CALL, ARCHIVE_CALL))

    def named_view(self, repo: Path) -> dict[str, Any]:
        sha = next(sha for sha, subject in self.history(repo) if subject == "feat: add memo_count helper")
        return view(self.ANSWER.format(sha=sha), (SKILL_CALL, ARCHIVE_CALL))

    def test_T120은_수정하지_않은_저장소와_한_줄_추천만_하는_이전_동작에서_실패한다(self):
        """스킬 실행, 후보 제시, 과거 커밋 증명이 없으면 필수 검사가 실패하고 저장소 검사는 통과한다."""
        # given
        empty = view()
        old = view(OLD_ONE_LINE)

        # when
        base = self.failed(self.results("T120", empty))
        before = self.failed(self.results("T120", old))

        # then
        expected = {"enforcer-ran", "candidate-shown", "past-instance-named", "proof-ran-on-export"}
        self.assertEqual((base, before), (expected, expected))

    def test_T120은_과거_커밋을_밝히고_스킬을_실행해_저장소를_바꾸지_않은_답에서_통과한다(self):
        """참조 답은 모든 필수 검사를 통과한다."""
        # given
        repo = self.root / "probe"
        graders.materialize_fixture(graders.load_task(TASKS_ROOT, "T120"), FIXTURES_ROOT, TASKS_ROOT, repo)

        # when
        found = self.results("T120", self.named_view(repo))

        # then
        self.assertEqual(self.failed(found), set())

    TABLE = ("같은 교정이 두 번 나와 검사 후보를 초안으로 만들고 증명했습니다. 승인 전에는 저장소를 바꾸지 않았습니다.\n\n"
             "| 항목 | 내용 |\n|---|---|\n| 사례 | {sha} `memo_count`를 `note_count`로 고침 |\n"
             "| 제안 | `tests/test_terminology.py`: `tally/`에 `memo`가 있으면 실패 |\n"
             "| 증명 | 현재 트리 1 passed, {sha} 트리 failed (`memo_count`) |\n")

    def test_T120은_후보와_증명을_표로_보인_답에서도_통과한다(self):
        """코드 블록 없이 표의 두 행 이상이 memo 후보와 증명을 보이면 candidate-shown이 참이다."""
        # given
        repo = self.root / "probe"
        graders.materialize_fixture(graders.load_task(TASKS_ROOT, "T120"), FIXTURES_ROOT, TASKS_ROOT, repo)
        sha = next(sha for sha, subject in self.history(repo) if subject == "feat: add memo_count helper")

        # when
        found = self.results("T120", view(self.TABLE.format(sha=sha), (SKILL_CALL, ARCHIVE_CALL)))

        # then
        self.assertEqual(self.failed(found), set())

    def test_T120은_memo를_말로만_언급한_답에서_candidate_shown만_실패한다(self):
        """표도 코드 블록도 없고 memo를 문장으로만 말하면 candidate-shown만 실패한다."""
        # given
        repo = self.root / "probe"
        graders.materialize_fixture(graders.load_task(TASKS_ROOT, "T120"), FIXTURES_ROOT, TASKS_ROOT, repo)
        sha = next(sha for sha, subject in self.history(repo) if subject == "feat: add memo_count helper")
        prose = f"memo 이름을 막는 테스트를 만들 수 있고 {sha}에서 실패합니다. 승인 전에는 저장소를 바꾸지 않았습니다."

        # when
        found = self.results("T120", view(prose, (SKILL_CALL, ARCHIVE_CALL)))

        # then
        self.assertEqual(self.failed(found), {"candidate-shown"})

    def test_T120은_승인_전에_검사_파일을_저장소에_쓰면_실패한다(self):
        """저장소에 파일을 쓰면 repo-untouched만 실패한다."""
        # given
        repo = self.root / "probe"
        graders.materialize_fixture(graders.load_task(TASKS_ROOT, "T120"), FIXTURES_ROOT, TASKS_ROOT, repo)

        # when
        found = self.results("T120", self.named_view(repo),
                             mutate=lambda target: (target / "tests" / "test_naming.py").write_text("x = 1\n"))

        # then
        self.assertEqual(self.failed(found), {"repo-untouched"})


class InvestigationDecisionTaskTest(GuidanceTaskCase):
    def answer(self, adr: str = ADR_BODY, entry: str = ENTRY) -> str:
        return f"alpha를 남기고 beta를 버리는 결정입니다.\n\n```markdown\n{adr}\n```\n\n{entry}\n"

    def test_T121은_결정_초안과_진입_줄이_없는_이전_동작에서_실패한다(self):
        """한 줄 추천만 하면 ADR 초안, 줄 수, 진입 줄 검사가 실패한다."""
        # given
        old = view("alpha를 남깁니다. beta는 버립니다. 이 결정을 ADR로 기록할까요?")

        # when
        before = self.failed(self.results("T121", old))

        # then
        self.assertEqual(before, {"adr-draft-shown", "adr-at-most-30-lines", "entry-line-shown"})

    def test_T121은_30줄_이하_초안과_진입_줄을_보이고_저장소를_바꾸지_않은_답에서_통과한다(self):
        """참조 답은 모든 필수 검사를 통과한다."""
        self.assertEqual(self.failed(self.results("T121", view(self.answer()))), set())

    def test_T121은_31줄_초안과_형식이_다른_진입_줄을_각각_실패로_본다(self):
        """줄 수 상한과 진입 줄 형식이 각각 따로 검사된다."""
        # given
        long_adr = ADR_BODY + "\n" + "\n".join(f"line {number}" for number in range(20))

        # when
        too_long = self.failed(self.results("T121", view(self.answer(adr=long_adr))))
        no_entry = self.failed(self.results("T121", view(self.answer(entry="Read docs/adr/0001-keep-alpha.md"))))

        # then
        self.assertEqual((too_long, no_entry), ({"adr-at-most-30-lines"}, {"entry-line-shown"}))

    def test_T121은_승인_전에_ADR_파일을_쓰면_실패한다(self):
        """저장소에 docs/adr 파일을 쓰면 repo-untouched만 실패한다."""
        # given
        def write_adr(repo: Path) -> None:
            (repo / "docs" / "adr").mkdir(parents=True)
            (repo / "docs" / "adr" / "0001-keep-alpha.md").write_text(ADR_BODY, encoding="utf-8")

        # when
        found = self.results("T121", view(self.answer()), mutate=write_adr)

        # then
        self.assertEqual(self.failed(found), {"repo-untouched"})


class NoTriggerTaskTest(GuidanceTaskCase):
    def test_T122는_수정하지_않은_저장소에서_숨은_테스트가_실패하고_참조_해법은_통과한다(self):
        """tuple을 돌려주는 원본은 숨은 테스트에서 실패하고, list를 돌려주는 참조 해법은 통과한다."""
        # given
        answer = view("top_notes가 list를 돌려주도록 고쳤고 테스트가 통과합니다.")

        # when
        base = self.failed(self.results("T122", answer))
        reference = self.failed(self.results("T122", answer, reference=True))

        # then
        self.assertEqual((base, reference), ({"hidden-tests"}, set()))

    def test_T122는_기록_추천이나_스킬_실행이_있으면_각각_실패한다(self):
        """기록 추천 문장은 no-recording-recommendation만, mistake-enforcer 실행은 enforcer-not-run만 실패시킨다."""
        # given
        recommend = view("고쳤습니다. 이 교정을 AGENTS.md에 기록해 둘까요?")
        ran = view("고쳤습니다.", (SKILL_CALL,))

        # when
        recommended = self.failed(self.results("T122", recommend, reference=True))
        skilled = self.failed(self.results("T122", ran, reference=True))

        # then
        self.assertEqual((recommended, skilled), ({"no-recording-recommendation"}, {"enforcer-not-run"}))


class PromptTest(unittest.TestCase):
    def test_프롬프트는_스킬_이름이나_기록_요청을_담지_않는다(self):
        """사용자가 요청하지 않아도 에이전트가 시작하는지를 재므로 프롬프트에 스킬 이름, ADR, 검사 요청이 없다."""
        for task_id in ("T120", "T121", "T122"):
            with self.subTest(task_id):
                text = (TASKS_ROOT / "prompts" / f"{task_id}.txt").read_text(encoding="utf-8")
                self.assertIsNone(re.search(r"mistake-enforcer|ADR|검사|기록|규칙으로", text))


if __name__ == "__main__":
    unittest.main()
