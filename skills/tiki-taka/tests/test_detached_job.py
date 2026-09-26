#!/usr/bin/env python3
"""분리 실행 도우미의 대기 조건과 결과 파일 보존을 검사한다."""

from __future__ import annotations

import subprocess
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "detached_job.py"


class DetachedJobTest(unittest.TestCase):
    def test_exited_parent_does_not_leave_child_running(self) -> None:
        """직접 실행한 프로세스가 종료되어도 남은 자식 프로세스를 정리한다."""
        # Given
        heartbeat = self.state / "heartbeat"
        pid_file = self.state / "child-pid"
        child_code = (
            "import signal,time; from pathlib import Path; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            f"p=Path({str(heartbeat)!r}); "
            "exec('while True:\\n p.write_text(str(time.time_ns())); time.sleep(0.02)')"
        )
        parent_code = (
            "import subprocess,sys; from pathlib import Path; "
            f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}], "
            "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
            f"Path({str(pid_file)!r}).write_text(str(p.pid))"
        )
        driver = (
            "import subprocess,sys,time; from pathlib import Path; "
            f"sys.path.insert(0,{str(SCRIPT.parent)!r}); "
            "from detached_job import terminate_group; import stream_agent; "
            "stream_agent.GROUP_GRACE_SECONDS=0.1; "
            f"p=subprocess.Popen([sys.executable,'-c',{parent_code!r}],start_new_session=True); "
            "p.wait(); "
            f"\nfor _ in range(100):\n if Path({str(heartbeat)!r}).exists(): break\n time.sleep(0.02)\n"
            "terminate_group(p)"
        )
        try:
            # When
            result = subprocess.run([sys.executable, "-c", driver], capture_output=True, text=True, timeout=10)
            first = heartbeat.read_text()
            time.sleep(0.1)
            second = heartbeat.read_text()
            # Then
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(first, second)
        finally:
            if pid_file.exists():
                try:
                    os.kill(int(pid_file.read_text()), 9)
                except ProcessLookupError:
                    pass

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="tiki-taka-job.")
        self.state = Path(self.temporary.name)
        self.pid = self.state / "worker-pid"
        self.exit = self.state / "worker-exit"
        self.result = self.state / "worker-result.txt"
        self.log = self.state / "worker-progress.log"
        self.uncertain = self.state / "uncertain"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def wait(self, *extra: str, timeout: float = 5) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(SCRIPT),
            "wait",
            "--pid-file",
            str(self.pid),
            "--exit-file",
            str(self.exit),
            "--result-file",
            str(self.result),
            "--progress-log",
            str(self.log),
            "--uncertain-file",
            str(self.uncertain),
            "--poll-seconds",
            "0.1",
            *extra,
        ]
        return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)

    def test_missing_job_fails_immediately(self) -> None:
        started = time.monotonic()
        result = self.wait("--collect")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("기다릴 분리 실행 작업이 없습니다", result.stderr)
        self.assertLess(time.monotonic() - started, 3)
        self.assertFalse(self.uncertain.exists())

    def test_malformed_pid_fails_immediately(self) -> None:
        self.pid.write_text("not-a-pid\n", encoding="utf-8")
        started = time.monotonic()
        result = self.wait()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("PID 파일 값", result.stderr)
        self.assertLess(time.monotonic() - started, 3)
        self.assertTrue(self.uncertain.exists())

    def test_non_positive_pid_fails_immediately(self) -> None:
        self.pid.write_text("0\n", encoding="utf-8")
        result = self.wait()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("양수", result.stderr)

    def test_finished_job_without_pid_file_is_collected(self) -> None:
        self.exit.write_text("0\n", encoding="utf-8")
        self.result.write_text("응답\n", encoding="utf-8")
        self.log.write_text("", encoding="utf-8")
        result = self.wait("--collect")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "응답\n")
        self.assertFalse(self.result.exists())
        self.assertFalse(self.exit.exists())

    def test_unreadable_result_is_kept_and_named(self) -> None:
        self.exit.write_text("0\n", encoding="utf-8")
        self.result.mkdir()
        result = self.wait("--collect")
        self.assertEqual(result.returncode, 1)
        self.assertIn("최종 응답을 읽을 수 없습니다", result.stderr)
        self.assertIn(str(self.result), result.stderr)
        self.assertTrue(self.result.exists())
        self.assertTrue(self.exit.exists())

    def test_empty_result_is_kept_and_named(self) -> None:
        self.exit.write_text("0\n", encoding="utf-8")
        self.result.write_text("", encoding="utf-8")
        result = self.wait("--collect")
        self.assertEqual(result.returncode, 1)
        self.assertIn(str(self.result), result.stderr)
        self.assertTrue(self.result.exists())

    def test_failed_job_files_are_cleared_after_collect(self) -> None:
        self.exit.write_text("3\n", encoding="utf-8")
        self.result.write_text("", encoding="utf-8")
        result = self.wait("--collect")
        self.assertEqual(result.returncode, 3)
        self.assertFalse(self.result.exists())
        self.assertFalse(self.exit.exists())


if __name__ == "__main__":
    unittest.main()
