"""Tests for the scripted user of the evaluation harness: answers from an answer sheet, approval of a specification, the log,
the approver server's handling of the question tool, and the folder the agent can see."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
TASKS = E2E_ROOT / "tasks"
sys.path.insert(0, str(E2E_ROOT))

from harness import approval_mcp, command, graders, scripted_user as su  # noqa: E402

SHEET = su.parse_sheet({
    "decisions": [
        {"id": "week-start", "terms": ["week", "Sunday"], "answer": "Weeks start on Sunday."},
        {"id": "archive-name", "terms": ["file name", "overwrite"], "answer": "Name the copy entries-YYYYMMDD-HHMM.json."},
    ],
    "required": [
        {"id": "week-start", "terms": ["sunday"], "rejected_terms": ["monday"], "sentence": "Say that weeks start on Sunday."},
        {"id": "archive-name", "terms": ["yyyymmdd-hhmm"], "rejected_terms": ["entries-yyyymmdd.json"],
         "sentence": "Name the copy entries-YYYYMMDD-HHMM.json."},
    ],
})
GOOD_SPEC = "## Goal\nWeeks start on Sunday.\n\n## Archive\nThe copy is named entries-YYYYMMDD-HHMM.json.\n\nApprove this specification?"


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    for args in (["init", "-q", "-b", "main"], ["-c", "user.name=x", "-c", "user.email=x@example.com", "commit", "-q", "--allow-empty",
                                                 "-m", "base"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    return repo


class AnswerTest(unittest.TestCase):
    def test_도구_질문과_평문_질문은_결정의_용어가_있으면_그_결정의_답만_받는다(self):
        """같은 질문을 도구 경로와 평문 경로로 물어도 용어가 있는 결정의 답만 돌아온다."""
        for kind in (su.KIND_TOOL, su.KIND_TEXT):
            with self.subTest(kind):
                # given
                question = "Which day does a WEEK start on?"

                # when
                exchange = su.respond(SHEET, question, kind)

                # then
                self.assertEqual((exchange.matched, exchange.reply), (("week-start",), "Weeks start on Sunday."))
                self.assertFalse(exchange.approval)

    def test_두_결정의_용어가_있는_질문은_두_답을_모두_받는다(self):
        """용어가 두 결정에 걸리면 두 결정의 답을 시트 순서대로 받는다."""
        # given
        question = "Does the week of the archive file name matter?"

        # when
        exchange = su.respond(SHEET, question, su.KIND_TEXT)

        # then
        self.assertEqual(exchange.matched, ("week-start", "archive-name"))
        self.assertEqual(exchange.reply, "Weeks start on Sunday.\nName the copy entries-YYYYMMDD-HHMM.json.")

    def test_용어가_하나도_없는_질문은_권장안을_쓰라는_답을_받는다(self):
        """어느 결정과도 맞지 않는 질문은 시트의 대체 답을 받고 일치한 식별자는 없다."""
        # given / when
        exchange = su.respond(SHEET, "Should the output be colored?", su.KIND_TOOL)

        # then
        self.assertEqual((exchange.matched, exchange.reply), ((), "use your recommendation"))

    def test_선택지_이름과_머리말도_결정_용어로_본다(self):
        """질문 도구의 질문 본문, 머리말, 선택지 이름을 합쳐 용어를 찾는다."""
        # given
        question = {"question": "Which one?", "header": "Overwrite", "options": [{"label": "Keep", "description": "x"}]}

        # when
        exchange = su.respond(SHEET, su.tool_question_text(question), su.KIND_TOOL)

        # then
        self.assertEqual(exchange.matched, ("archive-name",))

    def test_용어의_대안은_세로_막대로_적고_하나만_있어도_찾는다(self):
        """`a|b` 용어는 대안 중 하나만 있어도 일치하고 대소문자를 가리지 않는다."""
        # given / when / then
        self.assertTrue(su.has_term("한 주는 일요일에 시작", "sunday|일요일"))
        self.assertTrue(su.has_term("It is SUNDAY", "sunday|일요일"))
        self.assertFalse(su.has_term("It is Monday", "sunday|일요일"))


class ApprovalTest(unittest.TestCase):
    def test_필수_용어를_모두_가진_명세는_승인되고_승인_문장을_받는다(self):
        # given / when
        exchange = su.respond(SHEET, GOOD_SPEC, su.KIND_TEXT)

        # then
        self.assertEqual((exchange.approval, exchange.approved, exchange.reply), (True, True, SHEET.approved_reply))

    def test_필수_용어가_빠진_명세는_승인되지_않고_첫_실패_항목의_문장을_받는다(self):
        """두 항목이 모두 빠지면 시트 순서로 첫 항목의 문장을, 첫 항목이 있으면 다음 항목의 문장을 받는다."""
        # given
        no_week = "The copy is named entries-YYYYMMDD-HHMM.json. Approve?"
        no_name = "Weeks start on Sunday. Approve?"
        neither = "Approve this?"

        # when
        results = [su.respond(SHEET, text, su.KIND_TEXT) for text in (no_week, no_name, neither)]

        # then
        self.assertEqual([item.approved for item in results], [False, False, False])
        self.assertEqual([item.reply for item in results],
                         ["Say that weeks start on Sunday.", "Name the copy entries-YYYYMMDD-HHMM.json.", "Say that weeks start on Sunday."])
        self.assertEqual([item.failed_point for item in results], ["week-start", "archive-name", "week-start"])

    def test_기각한_선택지의_용어가_대안_제목_밖에_있으면_승인되지_않는다(self):
        """필수 용어를 모두 가져도 기각한 선택지의 용어가 제목 밖에 있으면 그 항목의 문장을 받는다."""
        # given
        spec = GOOD_SPEC + "\n\nWe chose this because Monday weeks confuse the team.\nApprove?"

        # when
        exchange = su.respond(SHEET, spec, su.KIND_TEXT)

        # then
        self.assertEqual((exchange.approved, exchange.failed_point), (False, "week-start"))

    def test_같은_용어가_기각한_대안_제목_아래에_있으면_승인을_막지_않는다(self):
        """제목은 마크다운 제목, 굵은 제목, 한국어 제목 모두 인정하고, 다음 제목에서 구역이 끝난다."""
        for heading in ("## Rejected alternatives", "**Rejected alternatives**", "Rejected alternatives:", "### 기각한 대안"):
            with self.subTest(heading):
                # given
                spec = f"{GOOD_SPEC}\n\n{heading}\n- Monday weeks, because the team counts from Sunday.\n- entries-YYYYMMDD.json, which overwrites.\n"

                # when
                exchange = su.respond(SHEET, spec, su.KIND_TEXT)

                # then
                self.assertEqual((exchange.approved, exchange.reply), (True, SHEET.approved_reply))

    def test_제목_구역은_다음_제목에서_끝나므로_그_뒤의_용어는_막는다(self):
        # given
        spec = f"{GOOD_SPEC}\n\n## Rejected alternatives\n- Monday weeks.\n\n## Notes\nMonday is a holiday.\n"

        # when
        exchange = su.respond(SHEET, spec, su.KIND_TEXT)

        # then
        self.assertEqual((exchange.approved, exchange.failed_point), (False, "week-start"))

    def test_승인_요청은_질문과_다른_명세_본문으로_판정할_수_있다(self):
        """질문이 짧아도 따로 준 명세 본문이 판정 대상이다."""
        # given / when
        approved = su.respond(SHEET, "Do you approve?", su.KIND_TOOL, GOOD_SPEC)
        rejected = su.respond(SHEET, "Do you approve?", su.KIND_TOOL, "Weeks start on Sunday.")

        # then
        self.assertEqual((approved.approved, rejected.approved), (True, False))

    def test_승인_뒤_답하지_않는_시트는_이후_질문에_답을_주지_않는다(self):
        """answer_after_approval이 거짓이면 승인 뒤의 질문은 답이 없고 기록만 남는다."""
        # given
        sheet = su.parse_sheet({"decisions": [], "required": [], "answer_after_approval": False})

        # when
        first = su.respond(sheet, "Do you approve this specification?", su.KIND_TEXT)
        later = su.respond(sheet, "What should I do next?", su.KIND_TEXT, approved_before=True)

        # then
        self.assertEqual((first.approved, first.reply), (True, sheet.approved_reply))
        self.assertIsNone(later.reply)


class QuestionShapeTest(unittest.TestCase):
    def test_마지막_줄이_물음표로_끝나야_질문이다(self):
        for text, expected in (("Done.\nWhich one?", True), ("Which one? **", True), ("어느 쪽이 좋을까요？", True),
                               ("Done. Should I also? Details follow.", False), ("", False), ("All good.", False)):
            with self.subTest(text):
                self.assertEqual(su.ends_with_question(text), expected)


class LogTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_로그는_모든_교환과_일치한_식별자를_담는다(self):
        """도구 질문 하나와 평문 질문 하나가 순서대로 기록되고 승인은 명세 본문도 남긴다."""
        # given
        log = self.root / su.LOG_NAME
        repo = make_repo(self.root)

        # when
        su.log_exchange(log, su.respond(SHEET, "Which week day?", su.KIND_TOOL), None, repo, "toolu_1")
        su.log_exchange(log, su.respond(SHEET, GOOD_SPEC, su.KIND_TEXT), GOOD_SPEC, repo)
        entries = su.load_log(log)

        # then
        self.assertEqual([(item["kind"], item["matched"], item["approval"]) for item in entries],
                         [("tool", ["week-start"], False), ("text", ["week-start", "archive-name"], True)])
        self.assertEqual(entries[0]["tool_use_id"], "toolu_1")
        self.assertEqual(entries[1]["specification"], GOOD_SPEC)
        self.assertEqual((entries[0]["edited"], entries[0]["commits"]), ([], 1))

    def test_로그는_질문_때_에이전트가_고친_경로와_커밋_수를_담는다(self):
        # given
        repo = make_repo(self.root)
        (repo / "new.py").write_text("x = 1\n", encoding="utf-8")
        (repo / "__pycache__").mkdir()
        (repo / "__pycache__" / "a.pyc").write_bytes(b"0")

        # when
        state = su.repo_state(repo)

        # then
        self.assertEqual(state, {"edited": ["new.py"], "commits": 1})

    def test_로그_파일이_없거나_깨진_줄이_있으면_그_줄만_빠진다(self):
        # given
        path = self.root / "log.jsonl"
        path.write_text('{"kind": "text"}\nnot json\n[1]\n', encoding="utf-8")

        # when / then
        self.assertEqual(su.load_log(path), [{"kind": "text"}])
        self.assertEqual(su.load_log(self.root / "missing.jsonl"), [])


class ToolAnswerTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.log = str(self.root / su.LOG_NAME)
        self.repo = make_repo(self.root)

    def test_질문_도구_호출은_질문마다_자유_입력_답을_돌려준다(self):
        """답은 질문 본문을 키로 하고 선택지 이름이 아닌 시트의 답 문장이며, 두 질문을 한 호출에 담아도 각각 기록한다."""
        # given
        tool_input = {"questions": [
            {"question": "Which day does a week start?", "header": "Week", "options": [{"label": "Sunday"}, {"label": "Monday"}]},
            {"question": "Should output be colored?", "header": "Color", "options": [{"label": "Yes"}, {"label": "No"}]}]}

        # when
        verdict = su.answer_tool_input(SHEET, tool_input, self.log, None, str(self.repo), "toolu_9")

        # then
        self.assertEqual(verdict["behavior"], "allow")
        self.assertEqual(verdict["updatedInput"]["answers"],
                         {"Which day does a week start?": "Weeks start on Sunday.", "Should output be colored?": "use your recommendation"})
        self.assertEqual(verdict["updatedInput"]["questions"], tool_input["questions"])
        self.assertEqual([item["matched"] for item in su.load_log(self.log)], [["week-start"], []])

    def test_승인_요청은_스트림의_직전_질문_이후_조수_텍스트로_판정한다(self):
        """질문 도구 호출 앞에 보인 명세가 판정 대상이고, 그 앞의 질문 이전 텍스트는 보지 않는다."""
        # given
        def assistant(*blocks):
            return {"type": "assistant", "parent_tool_use_id": None, "message": {"content": list(blocks)}}
        text = lambda value: {"type": "text", "text": value}  # noqa: E731
        ask = lambda ident: {"type": "tool_use", "id": ident, "name": su.QUESTION_TOOL, "input": {}}  # noqa: E731
        events = [assistant(text("Monday weeks were considered earlier."), ask("toolu_1")), assistant(text(GOOD_SPEC), ask("toolu_2"))]

        # when
        spec = su.assistant_text_since_last_question(events, "toolu_2")
        verdict = su.answer_tool_input(SHEET, {"questions": [{"question": "Do you approve?"}]}, self.log, spec, str(self.repo), "toolu_2")

        # then
        self.assertEqual(spec, GOOD_SPEC)
        self.assertEqual(verdict["updatedInput"]["answers"], {"Do you approve?": SHEET.approved_reply})
        self.assertEqual(su.load_log(self.log)[0]["approved"], True)

    def test_승인_뒤_답하지_않는_시트는_호출을_거부하고_기록한다(self):
        # given
        sheet = su.parse_sheet({"decisions": [], "required": [], "answer_after_approval": False})
        ask = {"questions": [{"question": "Do you approve this specification?"}]}
        later = {"questions": [{"question": "What next?"}]}

        # when
        first = su.answer_tool_input(sheet, ask, self.log, None, None)
        second = su.answer_tool_input(sheet, later, self.log, None, None)

        # then
        self.assertEqual(first["behavior"], "allow")
        self.assertEqual(second, {"behavior": "deny", "message": su.NOT_AVAILABLE})
        self.assertEqual([item["answered"] for item in su.load_log(self.log)], [True, False])

    def test_승인자_서버는_질문_도구만_시트로_답하고_다른_도구는_평소대로_처리한다(self):
        """MCP 요청 한 건: AskUserQuestion은 답을 받고, Bash는 허용되며, 설정이 없으면 질문도 평소 처리를 받는다."""
        # given
        user = {"sheet": SHEET, "log": self.log, "stream": None}
        ask = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "approve", "arguments": {
            "tool_name": "AskUserQuestion", "tool_use_id": "t1", "input": {"questions": [{"question": "Which week day?"}]}}}}
        bash = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "approve", "arguments": {
            "tool_name": "Bash", "tool_use_id": "t2", "input": {"command": "ls"}}}}

        # when
        asked = approval_mcp.handle(ask, None, None, str(self.repo), user=user)
        shell = approval_mcp.handle(bash, None, None, str(self.repo), user=user)
        plain = approval_mcp.handle(ask, None, None, str(self.repo), user=None)

        # then
        body = json.loads(asked["result"]["content"][0]["text"])
        self.assertEqual(body["updatedInput"]["answers"], {"Which week day?": "Weeks start on Sunday."})
        self.assertEqual(json.loads(shell["result"]["content"][0]["text"])["behavior"], "allow")
        self.assertNotIn("answers", json.loads(plain["result"]["content"][0]["text"])["updatedInput"])

    def test_도구_설정은_과제가_시트를_가질_때만_승인자_환경에_시트_경로를_넣는다(self):
        # given
        with_sheet = {"user": {"sheet": "answers/T49.json"}}

        # when
        env = command.user_env(with_sheet, Path("/tasks"), Path("/results/r1"))
        config = command.mcp_config(Path("/a.jsonl"), None, None, user=env)

        # then
        self.assertEqual(env["EVAL_ANSWER_SHEET"], "/tasks/answers/T49.json")
        self.assertEqual(config["mcpServers"]["eval_approver"]["env"]["EVAL_USER_LOG"], "/results/r1/user-log.jsonl")
        self.assertEqual(command.user_env({}, Path("/tasks"), Path("/results/r1")), {})


class SheetFileTest(unittest.TestCase):
    def test_잘못된_시트는_이유를_대고_거부한다(self):
        for data in ({"decisions": [{"id": "a", "terms": [], "answer": "x"}]},
                     {"decisions": [{"id": "a", "terms": ["t"], "answer": "x"}, {"id": "a", "terms": ["u"], "answer": "y"}]},
                     {"required": [{"id": "a", "terms": ["t"], "sentence": ""}]}, []):
            with self.subTest(data):
                with self.assertRaises(su.SheetError):
                    su.parse_sheet(data)

    def test_세_과제의_시트는_모두_읽히고_답과_문장이_에이전트의_폴더에_없다(self):
        """T49에서 T51까지 시트가 유효하고, 시트의 답과 문장은 픽스처 저장소 어디에도 없으며 내보낸 플러그인에서도 빠진다."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for task_id in ("T49", "T50", "T51"):
            with self.subTest(task_id):
                # given
                task = json.loads((TASKS / f"{task_id}.json").read_text(encoding="utf-8"))
                sheet = su.load_sheet(TASKS / task["user"]["sheet"])
                repo = Path(directory.name) / task_id

                # when
                graders.materialize_fixture(task, E2E_ROOT / "fixtures", TASKS, repo)
                prompt = (TASKS / task["prompt_file"]).read_text(encoding="utf-8")

                # then
                self.assertEqual(su.agent_folder_leaks(repo, sheet), [])
                for decision in sheet.decisions:
                    self.assertNotIn(decision.answer, prompt)
        from harness import plugin_export
        self.assertIn("evals", plugin_export.EXCLUDED_PATHS)

    def test_유출_검사는_답이_들어_있는_파일을_찾아낸다(self):
        # given
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        folder = Path(directory.name)
        (folder / "notes.md").write_text("weeks start on SUNDAY.", encoding="utf-8")

        # when / then
        self.assertEqual(su.agent_folder_leaks(folder, SHEET), ["notes.md"])


if __name__ == "__main__":
    unittest.main()
