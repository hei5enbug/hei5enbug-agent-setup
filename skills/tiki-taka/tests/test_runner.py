#!/usr/bin/env python3
"""실제 모델을 호출하지 않고 tiki-taka 실행 상태를 검사한다."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
RUNNER = SKILL_DIR / "run-opponent.sh"


class RunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="tiki-taka-test.")
        self.root = Path(self.temporary.name)
        self.bin_dir = self.root / "bin"
        self.repo = self.root / "repo"
        self.bin_dir.mkdir()
        self.repo.mkdir()
        (self.repo / ".git").mkdir()
        self._write_fake_codex()
        self._write_fake_claude()
        self.environment = os.environ.copy()
        self.environment["PATH"] = f"{self.bin_dir}{os.pathsep}{self.environment['PATH']}"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_executable(self, name: str, source: str) -> None:
        path = self.bin_dir / name
        path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def _write_fake_codex(self) -> None:
        self._write_executable(
            "codex",
            r'''
            #!/usr/bin/env python3
            import json
            import os
            import sys
            import time

            arguments = sys.argv[1:]
            output = arguments[arguments.index("-o") + 1]
            sys.stdin.read()
            call_log = os.environ.get("FAKE_CALL_LOG")
            if call_log:
                with open(call_log, "a", encoding="utf-8") as target:
                    target.write(f"{os.getpid()}\n")
            argument_log = os.environ.get("FAKE_ARGUMENT_LOG")
            if argument_log:
                with open(argument_log, "a", encoding="utf-8") as target:
                    target.write(json.dumps(arguments) + "\n")
            print(json.dumps({
                "type": "thread.started",
                "thread_id": "11111111-1111-4111-8111-111111111111",
            }), flush=True)
            print(json.dumps({"type": "turn.started"}), flush=True)
            print(json.dumps({
                "type": "item.started",
                "item": {"type": "command_execution"},
            }), flush=True)
            time.sleep(float(os.environ.get("FAKE_DELAY", "0")))
            with open(output, "w", encoding="utf-8") as target:
                target.write("Codex 응답\n")
            print(json.dumps({
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 80,
                    "output_tokens": 20,
                },
            }), flush=True)
            ''',
        )

    def _write_fake_claude(self) -> None:
        self._write_executable(
            "claude",
            r'''
            #!/usr/bin/env python3
            import json
            import os
            import sys
            import time

            sys.stdin.read()
            call_log = os.environ.get("FAKE_CLAUDE_CALL_LOG")
            if call_log:
                with open(call_log, "a", encoding="utf-8") as target:
                    target.write(" ".join(sys.argv[1:]) + "\n")
            quota_once = os.environ.get("FAKE_CLAUDE_QUOTA_ONCE") == "1"
            if quota_once and "--session-id" in sys.argv:
                print(json.dumps({
                    "type": "system",
                    "model": "claude-fable-5",
                }), flush=True)
                print(json.dumps({
                    "type": "result",
                    "is_error": True,
                    "result": "reached your model limit",
                }), flush=True)
                print("reached your model limit", file=sys.stderr, flush=True)
                raise SystemExit(0)
            active_model = "claude-opus-4-8" if "--resume" in sys.argv else "claude-fable-5"
            print(json.dumps({
                "type": "system",
                "model": active_model,
            }), flush=True)
            print(json.dumps({
                "type": "assistant",
                "message": {
                    "model": active_model,
                    "content": [{"type": "tool_use", "name": "Read"}],
                },
            }), flush=True)
            time.sleep(float(os.environ.get("FAKE_DELAY", "0")))
            print(json.dumps({
                "type": "result",
                "is_error": False,
                "result": "Claude 대체 응답" if "--resume" in sys.argv else "Claude 응답",
                "usage": {"input_tokens": 90, "output_tokens": 15},
            }), flush=True)
            ''',
        )

    def run_runner(
        self,
        opponent: str,
        state: Path,
        *extra: str,
        delay: float = 0,
        prompt: str | None = "검토하세요.",
        timeout: float = 10,
    ) -> subprocess.CompletedProcess[str]:
        environment = self.environment.copy()
        environment["FAKE_DELAY"] = str(delay)
        command = [
            "bash",
            str(RUNNER),
            "--opponent",
            opponent,
            "--state-dir",
            str(state),
            "--repo",
            str(self.repo),
            *extra,
        ]
        return subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            env=environment,
            timeout=timeout,
            check=False,
        )

    def test_codex_foreground_response_and_usage(self) -> None:
        state = self.root / "codex-state"
        result = self.run_runner(
            "codex",
            state,
            "--max-exchanges",
            "1",
            "--timeout-seconds",
            "5",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "Codex 응답\n")
        self.assertIn("[tiki-taka]", result.stderr)

        status = self.run_runner("codex", state, "--status", prompt=None)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("exchanges=1/1", status.stdout)
        self.assertIn("토큰=입력 100, 캐시 80, 출력 20", status.stdout)

    def test_quality_effort_is_default_and_fast_is_explicit(self) -> None:
        default_config = self.run_runner(
            "codex",
            self.root / "unused-default-state",
            "--show-config",
            prompt=None,
        )
        fast_config = self.run_runner(
            "codex",
            self.root / "unused-fast-state",
            "--show-config",
            "--fast",
            prompt=None,
        )
        self.assertEqual(default_config.returncode, 0, default_config.stderr)
        self.assertIn("effort=xhigh", default_config.stdout)
        self.assertEqual(fast_config.returncode, 0, fast_config.stderr)
        self.assertIn("effort=high", fast_config.stdout)

    def test_legacy_host_flag_maps_to_opponent(self) -> None:
        command = [
            "bash",
            str(RUNNER),
            "--host",
            "claude",
            "--show-config",
        ]
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            env=self.environment,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("opponent=codex", result.stdout)

    def test_claude_stream_response(self) -> None:
        state = self.root / "claude-state"
        result = self.run_runner(
            "claude",
            state,
            "--max-exchanges",
            "1",
            "--timeout-seconds",
            "5",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "Claude 응답\n")
        self.assertIn("Claude", result.stderr)

    def test_claude_quota_retries_with_fallback_model(self) -> None:
        state = self.root / "claude-quota-state"
        call_log = self.root / "claude-quota-calls.log"
        self.environment["FAKE_CLAUDE_QUOTA_ONCE"] = "1"
        self.environment["FAKE_CLAUDE_CALL_LOG"] = str(call_log)

        result = self.run_runner(
            "claude",
            state,
            "--max-exchanges",
            "1",
            "--timeout-seconds",
            "5",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "Claude 대체 응답\n")
        calls = call_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(calls), 2)
        self.assertIn("--model claude-opus-4-8", calls[1])
        self.assertIn("대체 모델", result.stderr)
        self.assertFalse((state / "uncertain").exists())

    def test_second_exchange_reuses_saved_state(self) -> None:
        """두 번째 교환은 첫 번째와 같은 대화 식별자로 재개한다."""
        # given
        state = self.root / "resume-state"
        argument_log = self.root / "codex-arguments.jsonl"
        self.environment["FAKE_ARGUMENT_LOG"] = str(argument_log)

        # when
        first = self.run_runner(
            "codex",
            state,
            "--max-exchanges",
            "2",
            "--timeout-seconds",
            "5",
        )
        second = self.run_runner(
            "codex",
            state,
            "--max-exchanges",
            "2",
            "--timeout-seconds",
            "5",
        )

        # then
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)

        calls = [json.loads(line) for line in argument_log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(calls), 2)
        self.assertNotIn("resume", calls[0])
        self.assertEqual(calls[1][:2], ["exec", "resume"])
        self.assertIn("11111111-1111-4111-8111-111111111111", calls[1])
        self.assertNotIn("--last", calls[1])
        self.assertNotIn("--continue", calls[1])

        status = self.run_runner("codex", state, "--status", prompt=None)
        self.assertIn("exchanges=2/2", status.stdout)

    def test_uncertain_state_blocks_prompt_replay(self) -> None:
        """응답 수신이 불확실하면 같은 프롬프트를 자동으로 다시 보내지 않는다."""
        # given
        state = self.root / "uncertain-state"
        self.run_runner(
            "codex",
            state,
            "--max-exchanges",
            "2",
            "--timeout-seconds",
            "5",
        )
        (state / "uncertain").write_text("응답 수신 여부 불확실\n", encoding="utf-8")
        argument_log = self.root / "uncertain-codex-arguments.jsonl"
        self.environment["FAKE_ARGUMENT_LOG"] = str(argument_log)

        # when
        result = self.run_runner(
            "codex",
            state,
            "--max-exchanges",
            "2",
            "--timeout-seconds",
            "5",
        )

        # then
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("응답 수신 여부가 불확실합니다", result.stderr)
        self.assertFalse(argument_log.exists())

    def test_timeout_marks_state_uncertain(self) -> None:
        state = self.root / "timeout-state"
        result = self.run_runner(
            "codex",
            state,
            "--max-exchanges",
            "1",
            "--timeout-seconds",
            "1",
            delay=2,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((state / "uncertain").exists())
        self.assertIn("시간 초과", result.stderr)

    def test_detached_job_can_be_observed_and_collected(self) -> None:
        state = self.root / "detached-state"
        launched = self.run_runner(
            "codex",
            state,
            "--max-exchanges",
            "1",
            "--timeout-seconds",
            "5",
            "--detach",
            delay=0.5,
        )
        self.assertEqual(launched.returncode, 0, launched.stderr)
        self.assertIn("state_dir=", launched.stdout)

        status = self.run_runner("codex", state, "--status", prompt=None)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("작업=", status.stdout)

        collected = self.run_runner(
            "codex",
            state,
            "--wait",
            prompt=None,
            timeout=10,
        )
        self.assertEqual(collected.returncode, 0, collected.stderr)
        self.assertEqual(collected.stdout, "Codex 응답\n")
        self.assertFalse((state / "worker-result.txt").exists())

        finished = self.run_runner("codex", state, "--finish", prompt=None)
        self.assertEqual(finished.returncode, 0, finished.stderr)
        self.assertFalse(state.exists())

    def test_concurrent_detach_starts_exactly_one_worker(self) -> None:
        state = self.root / "race-state"
        call_log = self.root / "codex-calls.log"
        environment = self.environment.copy()
        environment["FAKE_DELAY"] = "1"
        environment["FAKE_CALL_LOG"] = str(call_log)
        command = [
            "bash",
            str(RUNNER),
            "--opponent",
            "codex",
            "--state-dir",
            str(state),
            "--repo",
            str(self.repo),
            "--max-exchanges",
            "1",
            "--timeout-seconds",
            "5",
            "--detach",
        ]
        launchers = [
            subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            for _ in range(2)
        ]
        outcomes = [launcher.communicate("검토하세요.", timeout=10) for launcher in launchers]
        codes = sorted(launcher.returncode for launcher in launchers)
        self.assertEqual(codes, [0, 1], outcomes)

        collected = self.run_runner("codex", state, "--wait", prompt=None, timeout=15)
        self.assertEqual(collected.returncode, 0, collected.stderr)
        self.assertEqual(collected.stdout, "Codex 응답\n")
        self.assertEqual(len(call_log.read_text(encoding="utf-8").split()), 1)

    def test_finish_does_not_delete_directory_with_known_name(self) -> None:
        state = self.root / "finish-state"
        result = self.run_runner("codex", state, "--max-exchanges", "1", "--timeout-seconds", "5")
        self.assertEqual(result.returncode, 0, result.stderr)
        decoy = state / "worker-result.txt"
        decoy.mkdir()
        (decoy / "keep.txt").write_text("keep", encoding="utf-8")

        finished = self.run_runner("codex", state, "--finish", prompt=None)
        self.assertNotEqual(finished.returncode, 0)
        self.assertIn("worker-result.txt", finished.stderr)
        self.assertTrue((decoy / "keep.txt").exists())
        self.assertTrue(state.exists())

    def test_durable_mode_returns_final_response(self) -> None:
        state = self.root / "durable-state"
        result = self.run_runner(
            "claude",
            state,
            "--max-exchanges",
            "1",
            "--timeout-seconds",
            "5",
            "--durable",
            delay=0.2,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "Claude 응답\n")


if __name__ == "__main__":
    unittest.main()
