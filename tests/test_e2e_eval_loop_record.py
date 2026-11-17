"""Tests of the loop measures of the independent text review and of the record that decides the candidate loop shapes of issue 102."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from harness import cli, loop_measures, loop_record, records  # noqa: E402
from harness.command import ConfigError  # noqa: E402
from test_e2e_eval_record_cli import seed_run, write  # noqa: E402

REVIEW = "python3 /plugin/scripts/text_review.py review --kind pr-description --draft out/x.md"
CHECK = "python3 /plugin/scripts/text_review.py check --kind pr-description out/x.md"


def bash(call_id: str, command: str, result: str) -> dict:
    return {"id": call_id, "name": "Bash", "input": {"command": command}, "result_text": result, "is_error": False, "parent": None, "source": "main"}


def assistant(message_id: str, command: str | None = None, parent=None, tokens: int = 10) -> dict:
    blocks = [{"type": "text", "text": "ok"}]
    if command:
        blocks.append({"type": "tool_use", "id": f"t-{message_id}", "name": "Bash", "input": {"command": command}})
    return {"type": "assistant", "parent_tool_use_id": parent, "message": {"id": message_id, "content": blocks, "usage": {"output_tokens": tokens}}}


class MeasureTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)

    def test_검토자에_닿은_검토_실행만_세고_점검에서_멈춘_실행과_check와_러너_기록의_호출도_구분한다(self):
        """점검 단계에서 멈춘 review와 check 명령은 세지 않고, Codex가 이스케이프한 결과의 review 단계와 Claude 러너 기록 속의 review 실행은 센다."""
        # given
        stopped = bash("1", REVIEW, 'Exit code 1\n{"stage": "check", "findings": [{"rule": "repeated-check"}]}')
        reached = bash("2", REVIEW, 'Exit code 1\n{"stage": "review", "findings": []}')
        escaped = bash("3", REVIEW, json.dumps({"output": '{"stage": "review", "findings": []}', "metadata": {"exit_code": 0}}))
        checked = bash("4", CHECK, '{"findings": []}')
        write(self.root / "view.json", {"tool_calls": [stopped, reached, escaped, checked]})
        runner_events = [{"type": "assistant", "message": {"id": "m1", "content": [{"type": "tool_use", "id": "r1", "name": "Bash", "input": {"command": REVIEW}}]}},
                         {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "r1", "content": '{"stage": "review", "findings": []}'}]}}]
        runner = self.root / "transcripts" / "runner"
        runner.mkdir(parents=True)
        (runner / "language-1.jsonl").write_text("\n".join(json.dumps(event) for event in runner_events) + "\n", encoding="utf-8")

        # when
        counted = loop_measures.review_runs(loop_measures.run_calls(self.root))

        # then
        self.assertEqual(counted, 3)

    def test_주_세션_턴은_첫_검토를_부른_메시지부터_끝까지이고_하위_에이전트와_같은_메시지의_조각은_세지_않는다(self):
        """첫 review를 부른 메시지부터 마지막까지의 메시지 수를 세고, 같은 ID의 조각과 하위 에이전트 메시지는 한 번도 더하지 않으며 검토가 없으면 0이다."""
        # given
        events = [assistant("m1"), assistant("m2", REVIEW), assistant("m2", REVIEW), assistant("s1", parent="sub"), assistant("m3", REVIEW), assistant("m4")]

        # when
        turns, none = loop_measures.claude_main_turns(events), loop_measures.claude_main_turns([assistant("m1"), assistant("m2", CHECK)])

        # then
        self.assertEqual((turns, none), (3, 0))

    def test_Codex_주_세션_턴은_첫_검토_호출_앞까지_센_요청을_뺀_수이고_주_세션_토큰은_캐시를_포함한_합이다(self):
        """첫 review 호출 전에 끝난 요청은 빼고 그 뒤의 새 요청만 세며, 같은 누적 토큰의 반복 이벤트는 한 번만 센다. 토큰은 모델별 입력, 출력, 캐시 읽기와 쓰기의 합이다."""
        # given
        def usage(total: int) -> dict:
            return {"type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 1}, "total_token_usage": {"total": total}}}}

        call = {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "arguments": json.dumps({"cmd": REVIEW})}}
        events = [usage(1), usage(2), call, usage(3), usage(3), usage(4)]
        metrics = {"tokens": {"claude": {}, "codex": {"codex:main": {"gpt-6.1-sol": {"input": 5, "output": 2, "cache_read": 100, "cache_write": 3, "reasoning": 9}}}}}

        # when
        turns, tokens = loop_measures.codex_main_turns(events), loop_measures.main_tokens(metrics, "codex")

        # then
        self.assertEqual((turns, tokens), (2, 110))


class RecordLoopTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        write(self.root / "camp" / "campaign.json", {"inputs": {"variant_shas": {"base": "0123456789abcdef", "cand-a": "fedcba9876543210"}}})
        for variant, runs in (("base", 3), ("cand-a", 2)):
            for host in ("claude", "codex"):
                seed_run(self.root, "T15", variant, host, 1, True, 100.0, 1.0)
        folder = self.root / "camp" / "results" / "T15" / "cand-a"
        events = [assistant("m1"), assistant("m2", REVIEW), assistant("m3")]
        (folder / "rep1" / "stream.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
        write(folder / "rep1" / "view.json", {"tool_calls": [bash("1", REVIEW, '{"stage": "review", "findings": []}'), bash("2", REVIEW, '{"stage": "review", "findings": []}')]})

    def test_기록은_후보별_실행에_통과_여부와_검토_실행_턴_토큰을_담고_라벨로_이름을_바꾸며_검증을_통과한다(self):
        """campaign의 변형 이름 대신 baseline과 a 라벨이 기록에 들어가고, 실행마다 passed, review_runs, main_turns, main_tokens가 있으며 글쓰기 과제 일부만 돌렸으면 후보는 undecided다."""
        # given
        mapping = loop_record.parse_variants("baseline=base,a=cand-a")

        # when
        result = loop_record.record_loop(self.root, "camp", 102, mapping)

        # then
        record = result["record"]
        self.assertEqual(records.validate_record(record), [])
        self.assertEqual({run["variant"] for run in record["runs"]}, {"baseline", "a"})
        claude_a = next(run for run in record["runs"] if (run["variant"], run["host"]) == ("a", "claude"))
        self.assertEqual((claude_a["passed"], claude_a["review_runs"], claude_a["main_turns"]), (True, 2, 2))
        self.assertEqual([(item["candidate"], item["verdict"]) for item in record["decisions"]], [("a", "undecided")])
        self.assertEqual(set(record["variants"]), {"baseline", "a"})

    def test_변형_라벨은_baseline과_a_b_c의_조합만_받고_같은_라벨_두_번이나_기준선_없음은_거부한다(self):
        """a+b는 받고, baseline이 없거나 d 같은 라벨이거나 라벨이 겹치면 설정 오류로 멈춘다."""
        # given
        accepted = loop_record.parse_variants("baseline=x,a=y,a+b=z")
        bad = ("a=y", "baseline=x,d=y", "baseline=x,a=y,a=z", "baseline=x,a")

        # when
        rejected = []
        for text in bad:
            try:
                loop_record.parse_variants(text)
            except ConfigError:
                rejected.append(text)

        # then
        self.assertEqual(accepted, {"baseline": "x", "a": "y", "a+b": "z"})
        self.assertEqual(rejected, list(bad))

    def test_record_loop_명령은_기록을_쓰고_후보별_결정_줄을_출력한다(self):
        """CLI가 records/<issue>.json을 쓰고 후보 한 줄씩 결정과 단계를 출력하며 종료 코드 0이다."""
        # given
        out = io.StringIO()

        # when
        with contextlib.redirect_stdout(out):
            code = cli.main(["record-loop", "--run-root", str(self.root), "--campaign", "camp", "--issue", "102", "--variants", "baseline=base,a=cand-a",
                             "--records-dir", str(self.root / "records")])

        # then
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "records" / "102.json").is_file())
        self.assertIn("a: undecided", out.getvalue())


if __name__ == "__main__":
    unittest.main()
