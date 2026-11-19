"""Tests for ending an end-to-end run that already gave its final answer and has no background task left."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))

from harness import process, runner  # noqa: E402
from harness.config import STATUS_COMPLETE, STATUS_TIMED_OUT  # noqa: E402

FAKE_STREAMER = """#!{python}
import json, os, sys, time
for step in json.loads(os.environ["FAKE_STEPS"]):
    if isinstance(step, (int, float)):
        time.sleep(step)
    else:
        print(json.dumps(step), flush=True)
if os.environ.get("FAKE_END") == "hang":
    time.sleep(60)
"""

RESULT = {"type": "result", "subtype": "success", "is_error": False, "result": "ok", "session_id": "s1"}
STARTED = {"type": "system", "subtype": "task_started", "task_id": "t1"}
NOTIFIED = {"type": "system", "subtype": "task_notification", "task_id": "t1", "status": "completed"}
TASKS_NONE = {"type": "system", "subtype": "background_tasks_changed", "tasks": []}
TASKS_ONE = {"type": "system", "subtype": "background_tasks_changed", "tasks": [{"task_id": "t1"}]}
IDLE = 1.0
POLL = 0.2


class ResultIdleExitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fake = self.root / "fake_agent"
        self.fake.write_text(FAKE_STREAMER.format(python=sys.executable), encoding="utf-8")
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IEXEC)

    def run_fake(self, steps: list, end: str = "hang", wall: float = 30.0, idle: float | None = IDLE):
        env = {**os.environ, "FAKE_STEPS": json.dumps(steps), "FAKE_END": end}
        return process.run_agent(
            [str(self.fake)], self.root, env, self.root / "s.jsonl", self.root / "e.txt", wall, 0.3, 0.3, POLL,
            result_idle_seconds=idle,
        )

    def test_결과를_낸_뒤_백그라운드_작업이_없고_스트림이_멈추면_유휴_시간_뒤_끝내고_결과까지의_시간을_기록한다(self):
        """result 뒤 조용히 매달린 프로세스는 유휴 시간 뒤 종료되고 wall은 result 시각까지다."""
        # given
        steps = [0.5, RESULT, TASKS_NONE]

        # when
        result = self.run_fake(steps)

        # then
        self.assertTrue(result.ended_after_result)
        self.assertFalse(result.timed_out)
        self.assertGreaterEqual(result.wall_seconds, 0.4)
        self.assertLess(result.wall_seconds, 1.4)

    def test_결과_뒤_작업이_시작되고_알림과_두번째_결과가_오면_두번째_결과_뒤에_끝낸다(self):
        """새 줄은 유휴 타이머를 되돌리고, 두번째 result 시각이 wall이 된다."""
        # given
        steps = [0.3, RESULT, 0.5, STARTED, 0.5, NOTIFIED, 0.5, RESULT]

        # when
        result = self.run_fake(steps)

        # then
        self.assertTrue(result.ended_after_result)
        self.assertFalse(result.timed_out)
        self.assertGreaterEqual(result.wall_seconds, 1.7)
        self.assertLess(result.wall_seconds, 2.6)

    def test_백그라운드_작업이_남아_있으면_일찍_끝내지_않고_제한_시간만_끝낸다(self):
        """tasks가 비어 있지 않으면 유휴 시간이 지나도 계속 기다리다 제한 시간에 timed_out이 된다."""
        # given
        steps = [RESULT, TASKS_ONE]

        # when
        result = self.run_fake(steps, wall=3.0)

        # then
        self.assertFalse(result.ended_after_result)
        self.assertTrue(result.timed_out)

    def test_알림이_없는_작업_시작은_백그라운드_작업이_남은_것으로_본다(self):
        """task_started만 있고 task_notification이 없으면 끝내지 않는다."""
        # given
        steps = [RESULT, STARTED]

        # when
        result = self.run_fake(steps, wall=3.0)

        # then
        self.assertFalse(result.ended_after_result)
        self.assertTrue(result.timed_out)

    def test_정상_종료하는_실행은_그대로이다(self):
        """result를 내고 스스로 끝난 실행은 ended_after_result도 timed_out도 아니다."""
        # given
        steps = [RESULT]

        # when
        result = self.run_fake(steps, end="exit")

        # then
        self.assertEqual((result.ended_after_result, result.timed_out, result.returncode), (False, False, 0))

    def test_유휴_시간이_없으면_기존처럼_제한_시간까지_기다린다(self):
        """result_idle_seconds가 None이면 Codex 실행처럼 동작이 바뀌지 않는다."""
        # given
        steps = [RESULT]

        # when
        result = self.run_fake(steps, wall=2.0, idle=None)

        # then
        self.assertEqual((result.ended_after_result, result.timed_out), (False, True))

    def test_결과_뒤_새_턴이_시작되면_다음_결과까지_끝내지_않는다(self):
        """assistant 줄이 오면 답이 아직 안 나온 것으로 보고, 그 뒤 멈추면 제한 시간이 끝낸다."""
        # given
        steps = [RESULT, 0.3, {"type": "assistant", "message": {"content": []}}]

        # when
        result = self.run_fake(steps, wall=3.0)

        # then
        self.assertEqual((result.ended_after_result, result.timed_out), (False, True))


class ResultIdleStatusTest(unittest.TestCase):
    def test_결과_뒤_유휴로_끝난_실행은_aborted_결과가_뒤따라도_완료이다(self):
        """종료 신호로 생긴 aborted result가 마지막이어도 ended_after_result이면 complete이다."""
        # given
        facts = {"has_result": True, "terminal_reason": "aborted_streaming", "plugins": []}

        # when
        status = runner.decide_status(facts, None, False, ended_after_result=True)

        # then
        self.assertEqual(status, STATUS_COMPLETE)

    def test_결과_없이_제한_시간을_넘기면_timed_out이다(self):
        """ended_after_result가 아니면 기존 판정이 유지된다."""
        # given
        facts = {"has_result": True, "plugins": []}

        # when
        status = runner.decide_status(facts, None, True)

        # then
        self.assertEqual(status, STATUS_TIMED_OUT)


if __name__ == "__main__":
    unittest.main()
