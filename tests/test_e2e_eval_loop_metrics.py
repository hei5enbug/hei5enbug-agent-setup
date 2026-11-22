"""Unit tests for the loop measures of one run: reviewer runs, and main-session turns and tokens from the first review."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals/e2e"))

from harness import loop_metrics, metrics, transcript  # noqa: E402

REVIEW = "python3 /plugin/scripts/text_review.py review --kind issue-body --draft out/body.txt --rules docs/rules.md"
LANGUAGE = "python3 /plugin/scripts/role_runner.py language --assignment a.md --result r.md --instructions role.md"
REVIEWER_RESULT = json.dumps({"stage": "review", "kind": "issue-body", "findings": [{"type": "removable"}]})
CHECK_RESULT = json.dumps({"stage": "check", "findings": [{"rule": "repeated-check"}], "advisories": []})


def call(command, result, source="main"):
    return {"id": command[:8] + result[:8], "name": "Bash", "input": {"command": command}, "result_text": result,
            "is_error": False, "parent": None, "source": source}


def claude_turn(message_id, command=None, parent=None, output=10):
    block = {"type": "tool_use", "id": f"t-{message_id}", "name": "Bash", "input": {"command": command}} if command else \
        {"type": "text", "text": "words"}
    usage = {"input_tokens": 1, "output_tokens": output, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 20}
    return {"type": "assistant", "parent_tool_use_id": parent,
            "message": {"id": message_id, "model": "claude-opus-5-5", "usage": usage, "content": [block]}}


def codex_usage(total, last):
    info = {"total_token_usage": {"total_tokens": total}, "last_token_usage": {"input_tokens": last, "output_tokens": 5}}
    return {"type": "event_msg", "payload": {"type": "token_count", "info": info}}


def codex_call(command):
    return {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "call_id": "c1",
                                                  "arguments": json.dumps({"cmd": command})}}


class ReviewerRunsTest(unittest.TestCase):
    def test_검토자에_닿은_실행과_점검에서_멈춘_실행을_모든_세션의_호출에서_따로_센다(self):
        """given 메인과 작업자의 review 호출 셋 중 하나가 점검에서 멈췄을 때 when 세면 then 검토자 실행 둘과 점검 정지 하나다."""
        # given
        calls = [call(REVIEW, CHECK_RESULT), call(REVIEW, REVIEWER_RESULT, "codex:language"), call(REVIEW, REVIEWER_RESULT),
                 call("ls", "x")]

        # when
        found = loop_metrics.reviewer_runs(calls)

        # then
        self.assertEqual(found, {"reviewer_runs": 2, "check_stops": 1})

    def test_결과가_이스케이프된_JSON_문자열이어도_검토자_단계를_알아본다(self):
        """given Codex 출력처럼 따옴표가 이스케이프된 결과 when 세면 then 검토자 실행으로 센다."""
        # given
        calls = [call(REVIEW, json.dumps({"output": REVIEWER_RESULT}))]

        # when
        found = loop_metrics.reviewer_runs(calls)

        # then
        self.assertEqual(found["reviewer_runs"], 1)


class MainTurnsTest(unittest.TestCase):
    def test_Claude_메인_턴은_첫_검토를_낸_요청부터_끝까지_세고_하위_세션의_요청은_빼다(self):
        """given 초안, 검토 둘, 마무리 요청과 하위 세션 요청 when 세면 then 첫 검토 요청부터 3턴이고 토큰은 전체와 구간으로 나뉜다."""
        # given
        events = [claude_turn("m1"), claude_turn("m2", REVIEW), claude_turn("s1", parent="agent-1"),
                  claude_turn("m3", REVIEW), claude_turn("m4")]

        # when
        found = loop_metrics.claude_main_figures(events)

        # then
        self.assertEqual((found["loop_started"], found["main_requests"], found["main_turns"]), (True, 4, 3))
        self.assertEqual(found["main_tokens"]["output"], 40)
        self.assertEqual(found["main_tokens_loop"], {"input": 3, "output": 30, "cache_read": 300, "cache_write": 60})

    def test_Claude_작업자에게_루프를_넘기는_language_호출도_루프의_시작이다(self):
        """given 메인이 language 작업자를 부르고 결과를 읽는 요청 둘 when 세면 then 부르는 요청부터 센다."""
        # given
        events = [claude_turn("m1"), claude_turn("m2", LANGUAGE), claude_turn("m3")]

        # when
        found = loop_metrics.claude_main_figures(events)

        # then
        self.assertEqual(found["main_turns"], 2)

    def test_검토를_한_번도_하지_않으면_루프가_시작되지_않고_턴은_0이다(self):
        """given 검토 호출이 없는 요청들 when 세면 then loop_started는 거짓이고 턴과 구간 토큰은 0이다."""
        # given
        events = [claude_turn("m1"), claude_turn("m2")]

        # when
        found = loop_metrics.claude_main_figures(events)

        # then
        self.assertEqual((found["loop_started"], found["main_turns"], found["main_tokens"]["output"]), (False, 0, 20))
        self.assertEqual(found["main_tokens_loop"]["output"], 0)

    def test_Codex_메인_턴은_첫_검토_호출_뒤의_요청부터_센다(self):
        """given 호출 앞 요청 하나와 호출을 낸 요청, 마무리 요청 when 세면 then 호출을 낸 요청부터 2턴이다."""
        # given
        events = [codex_usage(100, 60), codex_call(REVIEW), codex_usage(200, 70), codex_usage(300, 80)]

        # when
        found = loop_metrics.codex_main_figures(events)

        # then
        self.assertEqual((found["loop_started"], found["main_requests"], found["main_turns"]), (True, 3, 2))
        self.assertEqual(found["main_tokens_loop"]["input"], 150)
        self.assertEqual(found["main_tokens"]["input"], 210)

    def test_run의_loop_수치는_metrics_json에_review_loop로_담긴다(self):
        """given build_metrics에 loop 수치를 넘길 때 when 만들면 then metrics에 그대로 review_loop로 담긴다."""
        # given
        figures = loop_metrics.review_loop([call(REVIEW, REVIEWER_RESULT)], [claude_turn("m1", REVIEW), claude_turn("m2")], "claude")
        empty = {"tokens": {}, "list_cost_usd": 0.0, "list_cost_usd_estimate": 0.0, "unpriced_models": [], "list_cost_usd_by_source": {}}
        run = {"run_id": "T13-b-r1", "task": "T13", "variant": "b", "rep": 1, "status": "complete"}

        # when
        result = metrics.build_metrics(run=run, task={}, view=transcript.build_view([]), facts={}, claude_report=empty,
                                       codex_report=empty, grade=None, rubric=None, checks={}, usage_source="stream",
                                       review_loop=figures)

        # then
        self.assertEqual(result["review_loop"]["reviewer_runs"], 1)
        self.assertEqual(result["review_loop"]["main_turns"], 2)


if __name__ == "__main__":
    unittest.main()
