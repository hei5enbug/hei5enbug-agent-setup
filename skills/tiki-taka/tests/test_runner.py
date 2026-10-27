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
        self.codex_home = self.root / "codex-home"
        self.claude_home = self.root / "claude-home"
        self._write_fake_codex()
        self._write_fake_claude()
        self.environment = os.environ.copy()
        self.environment["PATH"] = f"{self.bin_dir}{os.pathsep}{self.environment['PATH']}"
        self.environment["CODEX_HOME"] = str(self.codex_home)
        self.environment["CLAUDE_CONFIG_DIR"] = str(self.claude_home)

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
            if arguments[:2] == ["mcp", "list"]:
                mcp_log = os.environ.get("FAKE_MCP_LOG")
                if mcp_log:
                    with open(mcp_log, "a", encoding="utf-8") as target:
                        target.write(json.dumps({"argv": arguments, "cwd": os.getcwd()}) + "\n")
                time.sleep(float(os.environ.get("FAKE_MCP_DELAY", "0")))
                if os.environ.get("FAKE_MCP_EXIT"):
                    print("fake mcp failure", file=sys.stderr)
                    raise SystemExit(int(os.environ["FAKE_MCP_EXIT"]))
                print(os.environ.get(
                    "FAKE_MCP_LIST",
                    json.dumps([{"name": "aside", "enabled": True}, {"name": "datadog", "enabled": True}]),
                ))
                raise SystemExit(0)
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
            if os.environ.get("FAKE_NO_ROLLOUT") != "1":
                rollout_dir = os.path.join(os.environ["CODEX_HOME"], "sessions", "2026", "10", "15")
                os.makedirs(rollout_dir, exist_ok=True)
                rollout = os.path.join(
                    rollout_dir,
                    "rollout-2026-10-15T00-00-00-11111111-1111-4111-8111-111111111111.jsonl",
                )
                with open(rollout, "w", encoding="utf-8") as target:
                    target.write(json.dumps({"type": "session_meta", "payload": {}}) + "\n")
                    target.write(json.dumps({
                        "type": "turn_context",
                        "payload": {
                            "model": os.environ.get("FAKE_ROLLOUT_MODEL", "gpt-6.1-sol"),
                            "effort": os.environ.get("FAKE_ROLLOUT_EFFORT", "xhigh"),
                        },
                    }) + "\n")
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
            from pathlib import Path

            sys.stdin.read()
            call_log = os.environ.get("FAKE_CLAUDE_CALL_LOG")
            if call_log:
                with open(call_log, "a", encoding="utf-8") as target:
                    target.write(" ".join(sys.argv[1:]) + "\n")
            quota_once = os.environ.get("FAKE_CLAUDE_QUOTA_ONCE") == "1"
            if quota_once and "--session-id" in sys.argv:
                print(json.dumps({
                    "type": "system",
                    "model": "claude-fable-5-1",
                }), flush=True)
                print(json.dumps({
                    "type": "result",
                    "is_error": True,
                    "result": "reached your model limit",
                }), flush=True)
                print("reached your model limit", file=sys.stderr, flush=True)
                raise SystemExit(0)
            active_model = "claude-opus-5-5" if "--resume" in sys.argv else "claude-fable-5-1"
            session_flag = "--session-id" if "--session-id" in sys.argv else "--resume"
            session_id = sys.argv[sys.argv.index(session_flag) + 1]
            effort = sys.argv[sys.argv.index("--effort") + 1]
            model_field = {} if os.environ.get("FAKE_CLAUDE_NO_MODEL") == "1" else {"model": active_model}
            print(json.dumps({
                "type": "system",
                **model_field,
            }), flush=True)
            print(json.dumps({
                "type": "assistant",
                "message": {
                    **model_field,
                    "content": [{"type": "tool_use", "name": "Read"}],
                },
            }), flush=True)
            if os.environ.get("FAKE_CLAUDE_NO_TRANSCRIPT") != "1":
                transcript_dir = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / "-tiki-taka-test"
                transcript_dir.mkdir(parents=True, exist_ok=True)
                synthetic = os.environ.get("FAKE_CLAUDE_SYNTHETIC")
                records = [] if synthetic == "only" else [{
                    "type": "assistant",
                    "effort": os.environ.get("FAKE_CLAUDE_TRANSCRIPT_EFFORT", effort),
                    "message": {"model": active_model},
                }]
                if synthetic:
                    records.append({"type": "assistant", "message": {"model": "<synthetic>"}})
                later_model = os.environ.get("FAKE_CLAUDE_TRANSCRIPT_LATER_MODEL")
                if later_model:
                    records.append({"type": "assistant", "effort": effort, "message": {"model": later_model}})
                (transcript_dir / f"{session_id}.jsonl").write_text(
                    "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8",
                )
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

    def assert_codex_response_rejected(self, state: Path, expected: str) -> None:
        result = self.run_runner("codex", state, "--max-exchanges", "1", "--timeout-seconds", "5")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn(expected, result.stderr)
        self.assertTrue((state / "uncertain").exists())
        self.assertFalse((state / "session-id").exists())

    def test_codex_rollout_model_mismatch_rejects_response(self) -> None:
        """rollout의 실제 모델이 고정 모델과 다르면 응답을 버리고 불확실 상태로 남긴다."""
        self.environment["FAKE_ROLLOUT_MODEL"] = "gpt-5.6-luna"
        self.assert_codex_response_rejected(self.root / "model-mismatch-state", "gpt-5.6-luna")

    def test_codex_rollout_effort_mismatch_rejects_response(self) -> None:
        self.environment["FAKE_ROLLOUT_EFFORT"] = "high"
        self.assert_codex_response_rejected(self.root / "effort-mismatch-state", "'high'")

    def test_codex_missing_rollout_rejects_response(self) -> None:
        """실행 기록이 없으면 설정을 확인할 수 없으므로 응답을 받아들이지 않는다."""
        self.environment["FAKE_NO_ROLLOUT"] = "1"
        self.assert_codex_response_rejected(self.root / "missing-rollout-state", "rollout 기록을 찾을 수 없어")

    def test_fast_effort_is_checked_against_rollout(self) -> None:
        self.environment["FAKE_ROLLOUT_EFFORT"] = "high"
        state = self.root / "fast-rollout-state"
        result = self.run_runner("codex", state, "--fast", "--max-exchanges", "1", "--timeout-seconds", "5")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "Codex 응답\n")

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

    def test_claude_quota_error_stops_the_debate_without_a_fallback_model(self) -> None:
        """Claude 한도 오류는 대체 모델 재시도 없이 상대 실패로 보고되고, 같은 세션의 호출은 한 번뿐이다."""
        # Given
        state = self.root / "claude-quota-state"
        call_log = self.root / "claude-quota-calls.log"
        self.environment["FAKE_CLAUDE_QUOTA_ONCE"] = "1"
        self.environment["FAKE_CLAUDE_CALL_LOG"] = str(call_log)

        # When
        result = self.run_runner(
            "claude",
            state,
            "--max-exchanges",
            "1",
            "--timeout-seconds",
            "5",
        )

        # Then
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("반대쪽 에이전트 호출이 실패했습니다", result.stderr)
        calls = call_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(calls), 1)
        self.assertNotIn("claude-opus-5-5", "\n".join(calls))
        self.assertNotIn("--fallback-model", "\n".join(calls))

    def assert_claude_response_rejected(self, result: subprocess.CompletedProcess[str], state: Path, expected: str) -> None:
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn(expected, result.stderr)
        self.assertTrue((state / "uncertain").exists())
        self.assertFalse((state / "session-id").exists())

    def test_claude_model_evidence_missing_rejects_response(self) -> None:
        """응답 이벤트에 모델이 없으면 기대 모델로 대신하지 않고 응답을 버리며 불확실 상태로 남긴다."""
        # given
        self.environment["FAKE_CLAUDE_NO_MODEL"] = "1"
        state = self.root / "no-model-state"

        # when
        result = self.run_runner("claude", state, "--max-exchanges", "1", "--timeout-seconds", "5")

        # then
        self.assert_claude_response_rejected(result, state, "모델 증거가 없어")

    def test_claude_transcript_effort_mismatch_rejects_response(self) -> None:
        """Claude 기록의 assistant 사고 강도가 고정 값과 다르면 응답을 버리고 불확실 상태로 남긴다."""
        # given
        self.environment["FAKE_CLAUDE_TRANSCRIPT_EFFORT"] = "high"
        state = self.root / "effort-mismatch-claude-state"

        # when
        result = self.run_runner("claude", state, "--max-exchanges", "1", "--timeout-seconds", "5")

        # then
        self.assert_claude_response_rejected(result, state, "'high'")

    def test_claude_transcript_later_model_mismatch_rejects_response(self) -> None:
        """Claude 기록의 뒤쪽 assistant 항목이 고정 모델과 다르면 앞선 모델 이벤트가 맞아도 응답을 버리고 불확실 상태로 남긴다."""
        # given
        self.environment["FAKE_CLAUDE_TRANSCRIPT_LATER_MODEL"] = "claude-opus-5-5"
        state = self.root / "later-model-mismatch-claude-state"

        # when
        result = self.run_runner("claude", state, "--max-exchanges", "1", "--timeout-seconds", "5")

        # then
        self.assert_claude_response_rejected(result, state, "'claude-opus-5-5'이며")

    def test_claude_missing_transcript_rejects_response(self) -> None:
        """Claude 대화 기록이 없으면 사고 강도를 확인할 수 없으므로 응답을 받아들이지 않는다."""
        # given
        self.environment["FAKE_CLAUDE_NO_TRANSCRIPT"] = "1"
        state = self.root / "missing-transcript-state"

        # when
        result = self.run_runner("claude", state, "--max-exchanges", "1", "--timeout-seconds", "5")

        # then
        self.assert_claude_response_rejected(result, state, "기록을 찾을 수 없어")

    def codex_exec_calls(self, argument_log: Path) -> list[list[str]]:
        return [json.loads(line) for line in argument_log.read_text(encoding="utf-8").splitlines()]

    def test_codex_opponent는_설정된_MCP_서버마다_끄는_설정을_시작과_재개에_넘긴다(self) -> None:
        """Codex 상대는 codex mcp list --json의 이름마다 enabled=false를 시작과 재개 호출에 넘기고 빈 mcp_servers는 쓰지 않는다."""
        # given
        state = self.root / "mcp-off-state"
        argument_log = self.root / "mcp-off-arguments.jsonl"
        mcp_log = self.root / "mcp-list.jsonl"
        self.environment["FAKE_ARGUMENT_LOG"] = str(argument_log)
        self.environment["FAKE_MCP_LOG"] = str(mcp_log)
        self.environment["FAKE_MCP_LIST"] = json.dumps(
            [{"name": "aside", "transport": {"command": "secret-command"}}, {"name": "data-dog_2"}]
        )

        # when
        first = self.run_runner("codex", state, "--max-exchanges", "2", "--timeout-seconds", "5")
        second = self.run_runner("codex", state, "--max-exchanges", "2", "--timeout-seconds", "5")

        # then
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        calls = self.codex_exec_calls(argument_log)
        self.assertEqual(len(calls), 2)
        flags = ["-c", "mcp_servers.aside.enabled=false", "-c", "mcp_servers.data-dog_2.enabled=false"]
        for call in calls:
            start = call.index(flags[1])
            self.assertEqual(flags, call[start - 1 : start + 3])
            self.assertNotIn("mcp_servers={}", call)
            self.assertNotIn("secret-command", " ".join(call))
        listings = [json.loads(line) for line in mcp_log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(listings), 2)
        self.assertEqual(["mcp", "list", "--json"], listings[0]["argv"])

    def test_codex_opponent는_MCP_서버_목록을_못_읽으면_호출하지_않고_실패한다(self) -> None:
        """목록 조회 실패나 안전하지 않은 이름은 MCP를 켠 채 실행하지 않고 종료 코드 1로 실패한다."""
        cases = [
            {"FAKE_MCP_EXIT": "5"},
            {"FAKE_MCP_LIST": "not json"},
            {"FAKE_MCP_LIST": json.dumps({"aside": {}})},
            {"FAKE_MCP_LIST": json.dumps([{"name": 'a"b'}])},
            {"FAKE_MCP_LIST": json.dumps([{"name": "a.b"}])},
            {"FAKE_MCP_LIST": json.dumps([{"enabled": True}])},
        ]
        for index, overrides in enumerate(cases):
            with self.subTest(overrides=overrides):
                # given
                state = self.root / f"mcp-failure-state-{index}"
                argument_log = self.root / f"mcp-failure-arguments-{index}.jsonl"
                self.environment["FAKE_ARGUMENT_LOG"] = str(argument_log)
                for key in ("FAKE_MCP_EXIT", "FAKE_MCP_LIST"):
                    self.environment.pop(key, None)
                self.environment.update(overrides)

                # when
                result = self.run_runner("codex", state, "--max-exchanges", "1", "--timeout-seconds", "5")

                # then
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn("MCP", result.stderr)
                self.assertFalse(argument_log.exists())

    def test_claude_opponent는_strict_MCP_설정으로_MCP_설정_없이_실행한다(self) -> None:
        """Claude 상대는 --strict-mcp-config를 넘기고 --mcp-config는 넘기지 않는다."""
        # given
        state = self.root / "claude-strict-state"
        call_log = self.root / "claude-strict-calls.log"
        self.environment["FAKE_CLAUDE_CALL_LOG"] = str(call_log)

        # when
        result = self.run_runner("claude", state, "--max-exchanges", "1", "--timeout-seconds", "5")

        # then
        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = call_log.read_text(encoding="utf-8").split()
        self.assertIn("--strict-mcp-config", arguments)
        self.assertNotIn("--mcp-config", arguments)

    def test_claude_transcript의_synthetic_항목은_무시하고_다른_항목만_검증한다(self) -> None:
        """모델이 <synthetic>인 assistant 항목은 건너뛰고 나머지 항목이 고정 모델과 사고 강도에 맞으면 응답을 받아들인다."""
        # given
        self.environment["FAKE_CLAUDE_SYNTHETIC"] = "1"
        state = self.root / "synthetic-ignored-state"

        # when
        result = self.run_runner("claude", state, "--max-exchanges", "1", "--timeout-seconds", "5")

        # then
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "Claude 응답\n")

    def test_claude_transcript에_synthetic_항목만_있으면_응답을_버린다(self) -> None:
        """실제 모델이 응답한 assistant 항목이 하나도 없으면 synthetic 항목이 있어도 응답을 받아들이지 않는다."""
        # given
        self.environment["FAKE_CLAUDE_SYNTHETIC"] = "only"
        state = self.root / "synthetic-only-state"

        # when
        result = self.run_runner("claude", state, "--max-exchanges", "1", "--timeout-seconds", "5")

        # then
        self.assert_claude_response_rejected(result, state, "실제 모델이 응답한")

    def test_claude_transcript의_synthetic_항목이_있어도_다른_항목의_불일치는_거부한다(self) -> None:
        """synthetic 항목을 건너뛴 뒤에도 남은 항목의 모델이나 사고 강도가 다르면 응답을 버린다."""
        # given
        self.environment["FAKE_CLAUDE_SYNTHETIC"] = "1"
        self.environment["FAKE_CLAUDE_TRANSCRIPT_EFFORT"] = "high"
        state = self.root / "synthetic-mismatch-state"

        # when
        result = self.run_runner("claude", state, "--max-exchanges", "1", "--timeout-seconds", "5")

        # then
        self.assert_claude_response_rejected(result, state, "'high'")

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

    def test_느린_MCP_목록_조회는_응답_제한_시간을_쓰지_않는다(self) -> None:
        """Codex MCP 목록 조회가 응답 제한 시간보다 오래 걸려도 교환을 시작하고, 응답 시간 초과만 불확실 상태로 남긴다."""
        # given
        state = self.root / "slow-mcp-state"
        self.environment["FAKE_MCP_DELAY"] = "1.5"
        # when
        result = self.run_runner("codex", state, "--max-exchanges", "1", "--timeout-seconds", "1", delay=3)
        # then
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((state / "uncertain").exists(), result.stderr)
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
