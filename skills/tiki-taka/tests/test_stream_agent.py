#!/usr/bin/env python3
"""모의 이벤트 스트림으로 상대 응답의 완료 판정과 프로세스 정리를 검사한다."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "stream_agent.py"


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class StreamAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="tiki-taka-stream.")
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.prompt = self.root / "prompt"
        self.prompt.write_text("synthetic", encoding="utf-8")
        self.output = self.state / "out"
        self.progress = self.state / "progress"
        self.uncertain = self.state / "uncertain"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_stream(self, provider: str, script: str, timeout_seconds: int = 5) -> subprocess.CompletedProcess[str]:
        fake = self.root / "fake.py"
        fake.write_text(textwrap.dedent(script).lstrip(), encoding="utf-8")
        command = [
            sys.executable,
            str(SCRIPT),
            "--provider",
            provider,
            "--repo",
            str(self.root),
            "--prompt-file",
            str(self.prompt),
            "--output-file",
            str(self.output),
            "--events-file",
            str(self.state / "events"),
            "--log-file",
            str(self.state / "log"),
            "--progress-file",
            str(self.progress),
            "--uncertain-file",
            str(self.uncertain),
            "--exchange",
            "1",
            "--max-exchanges",
            "2",
            "--model",
            "synthetic",
            "--timeout-seconds",
            str(timeout_seconds),
            "--",
            sys.executable,
            str(fake),
            str(self.output),
        ]
        return subprocess.run(command, text=True, capture_output=True, timeout=timeout_seconds + 10, check=False)

    def progress_phase(self) -> str:
        return json.loads(self.progress.read_text(encoding="utf-8"))["phase"]

    def test_codex_failure_event_with_zero_exit_is_a_failure(self) -> None:
        result = self.run_stream(
            "codex",
            """
            import json, sys
            print(json.dumps({"type": "turn.failed", "error": {"message": "synthetic"}}), flush=True)
            open(sys.argv[1], "w").write("stale text")
            print(json.dumps({"type": "turn.completed", "usage": {}}), flush=True)
            """,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue(self.uncertain.exists())
        self.assertIn("실패 이벤트", self.uncertain.read_text(encoding="utf-8"))
        self.assertEqual(self.progress_phase(), "failed")

    def test_codex_success_requires_turn_completed_and_response(self) -> None:
        result = self.run_stream(
            "codex",
            """
            import json, sys
            print(json.dumps({"type": "turn.started"}), flush=True)
            open(sys.argv[1], "w").write("Codex 응답\\n")
            print(json.dumps({"type": "turn.completed", "usage": {"output_tokens": 1}}), flush=True)
            """,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "Codex 응답\n")
        self.assertFalse(self.uncertain.exists())

    def test_codex_without_turn_completed_fails(self) -> None:
        result = self.run_stream(
            "codex",
            """
            import json, sys
            print(json.dumps({"type": "turn.started"}), flush=True)
            open(sys.argv[1], "w").write("Codex 응답\\n")
            """,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("turn.completed", self.uncertain.read_text(encoding="utf-8"))

    def test_claude_partial_assistant_text_is_not_a_response(self) -> None:
        result = self.run_stream(
            "claude",
            """
            import json
            print(json.dumps({"type": "system", "model": "m"}), flush=True)
            print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "중간 답변"}]}}), flush=True)
            """,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(self.output.exists())
        self.assertIn("result", self.uncertain.read_text(encoding="utf-8"))

    def test_claude_result_event_is_the_response(self) -> None:
        result = self.run_stream(
            "claude",
            """
            import json
            print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "중간 답변"}]}}), flush=True)
            print(json.dumps({"type": "result", "is_error": False, "result": "최종 답변", "usage": {}}), flush=True)
            """,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "최종 답변\n")

    def test_claude_error_result_is_a_failure(self) -> None:
        result = self.run_stream(
            "claude",
            """
            import json
            print(json.dumps({"type": "result", "is_error": True, "result": "oops"}), flush=True)
            """,
        )
        self.assertEqual(result.returncode, 1)
        self.assertTrue(self.uncertain.exists())

    def test_grandchild_is_terminated_after_child_exits(self) -> None:
        child_pid_path = self.root / "grandchild-pid"
        started = time.monotonic()
        result = self.run_stream(
            "codex",
            f"""
            import json, subprocess, sys
            grandchild = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            open({str(child_pid_path)!r}, "w").write(str(grandchild.pid))
            open(sys.argv[1], "w").write("Codex 응답\\n")
            print(json.dumps({{"type": "turn.completed", "usage": {{}}}}), flush=True)
            """,
            timeout_seconds=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(time.monotonic() - started, 15)
        grandchild = int(child_pid_path.read_text(encoding="utf-8"))
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and pid_alive(grandchild):
                time.sleep(0.05)
            self.assertFalse(pid_alive(grandchild), "grandchild survived")
        finally:
            if pid_alive(grandchild):
                os.kill(grandchild, 9)


if __name__ == "__main__":
    unittest.main()
