"""Tests for the requirements agreement tasks T46 to T52: their files, their fixture, their reference solutions, and one
recorded conversation that passes and one that fails for each case."""

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

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
TASKS_ROOT = E2E_ROOT / "tasks"
FIXTURES_ROOT = E2E_ROOT / "fixtures"
sys.path.insert(0, str(E2E_ROOT))

from harness import converse, graders  # noqa: E402
from harness.scripted_user import ScriptedUser, load_sheet, sheet_leaks  # noqa: E402

TASK_IDS = ["T46", "T47", "T48", "T49", "T50", "T51", "T52"]
CASES = dict(zip("ABCDEFG", TASK_IDS))


def load_task(task_id: str) -> dict[str, Any]:
    return json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))


def apply_reference(task_id: str, repo: Path) -> None:
    script = TASKS_ROOT / "reference" / task_id / "apply.py"
    env = {**os.environ, "PYTHONPATH": str(TASKS_ROOT / "reference"), "PYTHONDONTWRITEBYTECODE": "1"}
    subprocess.run([sys.executable, "-B", str(script), str(repo)], cwd=repo, env=env, check=True, capture_output=True, text=True)


def text(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value}


def call(name: str, **tool_input: Any) -> dict[str, Any]:
    return {"type": "call", "id": f"c-{name}", "name": name, "input": tool_input}


def exchange(index: int, question: str, matched: list[str] | None = None, **fields: Any) -> dict[str, Any]:
    return {"type": "exchange", "index": index, "kind": fields.pop("kind", "tool"), "question": question, "matched": matched or [],
            "answer": fields.pop("answer", "x"), "approval": fields.pop("approval", None), "ended": fields.pop("ended", False), **fields}


def make_view(items: list[dict[str, Any]], final: str = "done") -> dict[str, Any]:
    exchanges = [{key: value for key, value in item.items() if key != "type"} for item in items if item["type"] == "exchange"]
    calls = [{"id": item["id"], "name": item["name"], "input": item["input"], "result_text": "", "is_error": False, "parent": None,
              "source": "main"} for item in items if item["type"] == "call"]
    return {"final_answer": final, "assistant_texts": [item["text"] for item in items if item["type"] == "text"], "tool_calls": calls,
            "delegations": [], "approvals": [], "permission_denials": [], "conversation": {"exchanges": exchanges, "timeline": items}}


EDIT = call("Edit", file_path="timesheet/cli.py")
READ = call("Read", file_path="README.md")

