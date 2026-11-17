"""Tests for the scripted user of the end-to-end evaluation: its answers, its approval judgment, its log, the approver that
answers the question tool, the turn loop that answers plain-text questions, and the timeline a grader reads."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
sys.path.insert(0, str(E2E_ROOT))

from harness import approval_mcp, command, converse, metrics, pilot_check, timeline  # noqa: E402
from harness.process import ProcessResult  # noqa: E402
from harness.scripted_user import (  # noqa: E402
    DEFAULT_ANSWER, KIND_TEXT, KIND_TOOL, REPEAT_ANSWER, ScriptedUser, SheetError, load_sheet, read_log, sheet_leaks, validate_sheet,
    without_rejected_section,
)

SHEET: dict[str, Any] = {
    "decisions": [
        {"id": "week-start", "terms": ["week start", "first day"], "answers": ["Weeks start on Sunday."]},
        {"id": "file-name", "terms": ["file name"], "answers": ["Put the date in the name.", "Date and time, I said."]},
    ],
    "points": [
        {"id": "sunday", "terms": ["sunday"], "rejected_terms": ["monday"], "sentence": "The week must start on Sunday."},
        {"id": "dated", "terms": ["YYYYMMDD"], "sentence": "The export name must hold YYYYMMDD."},
    ],
}
SPEC = "# Specification\n\nWeeks start on Sunday.\n\nExport names hold YYYYMMDD.\n"


class SheetAnswerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.log = Path(self._temp.name) / "log.jsonl"
        self.user = ScriptedUser(SHEET, self.log)

    def test_결정의_용어가_든_질문은_도구_질문이든_글_질문이든_그_결정의_답만_받는다(self):
        """같은 용어가 든 도구 질문과 글 질문은 종류와 상관없이 해당 결정의 답만 받는다."""
        # given
        question = "Which Week Start should the report use?"

        # when
        by_tool = self.user.answer(question, KIND_TOOL)
        by_text = ScriptedUser(SHEET).answer(question, KIND_TEXT)

        # then
        self.assertEqual((by_tool.answer, by_tool.matched), ("Weeks start on Sunday.", ("week-start",)))
        self.assertEqual((by_text.answer, by_text.matched), ("Weeks start on Sunday.", ("week-start",)))

    def test_두_결정의_용어가_든_질문은_두_답을_모두_받는다(self):
        """두 결정의 용어가 함께 든 질문은 두 결정의 답을 모두 받는다."""
        # given
        question = "What is the first day of the week, and what is the file name?"

        # when
        exchange = self.user.answer(question)

        # then
        self.assertEqual(exchange.matched, ("week-start", "file-name"))
        self.assertEqual(exchange.answer, "Weeks start on Sunday.\nPut the date in the name.")

    def test_용어가_없는_질문은_추천을_따른다는_답을_받는다(self):
        """어떤 결정의 용어도 없는 질문은 추천을 따르라는 기본 답을 받고 일치 목록이 비어 있다."""
        # given
        question = "Should the report be colored?"

        # when
        exchange = self.user.answer(question)

        # then
        self.assertEqual((exchange.answer, exchange.matched), (DEFAULT_ANSWER, ()))

    def test_답이_둘인_결정은_처음_둘째_순서로_답하고_다_쓴_뒤에는_앞의_답이_그대로라고_답한다(self):
        """답이 둘인 결정은 첫 질문에 첫째 답, 다음에 둘째 답을 주고, 셋째 질문은 둘째 답을 다시 받지 않고 시트의 반복 답을 받는다.
        회귀: 마지막 답을 되풀이하면 후속 질문에 같은 글이 돌아와 에이전트가 새 답으로 오해해 명세 합의가 끝나지 않았다."""
        # given
        question = "How should the file name look?"

        # when
        answers = [self.user.answer(question).answer for _ in range(3)]

        # then
        self.assertEqual(answers, ["Put the date in the name.", "Date and time, I said.", REPEAT_ANSWER])

    def test_한_번만_답하는_결정도_다시_일치한_후속_질문에는_같은_답을_되풀이하지_않는다(self):
        """답이 하나인 결정에 일치하는 둘째 질문은 첫 답이 아니라 반복 답을 받고, 일치한 결정은 로그에 남는다.
        회귀: 후속 질문이 같은 낱말을 가졌다는 이유만으로 첫 답이 새 답처럼 돌아왔다."""
        # given
        first = self.user.answer("What is the first day of the week?")

        # when
        follow_up = self.user.answer("Where should the first day be set?")

        # then
        self.assertEqual((first.answer, follow_up.answer), ("Weeks start on Sunday.", REPEAT_ANSWER))
        self.assertEqual(follow_up.matched, ("week-start",))

    def test_다_쓴_결정과_쓰지_않은_결정이_함께_일치하면_쓰지_않은_답만_받는다(self):
        """다 쓴 결정의 답은 빠지고 아직 남은 결정의 답만 합쳐지며, 시트의 반복 답이 있으면 그 글을 쓴다."""
        # given
        sheet = {**SHEET, "repeat_answer": "That stands."}
        user = ScriptedUser(sheet, self.log)
        user.answer("What is the first day of the week?")

        # when
        mixed = user.answer("Is the first day fine, and which file name?")
        exhausted = user.answer("And the first day again?")

        # then
        self.assertEqual(mixed.answer, "Put the date in the name.")
        self.assertEqual(exhausted.answer, "That stands.")

    def test_로그에는_모든_교환이_일치한_식별자와_함께_남고_순서_상태는_로그에서_이어진다(self):
        """다른 프로세스가 같은 로그로 이어 받아도 답 순서가 이어지고, 로그에는 질문과 일치 식별자가 남는다."""
        # given
        first = ScriptedUser(SHEET, self.log).answer("file name?", KIND_TEXT)

        # when
        second = ScriptedUser(SHEET, self.log).answer("file name again?", KIND_TOOL, tool_use_id="toolu_1")

        # then
        logged = read_log(self.log)
        self.assertEqual([item["index"] for item in logged], [1, 2])
        self.assertEqual([item["matched"] for item in logged], [["file-name"], ["file-name"]])
        self.assertEqual((first.answer, second.answer), ("Put the date in the name.", "Date and time, I said."))
        self.assertEqual(logged[1]["tool_use_id"], "toolu_1")


class ApprovalJudgmentTest(unittest.TestCase):
    def ask(self, specification: str, sheet: dict[str, Any] | None = None):
        return ScriptedUser(sheet or SHEET).answer("Do you approve this specification?", KIND_TEXT, specification)

    def test_필수_용어_하나가_빠진_명세는_승인하지_않고_그_항목의_문장을_준다(self):
        """필수 항목의 용어가 하나라도 없으면 승인하지 않고 처음 어긋난 항목의 문장으로 답한다."""
        # given
        specification = "Weeks start on Sunday.\n"

        # when
        exchange = self.ask(specification)

        # then
        self.assertEqual((exchange.approval, exchange.answer, exchange.detail), (False, "The export name must hold YYYYMMDD.", "dated"))

    def test_모든_용어가_있어도_기각한_선택지의_용어가_제목_밖에_있으면_승인하지_않는다(self):
        """필수 용어가 모두 있어도 기각한 선택지의 용어가 기각한 대안 제목 밖에 있으면 승인하지 않는다."""
        # given
        specification = SPEC + "\nThe week could also start on Monday.\n"

        # when
        exchange = self.ask(specification)

        # then
        self.assertEqual((exchange.approval, exchange.detail), (False, "sunday"))

    def test_같은_용어가_기각한_대안_제목_아래에_있으면_승인을_막지_않는다(self):
        """기각한 선택지의 용어가 '기각한 대안' 제목 아래에만 있으면 승인한다."""
        # given
        specification = SPEC + "\n## Rejected alternatives\n\n- Weeks start on Monday: the owner chose Sunday.\n"

        # when
        exchange = self.ask(specification)

        # then
        self.assertEqual((exchange.approval, exchange.answer), (True, "Approved."))

    def test_기각한_대안_절은_같은_수준의_다음_제목에서_끝난다(self):
        """기각한 대안 절 뒤의 같은 수준 제목 아래에 기각한 용어가 나오면 그 용어는 절 밖으로 센다."""
        # given
        text = "## Rejected alternatives\n\nMonday\n\n### Detail\n\nMonday again\n\n## Plan\n\nMonday plan\n"

        # when
        kept = without_rejected_section(text, ["rejected alternatives"])

        # then
        self.assertNotIn("Monday again", kept)
        self.assertIn("Monday plan", kept)

    def test_승인_뒤_멈추는_시트는_다음_질문에_답하지_않고_대화를_끝낸다(self):
        """stop_after_approval인 시트는 승인 뒤의 질문에 답을 주지 않고 끝났다고 표시한다."""
        # given
        with tempfile.TemporaryDirectory() as raw:
            user = ScriptedUser({**SHEET, "stop_after_approval": True}, Path(raw) / "log.jsonl")
            user.answer("approve?", KIND_TEXT, SPEC)

            # when
            after = user.answer("What should I do next?", KIND_TEXT)

        # then
        self.assertTrue(after.ended)
        self.assertIsNone(after.answer)

    def test_로그가_없으면_승인_뒤_상태를_알_수_없어_끝내지_않는다(self):
        """로그 없는 사용자는 이전 교환을 모르므로 승인 직후 질문에도 기본 답을 준다."""
        # given
        user = ScriptedUser({**SHEET, "stop_after_approval": True})

        # when
        user.answer("approve?", KIND_TEXT, SPEC)
        after = user.answer("What next?", KIND_TEXT)

        # then
        self.assertEqual(after.answer, DEFAULT_ANSWER)


class SheetValidationTest(unittest.TestCase):
    def test_점이_문장이나_용어_없이_적힌_시트는_거부한다(self):
        """점에 sentence가 없거나 결정에 용어가 비어 있으면 시트를 읽을 때 오류로 멈춘다."""
        # given
        no_sentence = {"points": [{"id": "p", "terms": ["x"]}]}
        no_terms = {"decisions": [{"id": "d", "terms": [], "answers": ["a"]}]}

        # when
        problems = []
        for sheet in (no_sentence, no_terms, {}):
            with self.assertRaises(SheetError) as caught:
                validate_sheet(sheet)
            problems.append(str(caught.exception))

        # then
        self.assertIn("sentence", problems[0])
        self.assertIn("terms", problems[1])
        self.assertIn("no decision", problems[2])

    def test_에이전트_폴더에_시트_사본이_있으면_찾아낸다(self):
        """시트와 같은 이름이나 같은 내용의 파일이 에이전트 폴더에 있으면 경로를 알려 준다."""
        # given
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            sheet = root / "evals" / "T99.json"
            sheet.parent.mkdir()
            sheet.write_text(json.dumps(SHEET), encoding="utf-8")
            repo = root / "work" / "repo"
            (repo / "notes").mkdir(parents=True)
            (repo / "notes" / "renamed.txt").write_text(json.dumps(SHEET), encoding="utf-8")
            (repo / "README.md").write_text("clean\n", encoding="utf-8")

            # when
            leaks = sheet_leaks(repo, sheet)

        # then
        self.assertEqual(leaks, ["notes/renamed.txt"])

    def test_시트가_있는_과제는_작업_폴더의_시트_사본을_파일럿_검사가_실패로_본다(self):
        """work 폴더에 시트가 복사돼 있으면 파일럿 검사의 시트 항목이 실패한다."""
        # given
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            tasks = root / "tasks"
            (tasks / "sheets").mkdir(parents=True)
            (tasks / "sheets" / "T99.json").write_text(json.dumps(SHEET), encoding="utf-8")
            (tasks / "T99.json").write_text(json.dumps({"sheet": "sheets/T99.json"}), encoding="utf-8")
            copy = root / "camp" / "work" / "T99-baseline-r1" / "repo"
            copy.mkdir(parents=True)
            (copy / "T99.json").write_text("{}", encoding="utf-8")

            # when
            leaked = pilot_check.check_sheet(root / "camp", {"task": "T99", "run_id": "T99-baseline-r1"}, tasks)
            (copy / "T99.json").unlink()
            clean = pilot_check.check_sheet(root / "camp", {"task": "T99", "run_id": "T99-baseline-r1"}, tasks)
            other = pilot_check.check_sheet(root / "camp", {"task": "T98", "run_id": "T98-baseline-r1"}, tasks)

        # then
        self.assertEqual([item[1] for item in leaked], [False])
        self.assertEqual([item[1] for item in clean], [True])
        self.assertEqual(other, [])


class ApproverTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.sheet = self.root / "sheet.json"
        self.sheet.write_text(json.dumps({**SHEET, "stop_after_approval": True}), encoding="utf-8")
        self.log = self.root / "scripted.jsonl"
        self.stream = self.root / "stream.jsonl"
        self.scripted = (str(self.sheet), str(self.log), str(self.stream))

    def call(self, question: str, tool_name: str = "AskUserQuestion") -> dict[str, Any]:
        arguments = {"tool_name": tool_name, "tool_use_id": "toolu_9",
                     "input": {"questions": [{"question": question, "header": "Q", "options": [{"label": "a"}, {"label": "b"}]}]}}
        return approval_mcp.decision(arguments, None, None, self.scripted)

    def test_질문_도구_호출은_자유_입력_칸에_시트의_답이_담겨_허용된다(self):
        """AskUserQuestion은 허용되고, answers에 질문 문장을 키로 시트의 답이 들어가며 도구 입력의 질문은 그대로 돌아온다."""
        # given
        question = "Which first day of the week do you want?"

        # when
        verdict = self.call(question)

        # then
        self.assertEqual(verdict["behavior"], "allow")
        self.assertEqual(verdict["updatedInput"]["answers"], {question: "Weeks start on Sunday."})
        self.assertEqual(verdict["updatedInput"]["questions"][0]["question"], question)

    def test_승인_질문은_도구_호출_앞에_에이전트가_보인_글까지_합쳐_명세로_판정한다(self):
        """승인 요청은 질문 문장만이 아니라 같은 차례에 에이전트가 앞서 보인 텍스트까지 명세로 보고 판정한다."""
        # given
        shown = {"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": SPEC}]}}
        self.stream.write_text(json.dumps(shown) + "\n", encoding="utf-8")

        # when
        verdict = self.call("Do you approve this specification?")

        # then
        self.assertEqual(verdict["updatedInput"]["answers"]["Do you approve this specification?"], "Approved.")
        self.assertEqual(read_log(self.log)[0]["approval"], True)

    def test_글_질문이_먼저_있었으면_도구_질문은_로그의_다음_답을_받는다(self):
        """하네스가 글 질문에 첫째 답을 낸 뒤 승인기가 받는 도구 질문은 둘째 답을 받는다."""
        # given
        ScriptedUser(json.loads(self.sheet.read_text(encoding="utf-8")), self.log).answer("file name?", KIND_TEXT)

        # when
        verdict = self.call("And the file name?")

        # then
        self.assertEqual(list(verdict["updatedInput"]["answers"].values()), ["Date and time, I said."])

    def test_승인_뒤_질문은_거부해_실행을_끝내고_다른_도구는_기존_규칙을_따른다(self):
        """승인 뒤 도구 질문은 거부되고, 시트가 있어도 Bash 같은 다른 도구는 예전처럼 허용된다."""
        # given
        self.call("approve this?")
        specification_ok = ScriptedUser(json.loads(self.sheet.read_text(encoding="utf-8")), self.log)
        specification_ok.answer("approve?", KIND_TEXT, SPEC)

        # when
        ended = self.call("What next?")
        bash = approval_mcp.decision({"tool_name": "Bash", "input": {"command": "ls"}}, None, None, self.scripted)

        # then
        self.assertEqual(ended["behavior"], "deny")
        self.assertEqual(bash["behavior"], "allow")

    def test_시트가_없는_실행은_질문_도구도_예전처럼_입력을_그대로_허용한다(self):
        """시트가 없으면 AskUserQuestion 호출도 입력 그대로 허용되고 answers가 붙지 않는다."""
        # given
        arguments = {"tool_name": "AskUserQuestion", "input": {"questions": [{"question": "q"}]}}

        # when
        verdict = approval_mcp.decision(arguments, None, None, None)

        # then
        self.assertEqual(verdict["updatedInput"], {"questions": [{"question": "q"}]})

    def test_승인기_설정은_시트가_있을_때만_시트_환경_변수를_싣는다(self):
        """mcp 설정은 시트가 있을 때만 시트, 로그, 스트림 경로를 환경에 넣는다."""
        # given
        base = (self.root / "approvals.jsonl", self.root / "work", self.root / "work" / "repo")

        # when
        with_sheet = command.mcp_config(*base, self.sheet, self.log, self.stream)
        without = command.mcp_config(*base)

        # then
        env = with_sheet["mcpServers"]["eval_approver"]["env"]
        self.assertEqual((env["EVAL_SHEET"], env["EVAL_SCRIPTED_LOG"], env["EVAL_STREAM"]), (str(self.sheet), str(self.log), str(self.stream)))
        self.assertNotIn("EVAL_SHEET", without["mcpServers"]["eval_approver"]["env"])


def result(wall: float = 10.0, **extra: Any) -> ProcessResult:
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return ProcessResult(**{"returncode": 0, "timed_out": False, "wall_seconds": wall, "started_at": moment, "ended_at": moment, **extra})


def assistant(text: str, message: str = "m") -> dict[str, Any]:
    return {"type": "assistant", "message": {"id": message, "content": [{"type": "text", "text": text}]}}


def turn_end(text: str) -> dict[str, Any]:
    return {"type": "result", "result": text, "session_id": "s1", "total_cost_usd": 1.0}


INIT = {"type": "system", "subtype": "init", "session_id": "s1"}


class TurnLoopTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.sheet = self.root / "sheet.json"
        self.sheet.write_text(json.dumps(SHEET), encoding="utf-8")
        self.calls: list[list[str]] = []

    def run_loop(self, turns: list[list[dict[str, Any]]], host: str = "claude", wall: float = 600.0, **sheet: Any):
        self.sheet.write_text(json.dumps({**SHEET, **sheet}), encoding="utf-8")
        queue = list(turns)

        def runner(argv, cwd, env, stream_path, stderr_path, wall_seconds, sigint, sigterm, interrupt=None, append=False):
            self.calls.append(list(argv))
            with stream_path.open("a" if append else "w", encoding="utf-8") as stream:
                stream.writelines(json.dumps(event) + "\n" for event in queue.pop(0))
            return result(100.0)

        return converse.run_turns(
            ["claude", "-p", "--", "start"], host=host, cwd=self.root, env={}, result_dir=self.root, sheet_path=self.sheet,
            wall_seconds=wall, sigint_grace=1, sigterm_grace=1, runner=runner)

    def test_질문으로_끝난_차례는_시트의_답으로_이어_받고_질문이_아니면_끝난다(self):
        """질문으로 끝난 차례에는 답을 넣어 --resume으로 이어 가고, 질문 아닌 보고로 끝나면 멈춘다."""
        # given
        turns = [[INIT, assistant("I read the code.\n\nWhich first day of the week?"), turn_end("I read the code.\n\nWhich first day of the week?")],
                 [assistant("Done."), turn_end("Done.")]]

        # when
        merged = self.run_loop(turns)

        # then
        self.assertEqual(self.calls[1][-4:], ["--resume", "s1", "--", "Weeks start on Sunday."])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(merged.wall_seconds, 200.0)
        self.assertEqual([item["kind"] for item in read_log(self.root / "scripted_user.jsonl")], ["text"])

    def test_승인을_구하는_글은_같은_차례의_앞선_글까지_명세로_판정한다(self):
        """마지막 문단이 승인 질문이고 명세는 앞 문단에 있어도 같은 차례의 글 전체로 판정해 승인한다."""
        # given
        final = f"{SPEC}\nDo you approve this specification?"
        turns = [[INIT, assistant(final), turn_end(final)], [assistant("Starting."), turn_end("Starting.")]]

        # when
        self.run_loop(turns)

        # then
        logged = read_log(self.root / "scripted_user.jsonl")
        self.assertEqual((logged[0]["approval"], logged[0]["question"]), (True, "Do you approve this specification?"))

    def test_시트가_끝낸_대화와_다_쓴_시간에는_더_이어_받지_않는다(self):
        """승인 뒤 질문은 답하지 않아 한 차례로 끝나고, 시간이 다 쓰이면 질문이 남아도 이어 받지 않는다."""
        # given
        final = f"{SPEC}\nDo you approve this specification?"
        approving = [[INIT, assistant(final), turn_end(final)],
                     [assistant("What should I do next?"), turn_end("What should I do next?")]]

        # when
        self.run_loop(approving, stop_after_approval=True)
        calls_after_stop = len(self.calls)
        self.calls.clear()
        (self.root / "scripted_user.jsonl").unlink()
        self.run_loop([[INIT, assistant("Which first day of the week?"), turn_end("Which first day of the week?")]], wall=100.0)

        # then
        self.assertEqual(calls_after_stop, 2)
        self.assertEqual(len(self.calls), 1)

    def test_코덱스는_resume_형식으로_이어_받고_샌드박스와_폴더_옵션은_설정으로_옮긴다(self):
        """Codex 이어 받기 명령은 exec resume <thread>이고 -s와 -C는 빠지며 샌드박스는 -c 설정으로 간다."""
        # given
        first = ["codex", "exec", "--json", "-m", "gpt-6.1-sol", "-c", 'model_reasoning_effort="high"', "-s", "danger-full-access",
                 "-C", "/work/repo", "--", "start"]

        # when
        argv = converse.resume_codex(first, "thread-1", "Answer.")

        # then
        self.assertEqual(argv[:3], ["codex", "exec", "resume"])
        self.assertNotIn("-s", argv)
        self.assertNotIn("-C", argv)
        self.assertEqual(argv[-5:], ["-c", converse.CODEX_SANDBOX_CONFIG, "thread-1", "--", "Answer."][-5:])
        self.assertIn("gpt-6.1-sol", argv)

    def test_질문_판별은_마지막_줄의_물음표만_본다(self):
        """마지막 줄이 물음표로 끝나야 질문이고, 중간에 물음표가 있어도 마지막이 평서문이면 질문이 아니다."""
        # given
        texts = {"Is it Sunday?": True, "Is it Sunday? No.": False, "Which one?**": True, "a\n\nb?\n": True, "": False}

        # when
        found = {text: converse.asks_question(text) for text in texts}

        # then
        self.assertEqual(found, texts)

    def test_여러_차례_스트림은_비용_합계를_알_수_없다고_표시해_토큰_비용으로_넘어간다(self):
        """결과 이벤트가 둘 이상이면 마지막 합계가 전체 비용이 아니므로 total_cost_usd를 비워 둔다."""
        # given
        one = [INIT, turn_end("a")]
        two = [INIT, turn_end("a?"), INIT, turn_end("b")]

        # when
        facts_one, facts_two = metrics.stream_facts(one), metrics.stream_facts(two)

        # then
        self.assertEqual((facts_one["total_cost_usd"], facts_two["total_cost_usd"]), (1.0, None))


class TimelineTest(unittest.TestCase):
    def test_클로드_스트림은_도구_질문을_그_호출_뒤에_글_질문을_차례_끝_뒤에_놓는다(self):
        """도구 질문 교환은 AskUserQuestion 호출 바로 뒤에, 글 질문 교환은 그 차례의 result 뒤에 놓인다."""
        # given
        events = [
            assistant("Plan."),
            {"type": "assistant", "message": {"id": "m2", "content": [{"type": "tool_use", "id": "t1", "name": "AskUserQuestion", "input": {}}]}},
            {"type": "assistant", "message": {"id": "m3", "content": [{"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "a.py"}}]}},
            assistant("Which one?", "m4"), turn_end("Which one?"),
            {"type": "assistant", "message": {"id": "m5", "content": [{"type": "tool_use", "id": "t3", "name": "Write", "input": {}}]}},
            turn_end("Done."),
        ]
        exchanges = [{"index": 1, "kind": "tool", "tool_use_id": "t1", "matched": []},
                     {"index": 2, "kind": "text", "matched": ["x"]}]

        # when
        items = timeline.claude_timeline(events, exchanges)

        # then
        self.assertEqual([(item["type"], item.get("name") or item.get("index")) for item in items],
                         [("text", None), ("call", "AskUserQuestion"), ("exchange", 1), ("call", "Edit"), ("text", None),
                          ("exchange", 2), ("call", "Write")])
        self.assertEqual(timeline.first_edit(items), 3)
        self.assertLess(timeline.position_of(items, 2), timeline.first_edit(items, timeline.position_of(items, 2)))

    def test_코덱스_롤아웃은_task_complete를_차례_끝으로_보고_셸_쓰기_명령을_편집으로_센다(self):
        """Codex 롤아웃의 task_complete 뒤에 글 질문 교환이 놓이고, 셸 리다이렉션은 편집, 읽기 명령은 편집이 아니다."""
        # given
        def call(identifier: str, command: str) -> dict[str, Any]:
            return {"type": "response_item", "payload": {"type": "function_call", "call_id": identifier, "name": "shell",
                                                         "arguments": json.dumps({"command": command})}}

        events = [call("c1", "cat README.md"), {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"text": "Which?"}]}},
                  {"type": "event_msg", "payload": {"type": "task_complete"}}, call("c2", "printf x > notes.txt")]
        exchanges = [{"index": 1, "kind": "text", "matched": []}]

        # when
        items = timeline.codex_timeline(events, exchanges)

        # then
        self.assertEqual([item["type"] for item in items], ["call", "text", "exchange", "call"])
        self.assertEqual(timeline.first_edit(items), 3)

    def test_편집_호출_판별은_읽기_명령과_널_리다이렉션을_편집으로_세지_않는다(self):
        """git diff, 테스트 실행, 2>&1, > /dev/null은 편집이 아니고 sed -i, tee, 파이썬 쓰기는 편집이다."""
        # given
        reads = ["git diff --stat", "python3 -m pytest -q 2>&1", "ls > /dev/null", "grep -rn week ."]
        writes = ["sed -i '' s/a/b/ x.py", "echo hi | tee out.txt", "python3 -c \"open('a','w').write('x')\"", "cp a b"]

        # when
        found = {text: timeline.is_edit_call({"name": "Bash", "input": {"command": text}}) for text in reads + writes}

        # then
        self.assertEqual([found[text] for text in reads], [False] * 4)
        self.assertEqual([found[text] for text in writes], [True] * 4)

    def test_시트가_있는_실행은_질문이_없어도_타임라인을_남겨_실제_Edit_호출을_본다(self):
        """로그가 없어도 시트가 있는 과제의 view에는 타임라인이 있고, 실제 stream의 Edit 이벤트 모양에서 첫 편집을 찾는다.
        회귀: 질문이 없던 실행은 conversation이 통째로 빠져 Edit 5번이 있어도 편집이 없다고 채점됐다."""
        # given
        edit = {"type": "tool_use", "id": "toolu_1", "name": "Edit", "caller": {"type": "direct"},
                "input": {"replace_all": False, "file_path": "timesheet/cli.py", "old_string": "a", "new_string": "b"}}
        events = [INIT, {"type": "assistant", "parent_tool_use_id": None, "message": {"id": "m1", "role": "assistant", "content": [edit]}},
                  turn_end("Done.")]
        with tempfile.TemporaryDirectory() as folder:
            # when
            scripted = converse.attach({"final_answer": "Done."}, Path(folder), "claude", events, scripted=True)
            plain = converse.attach({"final_answer": "Done."}, Path(folder), "claude", events)

        # then
        held = scripted["conversation"]
        self.assertEqual(held["exchanges"], [])
        self.assertEqual(timeline.first_edit(held["timeline"]), 0)
        self.assertNotIn("conversation", plain)


if __name__ == "__main__":
    unittest.main()
