"""Tests of the machine-wide measurement lock that `cli.py run` holds so two campaigns never overlap."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E = REPO_ROOT / "evals/e2e"
sys.path.insert(0, str(E2E))

from harness import campaign, cli, measure_lock  # noqa: E402
from harness.config import EXIT_LOCK_HELD, MEASURE_LOCK, MEASURE_LOCK_HOLDER_ENV  # noqa: E402

HOLD_AND_WAIT = (
    "import sys, time; sys.path.insert(0, sys.argv[1]); from pathlib import Path; from harness import measure_lock\n"
    "with measure_lock.hold('crashing run', Path(sys.argv[2])):\n"
    "    print('held', flush=True); time.sleep(60)\n"
)


def run_cli(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(args))
    return code, out.getvalue(), err.getvalue()


class MeasureLockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lock = Path(self.tmp.name) / "state" / "measure.lock"
        self.args = ["run", "--campaign", "demo", "--tasks", "T08", "--lock-file", str(self.lock),
                     "--run-root", str(Path(self.tmp.name) / "runs")]

    def test_기본_잠금_파일은_하니스_상태_폴더의_measure_lock이다(self):
        self.assertEqual(MEASURE_LOCK.name, "measure.lock")
        self.assertEqual(MEASURE_LOCK.parent, Path.home() / ".local/state/hei5enbug-agent-setup")

    def test_첫_실행이_잠금을_쥐는_동안_두_번째_실행은_점유자를_알리고_바로_끝난다(self):
        seen = {}

        def first_run(*_args, **_kwargs):
            started = time.monotonic()
            seen["second"] = run_cli(*self.args)
            seen["elapsed"] = time.monotonic() - started
            seen["holder"] = json.loads(self.lock.read_text(encoding="utf-8"))
            return 0

        with mock.patch.object(campaign, "run_campaign", side_effect=first_run), \
                mock.patch.object(campaign, "discover_tasks", return_value=["T08"]):
            code, _out, _err = run_cli(*self.args)
        second_code, _o, second_err = seen["second"]
        self.assertEqual(code, 0)
        self.assertEqual(second_code, EXIT_LOCK_HELD)
        self.assertNotIn(second_code, (0, 1, 75, 130))
        self.assertIn(f"pid {os.getpid()}", second_err)
        self.assertIn("cli.py run --campaign demo", second_err)
        self.assertEqual(seen["holder"]["pid"], os.getpid())
        self.assertLess(seen["elapsed"], 5)

    def test_첫_실행이_끝나면_잠금이_풀려_다음_실행이_들어간다(self):
        with mock.patch.object(campaign, "run_campaign", return_value=0) as run, \
                mock.patch.object(campaign, "discover_tasks", return_value=["T08"]):
            first = run_cli(*self.args)
            second = run_cli(*self.args)
        self.assertEqual((first[0], second[0]), (0, 0))
        self.assertEqual(run.call_count, 2)
        self.assertEqual(self.lock.read_text(encoding="utf-8"), "")

    def test_실행이_예외로_끝나도_잠금이_풀린다(self):
        with mock.patch.object(campaign, "run_campaign", side_effect=RuntimeError("boom")), \
                mock.patch.object(campaign, "discover_tasks", return_value=["T08"]):
            with self.assertRaises(RuntimeError):
                run_cli(*self.args)
            with mock.patch.object(campaign, "run_campaign", return_value=0):
                self.assertEqual(run_cli(*self.args)[0], 0)

    def test_점유_프로세스가_강제_종료돼도_잠금이_풀린다(self):
        process = subprocess.Popen([sys.executable, "-c", HOLD_AND_WAIT, str(E2E), str(self.lock)], stdout=subprocess.PIPE, text=True)
        self.addCleanup(process.kill)
        self.assertEqual(process.stdout.readline().strip(), "held")
        with self.assertRaises(measure_lock.MeasureLockHeld) as refused:
            with measure_lock.hold("second", self.lock):
                pass
        self.assertIn(f"pid {process.pid}", str(refused.exception))
        self.assertIn("crashing run", str(refused.exception))
        process.kill()
        process.wait()
        with measure_lock.hold("third", self.lock):
            self.assertEqual(json.loads(self.lock.read_text(encoding="utf-8"))["pid"], os.getpid())

    def test_대기_옵션은_잠금이_풀릴_때까지_기다리고_시간이_지나면_포기한다(self):
        ticks = {"now": 0.0, "sleeps": []}
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        holder = open(self.lock, "a+")
        self.addCleanup(holder.close)
        measure_lock.try_lock(holder)

        def sleep(seconds):
            ticks["sleeps"].append(seconds)
            ticks["now"] += seconds
            if len(ticks["sleeps"]) == 3:
                holder.close()

        clock = lambda: ticks["now"]  # noqa: E731
        with measure_lock.hold("waiter", self.lock, 10, clock=clock, sleep=sleep):
            self.assertEqual(len(ticks["sleeps"]), 3)
        holder2 = open(self.lock, "a+")
        self.addCleanup(holder2.close)
        measure_lock.try_lock(holder2)
        with self.assertRaises(measure_lock.MeasureLockHeld):
            with measure_lock.hold("giver-up", self.lock, 2, clock=clock, sleep=sleep):
                pass

    def test_드라이런과_다른_명령은_잠금을_건드리지_않는다(self):
        with measure_lock.hold("outer", self.lock):
            with mock.patch.object(campaign, "discover_tasks", return_value=["T08"]):
                code, _out, err = run_cli(*self.args, "--dry-run")
        self.assertNotEqual(code, EXIT_LOCK_HELD, err)

    def test_잠금을_쥔_러너의_자식_프로세스는_환경_변수로_같은_잠금을_통과한다(self):
        with measure_lock.hold("runner", self.lock):
            with mock.patch.dict(os.environ, {MEASURE_LOCK_HOLDER_ENV: str(os.getpid())}), \
                    mock.patch.object(campaign, "run_campaign", return_value=0) as run, \
                    mock.patch.object(campaign, "discover_tasks", return_value=["T08"]):
                code, _out, _err = run_cli(*self.args)
        self.assertEqual(code, 0)
        run.assert_called_once()
        with measure_lock.hold("runner", self.lock):
            with mock.patch.dict(os.environ, {MEASURE_LOCK_HOLDER_ENV: "1"}):
                with self.assertRaises(measure_lock.MeasureLockHeld):
                    with measure_lock.hold("stranger", self.lock):
                        pass


if __name__ == "__main__":
    unittest.main()