CONVERSATIONS: dict[str, tuple[list[dict[str, Any]], str, list[dict[str, Any]], str, str]] = {
    # task id: (passing timeline, passing report, failing timeline, check that must fail, what the failure is)
    "T46": (
        [READ, exchange(1, "Which first day of the week?", ["week-start"]), exchange(2, "Which file name?", ["export-name"]),
         exchange(3, "Do you approve this specification?", approval=True), EDIT],
        "done",
        [READ, exchange(1, "Which first day of the week?", ["week-start"]), EDIT, exchange(2, "Which file name?", ["export-name"]),
         exchange(3, "Do you approve this specification?", approval=True)],
        "no-edit-before-approval", "a file edit before the approval"),
    "T47": ([READ, EDIT], "done", [READ, exchange(1, "Which week start do you want?"), EDIT], "no-agreement-no-question", "a question"),
    "T48": (
        [READ, exchange(1, "totals could reuse load_cached, which already keeps the file for an hour; reuse it?", ["cache-choice"]), EDIT],
        "done",
        [READ, exchange(1, "totals could reuse load_cached; reuse it?", ["cache-choice"]),
         exchange(2, "Do you approve this specification?", approval=True), EDIT],
        "no-specification-approval", "a specification approval"),
    "T49": (
        [READ, exchange(1, "Do you approve this specification?", approval=True),
         exchange(2, "What should I do next: plan the work, or implement it?", answer=None, ended=True)],
        "done",
        [READ, exchange(1, "Do you approve this specification?", approval=True), EDIT,
         exchange(2, "What should I do next: plan the work, or implement it?", answer=None, ended=True)],
        "no-file-edit", "a file edit"),
    "T50": (
        [READ, exchange(1, "Removing the lock lets two adds at the same time lose an entry. Remove it anyway?", ["parallel-adds"]),
         exchange(2, "Two parallel adds can still lose an entry. Do you accept that?", ["parallel-adds"]), EDIT],
        "The lock is gone; two adds at the same time can now lose an entry.",
        [READ, exchange(1, "Removing the lock lets two adds at the same time lose an entry. Remove it anyway?", ["parallel-adds"]), EDIT,
         exchange(2, "Two parallel adds can still lose an entry. Do you accept that?", ["parallel-adds"])],
        "no-edit-between-answers", "a file edit between the first answer and the second question"),
    "T51": (
        [READ, exchange(1, "Is the store sorted by date?", ["sorted-claim"]),
         text("store.add only appends, so the file is not sorted; the sample data is out of order."),
         exchange(2, "The store does not sort. Remove the sort anyway?", ["sorted-claim"]), EDIT],
        "Removed the sort. You said the nightly import sorts the file before it is read.",
        [READ, exchange(1, "Is the store sorted by date?", ["sorted-claim"]),
         text("store.add only appends, so the file is not sorted."), exchange(2, "Remove it anyway?", ["sorted-claim"]), EDIT],
        "report-holds-constraint", "a final report without the constraint"),
    "T52": (
        [READ, text("I read --since as a YYYY-MM-DD date, as the other options of this tool do."), EDIT], "done",
        [READ, exchange(1, "Which date format should --since use?"), text("Reading --since as YYYY-MM-DD."), EDIT],
        "no-question", "a question"),
}
BAD_REPORT = {"T51": "Removed the sort."}
EXPECTED_FAILURES = {
    "T46": {"hidden-tests", "specification-approved", "no-edit-before-approval"},
    "T47": {"hidden-tests"},
    "T48": {"hidden-tests", "one-question-names-mechanism"},
    "T49": {"specification-approved", "stops-and-asks-next"},
    "T50": {"hidden-tests", "question-before-edit", "no-edit-between-answers", "report-names-behavior"},
    "T51": {"hidden-tests", "no-edit-between-answers", "message-shows-check", "report-holds-constraint"},
    "T52": {"hidden-tests", "reading-stated-before-edit"},
}
EXPECTED_PASSES = {
    "T46": {"regressions"}, "T47": {"regressions", "no-agreement-no-question"}, "T48": {"regressions", "single-cache-class", "no-specification-approval"},
    "T49": {"no-file-edit", "repo-unchanged"}, "T50": {"regressions"}, "T51": {"regressions"}, "T52": {"regressions", "no-question"},
}


class AgreementTaskTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)

    def materialize(self, task_id: str) -> tuple[dict[str, Any], Path, str]:
        task = load_task(task_id)
        repo = self.root / f"repo-{task_id}"
        return task, repo, graders.materialize_fixture(task, FIXTURES_ROOT, TASKS_ROOT, repo)

    def grade(self, task: dict[str, Any], repo: Path, base: str, view: dict[str, Any]) -> dict[str, Any]:
        return graders.grade_run(task, repo, base, view, TASKS_ROOT, self.root / f"work-{task['id']}")

    def failed(self, result: dict[str, Any]) -> set[str]:
        return {check["id"] for check in result["checks"] if not check["passed"]}

    def test_일곱_과제는_프롬프트_시트_픽스처_숨은_테스트_참조_해법과_사용자_지정_검사를_갖춘다(self):
        """T46부터 T52까지 모든 파일이 있고 시트가 유효하며 검사 종류와 사용자 지정 함수가 실제로 있다."""
        for task_id in TASK_IDS:
            with self.subTest(task_id):
                # given
                task = load_task(task_id)

                # when
                missing = [name for name, ok in {
                    "prompt": (TASKS_ROOT / task["prompt_file"]).is_file(), "fixture": (FIXTURES_ROOT / task["fixture"]).is_dir(),
                    "sheet": (TASKS_ROOT / task["sheet"]).is_file(), "reference": (TASKS_ROOT / "reference" / task_id / "apply.py").is_file(),
                    "hidden": "hidden_tests" not in task or (TASKS_ROOT / task["hidden_tests"]["source"]).is_dir(),
                }.items() if not ok]
                unknown = [check["kind"] for check in task["checks"] if check["kind"] not in graders.CHECKS]
                source = (TASKS_ROOT / "custom" / f"{task_id}.py").read_text(encoding="utf-8")
                absent = [check["id"] for check in task["checks"] if check["kind"] == "custom"
                          and f"def {check['function']}(" not in source and f"def {check['function']}(" not in (
                              TASKS_ROOT / "custom" / "agreement_shared.py").read_text(encoding="utf-8")]
                load_sheet(TASKS_ROOT / task["sheet"])

                # then
                self.assertEqual((missing, unknown, absent), ([], [], []))

    def test_시트는_에이전트가_받는_저장소에_복사되지_않는다(self):
        """과제별로 만든 실행 저장소와 그 상위 작업 폴더에는 시트의 이름도 내용도 없다."""
        for task_id in TASK_IDS:
            with self.subTest(task_id):
                # given
                task, repo, _ = self.materialize(task_id)

                # when
                leaks = sheet_leaks(repo.parent, TASKS_ROOT / task["sheet"])

                # then
                self.assertEqual(leaks, [])

    def test_수정하지_않은_저장소는_사례가_요구하는_필수_검사에서_실패한다(self):
        """아무 대화도 없는 빈 실행은 success가 False이고 기대한 필수 검사만 실패하며 나머지는 통과한다."""
        for task_id in TASK_IDS:
            with self.subTest(task_id):
                # given
                task, repo, base = self.materialize(task_id)

                # when
                result = self.grade(task, repo, base, make_view([]))

                # then
                required = {check["id"] for check in task["checks"] if check["required"]}
                failed = self.failed(result)
                self.assertFalse(result["success"])
                self.assertEqual(failed & required, EXPECTED_FAILURES[task_id], (task_id, failed))
                self.assertTrue(EXPECTED_PASSES[task_id] <= {check["id"] for check in result["checks"] if check["passed"]})

    def test_참조_해법과_통과하는_대화_기록은_모든_검사를_통과해_정확도_1이_된다(self):
        """사례마다 참조 해법과 통과 기록을 채점하면 성공이고 정확도 1.0이다."""
        for task_id in TASK_IDS:
            with self.subTest(task_id):
                # given
                task, repo, base = self.materialize(task_id)
                apply_reference(task_id, repo)
                passing, report = CONVERSATIONS[task_id][0], CONVERSATIONS[task_id][1]

                # when
                result = self.grade(task, repo, base, make_view(passing, report))

                # then
                self.assertEqual([(c["id"], c["detail"]) for c in result["checks"] if not c["passed"]], [])
                self.assertEqual(result["correctness"], 1.0)

    def test_실패하는_대화_기록은_그_사례의_검사_하나만_실패시킨다(self):
        """A는 승인 전 편집, B는 질문, C는 명세 승인, D는 파일 편집, E는 두 답 사이 편집, F는 제약 없는 보고, G는 질문이 각각 그 검사만 실패시킨다."""
        for case, task_id in CASES.items():
            with self.subTest(case=case, task_id=task_id):
                # given
                task, repo, base = self.materialize(task_id)
                apply_reference(task_id, repo)
                _, _, failing, expected, _ = CONVERSATIONS[task_id]

                # when
                result = self.grade(task, repo, base, make_view(failing, BAD_REPORT.get(task_id, CONVERSATIONS[task_id][1])))

                # then
                self.assertEqual(self.failed(result), {expected}, (case, [(c["id"], c["detail"]) for c in result["checks"] if not c["passed"]]))

    def test_교환이_없어도_질문_도구_호출이_있으면_무질문_검사가_질문으로_센다(self):
        """로그가 있는 실행에서 AskUserQuestion 호출만 있고 교환이 없으면 B와 G의 무질문 검사는 도구 호출로 질문을 잡아낸다."""
        for task_id in ("T47", "T52"):
            with self.subTest(task_id):
                # given
                task, repo, base = self.materialize(task_id)
                apply_reference(task_id, repo)
                view = make_view([READ, EDIT])
                view["tool_calls"].append({"id": "q", "name": "AskUserQuestion", "input": {}, "result_text": "", "is_error": False,
                                           "parent": None, "source": "main"})

                # when
                result = self.grade(task, repo, base, view)

                # then
                self.assertTrue({"no-agreement-no-question", "no-question"} & self.failed(result))

    def test_시트의_점은_참조_해법이_만들_명세로_승인되고_기각한_용어는_제목_밖에서_막는다(self):
        """T46 시트는 일요일과 날짜 형식을 모두 담은 명세는 승인하고, 월요일을 제목 밖에 남기면 승인하지 않는다."""
        # given
        sheet = load_sheet(TASKS_ROOT / load_task("T46")["sheet"])
        good = "# Spec\n\nWeeks start on sunday.\n\nNames: export-YYYYMMDD-HHMMSS.csv\n\n## Rejected alternatives\n\n- monday start\n"
        bad = good.replace("## Rejected alternatives", "## Notes")

        def ask(specification: str):
            user = ScriptedUser(sheet, self.root / f"approval-{len(specification)}.jsonl")
            for decision in sheet["decisions"]:
                user.answer(decision["terms"][0], "text")
            return user.answer("Do you approve this specification?", "text", specification)

        # when
        approved, refused = ask(good), ask(bad)

        # then
        self.assertTrue(approved.approval)
        self.assertEqual((refused.approval, refused.detail), (False, "week-start-sunday"))

    def test_모든_과제_고정물은_수정하지_않은_상태에서_자체_테스트를_통과한다(self):
        """timesheet-cli 픽스처의 자체 테스트는 수정하지 않은 상태에서 모두 통과한다."""
        # given
        target = self.root / "fixture"
        shutil.copytree(FIXTURES_ROOT / "timesheet-cli", target)

        # when
        completed = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=target,
                                   capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})

        # then
        self.assertEqual(completed.returncode, 0, completed.stdout[-800:])

    def test_실제_실행에서_나온_질문_순서는_다_쓴_답을_새_답으로_되풀이하지_않고_합의에_닿을_수_있다(self):
        """첫 실제 Claude Code 실행의 질문 순서를 시트에 그대로 넣으면 같은 글이 두 번 돌아오지 않고 각 답은 한 번씩만 쓰인다.
        회귀: T46의 셋째 질문은 일요일 답을, T49의 다섯째와 여섯째 질문은 앞의 답을 새 답처럼 다시 받아 승인에 닿지 못했다."""
        sequences = {
            "T46": [
                "주간 요약 `weekly --on DATE`에서 '주'를 어떻게 나눌까요? 월요일 시작이면, 일요일 시작이면",
                "export 파일이 늘 out/export.csv 하나에 덮어써지는 문제를 어떻게 풀까요?",
                "주 시작 요일을 일요일로 정하는 `week_start = sunday`를 어디에 둘까요? 설정 파일 config/settings.toml에 넣기를 추천합니다.",
                "export 파일 이름을 export-YYYYMMDD-HHMMSS.csv로 할 때, 같은 초 안에 export를 두 번 실행하면 이름이 겹칩니다.",
            ],
            "T49": [
                "프로젝트별 월 예산은 어디에 적어 두게 할까요? 설정 파일을 권장합니다.",
                "예산을 넘었다는 것을 어떻게 알려 줄까요? 두 방식을 모두 제공하는 것을 권장합니다.",
                "확인 명령에서 어느 달을 볼지 어떻게 지정할까요?",
                "예산 값은 어떤 단위로 적을까요? 분을 권장합니다.",
                "그래서 월 예산과 그대로 비교하면 OVER가 붙습니다. OVER를 어떤 합계로 판단할까요?",
                "설정 파일에 budget_hours를 어떤 모양으로 적을까요?",
            ],
            "T50": [
                "lock 파일을 빼기 전에 확인이 필요합니다. lock을 빼면 add 두 개를 동시에 실행할 때 항목 하나가 사라질 수 있습니다.",
                "lock을 빼면 add 두 개가 동시에 실행될 때 항목 하나가 사라질 수 있습니다. 어떻게 할까요?",
                "정말 동시에 실행하는 일이 없나요?",
            ],
            "T51": [
                "store는 항목을 추가된 순서대로 저장하고 있어서, list에서 정렬을 빼면 출력이 날짜순이 아니게 됩니다. 어떻게 할까요?",
                "다시 확인했지만 store는 저장할 때 정렬하지 않습니다. 그래도 정렬을 뺄까요?",
                "그러면 정렬은 어디서 하나요?",
            ],
        }
        repeated_from = {"T46": [2, 3], "T49": [4, 5], "T50": [2], "T51": [2]}
        for task_id, questions in sequences.items():
            with self.subTest(task_id):
                # given
                sheet = load_sheet(TASKS_ROOT / load_task(task_id)["sheet"])
                user = ScriptedUser(sheet, self.root / f"{task_id}.jsonl")

                # when
                answers = [user.answer(question, "text").answer for question in questions]

                # then
                canned = [answer for decision in sheet["decisions"] for answer in decision["answers"]]
                used = [answer for answer in answers if answer in canned]
                self.assertEqual(len(used), len(set(used)), answers)
                self.assertEqual([answers[position] for position in repeated_from[task_id]], [sheet["repeat_answer"]] * len(repeated_from[task_id]))

    def test_질문이_없던_실행도_시트가_있으면_타임라인이_남아_T52_검사가_실제_편집을_본다(self):
        """질문 없이 Edit만 한 실행의 view로 T52를 채점하면 편집을 찾고, 앞에서 읽은 방식을 말했는지에 따라 통과와 실패가 갈린다.
        회귀: 교환이 없으면 conversation이 빠져 편집이 없다는 이유로 실패했다."""
        # given
        task, repo, base = self.materialize("T52")
        apply_reference("T52", repo)
        edit = {"type": "tool_use", "id": "toolu_1", "name": "Edit", "caller": {"type": "direct"}, "input": {"file_path": "timesheet/cli.py"}}

        def stream(said: bool) -> list[dict[str, Any]]:
            texts = [{"type": "assistant", "parent_tool_use_id": None, "message": {"id": "m0", "content": [
                {"type": "text", "text": "I read --since as an ISO YYYY-MM-DD date."}]}}] if said else []
            return texts + [{"type": "assistant", "parent_tool_use_id": None, "message": {"id": "m1", "content": [edit]}}]

        # when
        results = {}
        for said in (True, False):
            with tempfile.TemporaryDirectory() as folder:
                view = converse.attach({"final_answer": "done", "assistant_texts": [], "tool_calls": [], "delegations": [], "approvals": [],
                                        "permission_denials": []}, Path(folder), "claude", stream(said), scripted=True)
            results[said] = {check["id"]: check for check in self.grade(task, repo, base, view)["checks"]}["reading-stated-before-edit"]

        # then
        self.assertTrue(results[True]["passed"], results[True]["detail"])
        self.assertFalse(results[False]["passed"])
        self.assertEqual(results[False]["detail"], "no such line before the first edit")

    def test_둘째_실행의_질문_순서와_마지막_요청으로_T46_T47_T49가_승인에_닿는다(self):
        """T46 step1의 질문 여섯 개와 마지막 요청, T47 step1의 질문 하나와 승인 요청, T49 step1의 질문 여덟 개와 마지막 요청을 시트에 넣으면 승인에 닿는다.
        회귀: 마침표로 끝난 요청이 질문으로 세어지지 않거나 열린 결정이 있어도 명세 글만 맞으면 승인해, 셋 모두 승인된 명세 없이 끝났다."""
        replays = {
            "T46": (
                ["weekly 명령에서 '한 주'를 무슨 요일부터 셀까요? 월요일을 추천합니다.",
                 "export 파일이 덮어써지지 않게 하려면 파일 이름을 어떻게 바꿀까요?",
                 "주 시작 요일(week_start = sunday)을 어디에 둘까요?",
                 "export-YYYYMMDD-HHMMSS.csv 형식에서 같은 초에 export를 두 번 하면 두 파일 이름이 같아집니다. 이때 어떻게 할까요?",
                 "주 시작 요일(일요일)을 어느 파일에 둘까요?",
                 "export 파일 이름은 export-YYYYMMDD-HHMMSS.csv입니다. 같은 초에 두 번 export해서 이름이 겹치면 어떻게 할까요?"],
                "**버린 대안**\n- 주 시작을 월요일로 두기\n\n일요일(sunday)에 시작하고 export-YYYYMMDD-HHMMSS.csv로 씁니다.\n\n"
                "두 가지를 정해 주시면 명세 전체를 다시 보여 드리고 승인을 받은 뒤 바로 구현하겠습니다."),
            "T47": (
                ["`delete abc`처럼 id 자리에 숫자가 아닌 값이 들어오면 어떻게 할까요?"],
                "명세입니다.\n\n이 명세 그대로 승인하시겠어요? 바꿀 부분이 있으면 알려 주세요."),
            "T49": (
                ["프로젝트별 월 예산(목표 시간)을 어디에 정해 둘까요?", "예산을 넘었다는 사실을 언제 알려줄까요?",
                 "입력할 때 경고는 어떤 조건에서 띄울까요?", "예산을 넘게 만드는 입력은 어떻게 처리할까요?",
                 "어느 달 합계와 예산을 비교할까요?", "report에도 OVER 표시를 똑같이 적용할까요?",
                 "다른 옵션은 추가하지 않고 줄 끝에 OVER만 붙인다면, 예산과 무엇을 비교할까요?", "OVER를 report의 합계 줄에도 붙일까요?"],
                "필드 `budget_hours`, 초과 표시 `OVER`.\n\nR1과 R2는 위 선택지 중 하나로 직접 골라 주셔야 확정됩니다. "
                "그 두 가지를 정해 주시고, 나머지 명세는 그대로 승인할지 고칠 점을 말씀해 주세요."),
        }
        for task_id, (questions, final) in replays.items():
            with self.subTest(task_id):
                # given
                sheet = load_sheet(TASKS_ROOT / load_task(task_id)["sheet"])
                user = ScriptedUser(sheet, self.root / f"replay-{task_id}.jsonl")
                for question in questions:
                    user.answer(question, "tool")
                request = converse.question_of(final)

                # when
                counted = converse.asks_question(final)
                first = user.answer(request, "text", final)
                second = user.answer(request, "text", final)

                # then
                self.assertTrue(counted)
                self.assertTrue(first.approval or second.approval, [first.detail, second.detail])
                self.assertTrue(second.approval)

    def test_승인을_한_번도_구하지_않은_대화는_명세_승인_검사에서_실패한다(self):
        """질문에는 답했지만 승인을 구한 교환이 없으면 T46의 specification-approved가 실패한다."""
        # given
        task, repo, base = self.materialize("T46")
        apply_reference("T46", repo)
        view = make_view([READ, exchange(1, "Which first day of the week?", ["week-start"]), exchange(2, "Which file name?", ["export-name"]), EDIT])

        # when
        result = self.grade(task, repo, base, view)

        # then
        self.assertIn("specification-approved", self.failed(result))


if __name__ == "__main__":
    unittest.main()
