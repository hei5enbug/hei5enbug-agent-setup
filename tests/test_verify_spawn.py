from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY = REPO_ROOT / "scripts" / "verify_spawn.py"
PARENT = "019e0000-aaaa-bbbb-cccc-000000000001"
AGENT_PATH = "/root/vessel_selection"


def spawn_meta(parent: str = PARENT, agent_path: str = AGENT_PATH) -> dict:
    return {
        "type": "session_meta",
        "payload": {
            "id": "019e0000-cccc-dddd-eeee-000000000002",
            "source": {"subagent": {"thread_spawn": {"parent_thread_id": parent, "depth": 1, "agent_path": agent_path, "agent_role": "scout"}}},
        },
    }


def turn(model: str, effort: str, sandbox: str | None = None) -> dict:
    payload = {"model": model, "effort": effort}
    if sandbox is not None:
        payload["sandbox_policy"] = {"type": sandbox}
    return {"type": "turn_context", "payload": payload}


class VerifySpawnTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.codex_home = Path(self.temp.name).resolve() / "codex-home"

    def write_rollout(self, name: str, lines: list[dict]) -> None:
        folder = self.codex_home / "sessions" / "2026" / "10" / "15"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")

    def verify(
        self, *, parent: str = PARENT, agent_path: str = AGENT_PATH, model: str = "gpt-5.6-luna", effort: str = "xhigh",
        omit: str | None = None, sandbox: str | None = None,
    ):
        arguments = {"--parent": parent, "--agent-path": agent_path, "--model": model, "--effort": effort}
        if sandbox is not None:
            arguments["--sandbox"] = sandbox
        command = [sys.executable, str(VERIFY)]
        for flag, value in arguments.items():
            if flag != omit:
                command += [flag, value]
        env = {"PATH": os.environ.get("PATH", ""), "CODEX_HOME": str(self.codex_home)}
        completed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
        return completed.returncode, json.loads(completed.stdout.strip().splitlines()[-1])

    def test_부모와_agent_path가_맞고_모든_turn_context가_기대값이면_검증된다(self):
        """session_meta의 thread_spawn이 부모와 경로에 맞고 turn_context 두 개가 모두 기대 모델과 effort이면 종료 코드 0이다."""
        # Given
        self.write_rollout("rollout-2026-10-15T10-00-00-child.jsonl", [spawn_meta(), turn("gpt-5.6-luna", "xhigh"), turn("gpt-5.6-luna", "xhigh")])

        # When
        code, status = self.verify()

        # Then
        self.assertEqual(0, code)
        self.assertEqual((True, 2, None), (status["verified"], status["turns"], status["error"]))
        self.assertTrue(status["rollout"].endswith("rollout-2026-10-15T10-00-00-child.jsonl"))

    def test_turn_context의_모델이_다르면_종료_코드_4이다(self):
        """turn_context 모델이 기대와 다르면 검증되지 않고 종료 코드 4이다."""
        # Given
        self.write_rollout("rollout-2026-10-15T10-00-00-child.jsonl", [spawn_meta(), turn("gpt-6-astra", "xhigh")])

        # When
        code, status = self.verify()

        # Then
        self.assertEqual(4, code)
        self.assertFalse(status["verified"])
        self.assertIn("gpt-6-astra", status["error"])

    def test_turn_context의_effort가_다르면_종료_코드_4이다(self):
        """여러 turn_context 중 하나만 effort가 달라도 종료 코드 4이다."""
        # Given
        self.write_rollout("rollout-2026-10-15T10-00-00-child.jsonl", [spawn_meta(), turn("gpt-5.6-luna", "xhigh"), turn("gpt-5.6-luna", "high")])

        # When
        code, status = self.verify()

        # Then
        self.assertEqual(4, code)
        self.assertFalse(status["verified"])

    def test_turn_context가_없으면_증거가_없어_종료_코드_4이다(self):
        """spawn된 rollout에 turn_context가 없으면 종료 코드 4이다."""
        # Given
        self.write_rollout("rollout-2026-10-15T10-00-00-child.jsonl", [spawn_meta()])

        # When
        code, status = self.verify()

        # Then
        self.assertEqual(4, code)
        self.assertEqual(0, status["turns"])

    def test_다른_부모나_다른_agent_path의_rollout은_증거로_쓰지_않는다(self):
        """부모 스레드나 agent_path가 맞지 않는 rollout만 있으면 종료 코드 4이다."""
        # Given
        self.write_rollout("rollout-2026-10-15T10-00-00-other-parent.jsonl", [spawn_meta(parent="other-parent"), turn("gpt-5.6-luna", "xhigh")])
        self.write_rollout("rollout-2026-10-15T10-00-00-other-path.jsonl", [spawn_meta(agent_path="/root/other"), turn("gpt-5.6-luna", "xhigh")])

        # When
        code_parent, status_parent = self.verify()
        code_path, status_path = self.verify(agent_path="/root/missing")

        # Then
        self.assertEqual(4, code_parent)
        self.assertIsNone(status_parent["rollout"])
        self.assertEqual(4, code_path)
        self.assertIsNone(status_path["rollout"])

    def test_session_meta가_첫_줄이_아니면_spawn된_rollout으로_보지_않는다(self):
        """thread_spawn 정보가 첫 줄의 session_meta에 없으면 그 rollout은 맞는 spawn 증거가 아니다."""
        # Given
        self.write_rollout("rollout-2026-10-15T10-00-00-late.jsonl", [turn("gpt-5.6-luna", "xhigh"), spawn_meta()])

        # When
        code, status = self.verify()

        # Then
        self.assertEqual(4, code)
        self.assertIsNone(status["rollout"])

    def test_같은_경로로_다시_spawn되면_가장_최근_rollout으로_검증한다(self):
        """같은 agent 경로의 가장 최근 rollout이 결과를 정한다. 이전의 어긋난 rollout과 무관하게 최근 rollout이 기대값이면 통과한다."""
        # Given
        self.write_rollout("rollout-2026-10-15T10-00-00-first.jsonl", [spawn_meta(), turn("gpt-6-astra", "xhigh")])
        self.write_rollout("rollout-2026-10-15T11-00-00-second.jsonl", [spawn_meta(), turn("gpt-6.1-sol", "high")])

        # When
        code, status = self.verify(model="gpt-6.1-sol", effort="high")

        # Then
        self.assertEqual(0, code)
        self.assertTrue(status["rollout"].endswith("rollout-2026-10-15T11-00-00-second.jsonl"))

    def test_인자가_빠지면_종료_코드_2이고_JSON_한_줄로_알린다(self):
        """필수 인자가 없으면 검증하지 않고 종료 코드 2이며 상태 JSON 한 줄을 출력한다."""
        # When
        code, status = self.verify(omit="--effort")

        # Then
        self.assertEqual(2, code)
        self.assertEqual((False, None, 0), (status["verified"], status["rollout"], status["turns"]))
        self.assertIn("--effort", status["error"])

    def test_sandbox를_넘기면_모든_turn_context의_sandbox가_같아야_검증된다(self):
        """--sandbox를 주면 모든 turn_context의 sandbox_policy.type이 그 값과 같을 때만 종료 코드 0이다."""
        # Given
        self.write_rollout("rollout-2026-10-15T10-00-00-child.jsonl", [spawn_meta(), turn("gpt-5.6-luna", "xhigh", "read-only")])

        # When
        code, status = self.verify(sandbox="read-only")

        # Then
        self.assertEqual(0, code)
        self.assertEqual((True, None), (status["verified"], status["error"]))

    def test_sandbox가_다르거나_없는_turn_context가_있으면_종료_코드_4이다(self):
        """sandbox_policy.type이 요청과 다르거나 빠진 turn_context가 하나라도 있으면 종료 코드 4이다."""
        cases = [
            ([spawn_meta(), turn("gpt-5.6-luna", "xhigh", "workspace-write")], "workspace-write"),
            ([spawn_meta(), turn("gpt-5.6-luna", "xhigh", "read-only"), turn("gpt-5.6-luna", "xhigh")], "read-only"),
        ]
        for index, (lines, sandbox) in enumerate(cases):
            with self.subTest(index=index):
                # Given
                self.write_rollout("rollout-2026-10-15T10-00-00-child.jsonl", lines)

                # When
                code, status = self.verify(sandbox="read-only")

                # Then
                self.assertEqual(4, code)
                self.assertFalse(status["verified"])
                self.assertIn("sandbox", status["error"])

    def test_허용되지_않은_sandbox_값은_종료_코드_2이다(self):
        """--sandbox는 read-only 또는 workspace-write만 받고 그 밖의 값은 사용 오류로 종료 코드 2이다."""
        # Given
        self.write_rollout("rollout-2026-10-15T10-00-00-child.jsonl", [spawn_meta(), turn("gpt-5.6-luna", "xhigh", "read-only")])

        # When
        code, status = self.verify(sandbox="danger-full-access")

        # Then
        self.assertEqual(2, code)
        self.assertFalse(status["verified"])

    def test_빈_부모_스레드는_사용_오류이다(self):
        """부모 스레드 값이 빈 문자열이면 종료 코드 2이다."""
        # When
        code, status = self.verify(parent="")

        # Then
        self.assertEqual(2, code)
        self.assertFalse(status["verified"])


if __name__ == "__main__":
    unittest.main()
