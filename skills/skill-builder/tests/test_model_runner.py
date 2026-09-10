"""Model runner: stdin/stdout contract and cleanup of the whole process group."""

from __future__ import annotations

import os
import shlex
import signal
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))

from scripts.model_runner import RunnerError, run_model  # noqa: E402


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class RunModelTest(unittest.TestCase):
    def test_echoes_stdout_for_a_successful_command(self):
        command = shlex.join([sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())"])
        self.assertEqual(run_model("hello", command, timeout=10), "HELLO")

    def test_non_zero_exit_raises_with_stderr(self):
        command = shlex.join([sys.executable, "-c", "import sys; sys.stderr.write('bad'); sys.exit(3)"])
        with self.assertRaises(RunnerError) as ctx:
            run_model("x", command, timeout=10)
        self.assertIn("status 3", str(ctx.exception))
        self.assertIn("bad", str(ctx.exception))

    def test_missing_executable_raises(self):
        with self.assertRaises(RunnerError):
            run_model("x", "definitely-not-a-real-binary-xyz", timeout=10)

    def test_timeout_kills_parent_and_grandchild(self):
        with tempfile.TemporaryDirectory() as td:
            child_pid_path = Path(td) / "child-pid"
            parent_pid_path = Path(td) / "parent-pid"
            parent = Path(td) / "parent.py"
            parent.write_text(
                textwrap.dedent(
                    f"""
                    import os, subprocess, sys, time
                    from pathlib import Path
                    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    Path({str(child_pid_path)!r}).write_text(str(child.pid))
                    Path({str(parent_pid_path)!r}).write_text(str(os.getpid()))
                    time.sleep(30)
                    """
                ).lstrip()
            )
            started = time.monotonic()
            with self.assertRaises(RunnerError) as ctx:
                run_model("prompt", shlex.join([sys.executable, str(parent)]), timeout=1)
            self.assertIn("timed out", str(ctx.exception))
            self.assertLess(time.monotonic() - started, 15)

            child_pid = int(child_pid_path.read_text())
            parent_pid = int(parent_pid_path.read_text())
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and (pid_alive(child_pid) or pid_alive(parent_pid)):
                    time.sleep(0.05)
                self.assertFalse(pid_alive(parent_pid), "parent survived the timeout")
                self.assertFalse(pid_alive(child_pid), "grandchild survived the timeout")
            finally:
                for pid in (child_pid, parent_pid):
                    if pid_alive(pid):
                        os.kill(pid, signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()
