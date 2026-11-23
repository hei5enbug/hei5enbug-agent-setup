"""Tests for the conversation driver: a plain-text question that ends a turn is answered by the scripted user and the session is
resumed, on both hosts, until a turn ends without a question or the sheet gives no reply."""

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
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))

from harness import codex_host, scripted_user as su, user_turns  # noqa: E402
from harness.config import HarnessConfig  # noqa: E402
from harness.process import ProcessResult  # noqa: E402

SHEET = su.parse_sheet({
    "decisions": [{"id": "week-start", "terms": ["week"], "answer": "Weeks start on Sunday."}],
    "required": [{"id": "week-start", "terms": ["sunday"], "rejected_terms": [], "sentence": "Say Sunday."}],
    "max_exchanges": 3,
})
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def claude_turn(text: str, session: str = "s-1", error: bool = False) -> list[dict[str, Any]]:
    return [{"type": "system", "subtype": "init", "session_id": session},
            {"type": "assistant", "parent_tool_use_id": None, "message": {"id": "m", "content": [{"type": "text", "text": text}]}},
            {"type": "result", "result": text, "is_error": error, "session_id": session}]


def codex_turn(text: str, thread: str = "t-1") -> list[dict[str, Any]]:
    return [{"type": "thread.started", "thread_id": thread},
            {"type": "item.completed", "item": {"id": "i", "type": "agent_message", "text": text}},
            {"type": "turn.completed"}]


class FakeAgent:
    """A stand-in for `run_agent`: each call appends the next canned turn to the stream file and records the command."""

    def __init__(self, turns: list[list[dict[str, Any]]], code: int = 0, timed_out: bool = False):
        self.turns, self.calls, self.code, self.timed_out = turns, [], code, timed_out

    def __call__(self, argv, cwd, env, stream_path, stderr_path, wall_seconds, sigint, sigterm, interrupt=None, append=False):
        self.calls.append({"argv": list(argv), "append": append, "wall": wall_seconds})
        with Path(stream_path).open("a" if append else "w", encoding="utf-8") as stream:
            for event in self.turns[len(self.calls) - 1]:
                stream.write(json.dumps(event) + "\n")
        return ProcessResult(self.code, self.timed_out, 1.5, NOW, NOW, None)


class ConversationTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.log = self.root / su.LOG_NAME

    def drive(self, agent: FakeAgent, host: str, resume=None) -> ProcessResult:
        return user_turns.run_conversation(
            first_argv=["agent", "--", "do it"], resume_argv=resume or user_turns.claude_resume(["agent", "-p", "--", "do it"]),
            host=host, cwd=self.root, env={}, stream_path=self.root / "stream.jsonl", stderr_path=self.root / "stderr.txt",
            wall_seconds=100.0, sigint_grace=1.0, sigterm_grace=1.0, sheet=SHEET, log_path=self.log, run_turn=agent,
            interrupt=threading.Event())

    def test_Claude_Code는_질문으로_끝난_턴마다_같은_플래그에_resume으로_이어_간다(self):
        # given
        agent = FakeAgent([claude_turn("Which week day starts a week?"), claude_turn("Done.")])

        # when
        result = self.drive(agent, "claude")

        # then
        self.assertEqual(agent.calls[1]["argv"], ["agent", "-p", "--resume", "s-1", "--", "Weeks start on Sunday."])
        self.assertEqual([call["append"] for call in agent.calls], [False, True])
        self.assertEqual(result.wall_seconds, 3.0)
        entries = su.load_log(self.log)
        self.assertEqual([(item["kind"], item["matched"], item["answer"]) for item in entries],
                         [("text", ["week-start"], "Weeks start on Sunday.")])

    def test_Codex는_thread_id로_exec_resume을_부른다(self):
        # given
        agent = FakeAgent([codex_turn("Which week day starts a week?"), codex_turn("Done.")])
        cfg = HarnessConfig()

        # when
        self.drive(agent, "codex", lambda session, reply: codex_host.build_codex_resume(cfg, {"models": {}}, session, reply))

        # then
        argv = agent.calls[1]["argv"]
        self.assertEqual(argv[:3], ["codex", "exec", "resume"])
        self.assertEqual(argv[-2:], ["t-1", "Weeks start on Sunday."])
        self.assertIn("gpt-6.1-sol", argv)
        self.assertNotIn("-s", argv)

    def test_Codex는_질문_뒤에_설명_문장이_이어져도_질문으로_읽고_이어_간다(self):
        """Codex 답의 마지막 줄이 문장이어도 앞 줄이 물음표로 끝나면 exec resume 으로 이어 가고, Claude Code 는 마지막 줄 규칙을 그대로 쓴다.
        잡는 회귀: 마지막 줄만 보아 질문을 놓치고 교환 없이 끝나는 Codex 실행."""
        # given
        text = "Which week day starts a week?\n\nThe repository does not say, so I need to confirm."
        codex = FakeAgent([codex_turn(text), codex_turn("Done.")])
        claude = FakeAgent([claude_turn(text)])

        # when
        self.drive(codex, "codex", lambda session, reply: ["codex", "exec", "resume", session, reply])
        calls = len(codex.calls)
        self.log.unlink()
        (self.root / "stream.jsonl").unlink()
        self.drive(claude, "claude")

        # then
        self.assertEqual((calls, len(claude.calls)), (2, 1))
        self.assertEqual(codex.calls[1]["argv"][-2:], ["t-1", "Weeks start on Sunday."])

    def test_질문이_아닌_턴으로_끝나면_더_잇지_않고_기록도_없다(self):
        # given
        agent = FakeAgent([claude_turn("All done.")])

        # when
        self.drive(agent, "claude")

        # then
        self.assertEqual(len(agent.calls), 1)
        self.assertEqual(su.load_log(self.log), [])

    def test_승인_요청은_그_턴의_모든_조수_텍스트로_판정한다(self):
        """명세가 앞 문단에 있고 마지막 줄은 승인 질문뿐이어도 턴 전체 텍스트가 판정 대상이다."""
        # given
        events = [{"type": "system", "subtype": "init", "session_id": "s-1"},
                  {"type": "assistant", "parent_tool_use_id": None, "message": {"id": "a", "content": [{"type": "text", "text": "Weeks start on Sunday."}]}},
                  {"type": "assistant", "parent_tool_use_id": None, "message": {"id": "b", "content": [{"type": "text", "text": "Do you approve?"}]}},
                  {"type": "result", "result": "Do you approve?", "is_error": False}]
        agent = FakeAgent([events, claude_turn("Done.")])

        # when
        self.drive(agent, "claude")

        # then
        entry = su.load_log(self.log)[0]
        self.assertEqual((entry["approval"], entry["approved"]), (True, True))
        self.assertIn("Weeks start on Sunday.", entry["specification"])

    def test_시트가_답하지_않거나_교환_한도에_닿으면_멈춘다(self):
        """승인 뒤 답하지 않는 시트에서는 마지막 질문이 답 없이 기록되고, 한도에서는 더 묻지 않는다."""
        # given
        quiet = su.parse_sheet({"decisions": [], "required": [], "answer_after_approval": False})
        agent = FakeAgent([claude_turn("Do you approve?"), claude_turn("Spec is final. What next?")])

        # when
        result = user_turns.run_conversation(
            first_argv=["agent", "--", "x"], resume_argv=user_turns.claude_resume(["agent", "--", "x"]), host="claude", cwd=self.root,
            env={}, stream_path=self.root / "stream.jsonl", stderr_path=self.root / "stderr.txt", wall_seconds=100.0,
            sigint_grace=1.0, sigterm_grace=1.0, sheet=quiet, log_path=self.log, run_turn=agent)

        # then
        self.assertEqual(len(agent.calls), 2)
        self.assertEqual([item["answered"] for item in su.load_log(self.log)], [True, False])
        self.assertEqual(result.returncode, 0)
        self.log.unlink()
        (self.root / "stream.jsonl").unlink()
        endless = FakeAgent([claude_turn("Which week?")] * 6)
        self.drive(endless, "claude")
        self.assertEqual(len(endless.calls), SHEET.max_exchanges + 1)

    def test_턴이_실패하거나_시간_초과면_이어_가지_않는다(self):
        for agent in (FakeAgent([claude_turn("Which week?", error=True)]), FakeAgent([claude_turn("Which week?")], code=1),
                      FakeAgent([claude_turn("Which week?")], timed_out=True)):
            with self.subTest(agent.code):
                # when
                result = self.drive(agent, "claude")

                # then
                self.assertEqual(len(agent.calls), 1)
                self.assertEqual(su.load_log(self.log), [])
                self.assertEqual(result.timed_out, agent.timed_out)

    def test_남은_시간은_앞_턴이_쓴_만큼_줄고_결과는_합쳐진다(self):
        # given
        results = [ProcessResult(0, False, 2.0, NOW, NOW, None, 1, 0, False), ProcessResult(1, True, 3.0, NOW, NOW, "boom", 0, 2, True)]

        # when
        merged = user_turns.merge(results)

        # then
        self.assertEqual((merged.returncode, merged.timed_out, merged.wall_seconds, merged.error, merged.orphans_killed,
                          merged.leftover_killed, merged.interrupted), (1, True, 5.0, "boom", 1, 2, True))


if __name__ == "__main__":
    unittest.main()
