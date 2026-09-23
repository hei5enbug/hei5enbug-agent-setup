from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "scripts" / "session_lifecycle.py"


class SessionLifecycleHookTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data_root = self.root / "orca data"
        self.env = {
            "PATH": os.defpath,
            "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
            "ORCA_USER_DATA_PATH": str(self.data_root),
            "ORCA_TERMINAL_HANDLE": "term_test-1234",
            "ORCA_WORKTREE_ID": "repo-test::/tmp/sample",
            "ORCA_TAB_ID": "tab-test",
            "ORCA_PANE_KEY": "tab-test:leaf-test",
        }

    def invoke(self, event: str, *, host: str = "claude", payload: dict[str, object] | None = None):
        env = dict(self.env)
        if host == "codex":
            env["PLUGIN_ROOT"] = str(REPO_ROOT)
        input_payload = payload or {
            "hook_event_name": event,
            "session_id": "session-test-1234",
            "cwd": "/tmp/sample",
        }
        return subprocess.run(
            [sys.executable, str(HOOK)],
            cwd=self.root,
            env=env,
            input=json.dumps(input_payload),
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )

    def registry(self) -> dict[str, object]:
        return json.loads((self.data_root / "plugin-session-refresh" / "registry-v1.json").read_text())

    def test_SessionStart에는_context와_lifecycle_훅이_모두_연결된다(self):
        """새 프로세스는 지침 로드와 세션 등록을 모두 실행한다."""
        # Given
        hooks = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text())

        # When
        commands = [item["command"] for group in hooks["hooks"]["SessionStart"] for item in group["hooks"]]

        # Then
        self.assertEqual(len(commands), 2)
        self.assertTrue(any("session_context.py" in command for command in commands))
        self.assertTrue(any("session_lifecycle.py" in command for command in commands))

    def test_세션시작에서_재개에_필요한_정보를_등록한다(self):
        """SessionStart에서 세션 재개에 필요한 최소 정보를 등록한다."""
        # Given
        event = {"hook_event_name": "SessionStart", "source": "startup", "session_id": "session-test-1234", "cwd": "/tmp/sample"}

        # When
        result = self.invoke("SessionStart", payload=event)

        # Then
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        record = self.registry()["sessions"]["claude:session-test-1234"]
        self.assertEqual(record["state"], "idle")
        self.assertEqual(record["terminal_handle"], "term_test-1234")
        self.assertEqual(record["tab_id"], "tab-test")
        self.assertEqual(record["leaf_id"], "leaf-test")
        self.assertEqual(record["worktree_id"], "repo-test::/tmp/sample")
        self.assertEqual(record["plugin_version"], "0.6.0")
        self.assertNotIn("prompt", record)

    def test_사용자_입력에서_세션을_busy로_기록하고_프롬프트를_저장하지_않는다(self):
        """사용자 입력을 시작하면 세션을 busy로 기록하고 프롬프트 본문은 저장하지 않는다."""
        # Given
        self.invoke("SessionStart")
        event = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "session-test-1234",
            "cwd": "/tmp/sample",
            "prompt": "private prompt sentinel",
        }

        # When
        result = self.invoke("UserPromptSubmit", payload=event)

        # Then
        self.assertEqual(result.returncode, 0, result.stderr)
        registry_text = (self.data_root / "plugin-session-refresh" / "registry-v1.json").read_text()
        self.assertNotIn("private prompt sentinel", registry_text)
        self.assertEqual(self.registry()["sessions"]["claude:session-test-1234"]["state"], "busy")

    def test_정상_턴_종료에서_Codex가_요구하는_JSON을_반환한다(self):
        """Codex 턴 종료 시 빈 JSON 응답과 idle 상태를 기록한다."""
        # Given
        self.invoke("SessionStart", host="codex")
        self.invoke("UserPromptSubmit", host="codex")

        # When
        result = self.invoke("Stop", host="codex")

        # Then
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})
        self.assertEqual(self.registry()["sessions"]["codex:session-test-1234"]["state"], "idle")

    def test_Claude_Stop에서_백그라운드_작업이_남으면_busy를_유지한다(self):
        """Claude Code의 응답이 끝나도 백그라운드 작업이 있으면 busy로 기록한다."""
        # Given
        self.invoke("SessionStart")
        event = {
            "hook_event_name": "Stop", "session_id": "session-test-1234", "cwd": "/tmp/sample",
            "background_tasks": [{"id": "task-1", "status": "running", "type": "shell"}], "session_crons": [],
        }

        # When
        result = self.invoke("Stop", payload=event)

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.registry()["sessions"]["claude:session-test-1234"]["state"], "busy")

    def test_Claude_Stop에서_예약된_작업이_남으면_busy를_유지한다(self):
        """Claude Code에 예약된 재실행이 있으면 세션을 idle로 인증하지 않는다."""
        # Given
        self.invoke("SessionStart")
        event = {
            "hook_event_name": "Stop", "session_id": "session-test-1234", "cwd": "/tmp/sample",
            "background_tasks": [], "session_crons": [{"id": "cron-1"}],
        }

        # When
        result = self.invoke("Stop", payload=event)

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.registry()["sessions"]["claude:session-test-1234"]["state"], "busy")

    def test_Claude_Stop에서_작업_목록이_비어야_idle이_된다(self):
        """두 작업 목록이 모두 비어 있을 때만 Claude Code를 idle로 기록한다."""
        # Given
        self.invoke("SessionStart")
        event = {
            "hook_event_name": "Stop", "session_id": "session-test-1234", "cwd": "/tmp/sample",
            "background_tasks": [], "session_crons": [],
        }

        # When
        result = self.invoke("Stop", payload=event)

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.registry()["sessions"]["claude:session-test-1234"]["state"], "idle")

    def test_Claude_Stop에서_작업_목록을_받지_못하면_idle로_인증하지_않는다(self):
        """훅 입력에 작업 상태가 없으면 Claude Code 세션을 busy로 유지한다."""
        # Given
        self.invoke("SessionStart")
        event = {"hook_event_name": "Stop", "session_id": "session-test-1234", "cwd": "/tmp/sample"}

        # When
        result = self.invoke("Stop", payload=event)

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.registry()["sessions"]["claude:session-test-1234"]["state"], "busy")

    def test_자동_compact는_진행중인_턴을_idle로_바꾸지_않는다(self):
        """자동 compact의 SessionStart는 진행 중인 턴의 busy 상태를 유지한다."""
        # Given
        self.invoke("SessionStart")
        self.invoke("UserPromptSubmit")
        event = {"hook_event_name": "SessionStart", "source": "compact", "session_id": "session-test-1234", "cwd": "/tmp/sample"}

        # When
        result = self.invoke("SessionStart", payload=event)

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.registry()["sessions"]["claude:session-test-1234"]["state"], "busy")

    def test_세션종료에서_ended_상태를_기록한다(self):
        """세션이 종료되면 registry 상태를 ended로 갱신한다."""
        # Given
        self.invoke("SessionStart")

        # When
        result = self.invoke("SessionEnd")

        # Then
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.registry()["sessions"]["claude:session-test-1234"]["state"], "ended")

    def test_종료_훅이_누락되어도_같은_terminal의_새_세션이_옛_기록을_종료한다(self):
        """기존 SessionEnd가 누락되어도 새 세션이 같은 터미널의 유일한 live 소유자가 된다."""
        # Given
        self.invoke("SessionStart")
        self.invoke("UserPromptSubmit")
        new_event = {"hook_event_name": "SessionStart", "source": "clear", "session_id": "new-session-1234", "cwd": "/tmp/sample"}

        # When
        result = self.invoke("SessionStart", payload=new_event)

        # Then
        self.assertEqual(result.returncode, 0)
        sessions = self.registry()["sessions"]
        self.assertEqual(sessions["claude:session-test-1234"]["state"], "ended")
        self.assertEqual(sessions["claude:new-session-1234"]["state"], "idle")

    def test_활성_거래중에는_새_prompt를_차단한다(self):
        """활성 update transaction이 있으면 새 사용자 prompt를 차단한다."""
        # Given
        self.invoke("SessionStart")
        app_root = self.data_root / "plugin-session-refresh"
        transaction_id = "a" * 32
        receipt = app_root / "transactions" / transaction_id / "receipt.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps({"transaction_id": transaction_id, "state": "running"}))
        registry_path = app_root / "registry-v1.json"
        registry = json.loads(registry_path.read_text())
        registry["sessions"]["claude:session-test-1234"]["refresh_transaction_id"] = transaction_id
        registry_path.write_text(json.dumps(registry))

        # When
        result = self.invoke("UserPromptSubmit", payload={
            "hook_event_name": "UserPromptSubmit",
            "session_id": "session-test-1234",
            "cwd": "/tmp/sample",
            "prompt": "do not persist",
        })

        # Then
        output = json.loads(result.stdout)
        self.assertEqual(output["decision"], "block")
        self.assertNotIn("do not persist", registry_path.read_text())
        self.assertEqual(self.registry()["sessions"]["claude:session-test-1234"]["state"], "idle")

    def test_거래중에도_worker가_보내는_종료명령은_허용한다(self):
        """update transaction 중에도 worker의 종료 명령은 통과시킨다."""
        # Given
        self.invoke("SessionStart")
        app_root = self.data_root / "plugin-session-refresh"
        transaction_id = "b" * 32
        receipt = app_root / "transactions" / transaction_id / "receipt.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps({"transaction_id": transaction_id, "state": "running"}))
        registry_path = app_root / "registry-v1.json"
        registry = json.loads(registry_path.read_text())
        registry["sessions"]["claude:session-test-1234"]["refresh_transaction_id"] = transaction_id
        registry_path.write_text(json.dumps(registry))

        # When
        result = self.invoke("UserPromptSubmit", payload={
            "hook_event_name": "UserPromptSubmit",
            "session_id": "session-test-1234",
            "cwd": "/tmp/sample",
            "prompt": "/exit",
        })

        # Then
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.registry()["sessions"]["claude:session-test-1234"]["state"], "busy")

    def test_거래_영수증을_읽을_수_없으면_lease를_유지하고_prompt를_차단한다(self):
        """손상된 영수증은 거래 종료 증거가 아니므로 새 입력을 차단한다."""
        # Given
        self.invoke("SessionStart")
        app_root = self.data_root / "plugin-session-refresh"
        transaction_id = "c" * 32
        registry_path = app_root / "registry-v1.json"
        registry = json.loads(registry_path.read_text())
        registry["sessions"]["claude:session-test-1234"]["refresh_transaction_id"] = transaction_id
        registry_path.write_text(json.dumps(registry))
        receipt = app_root / "transactions" / transaction_id / "receipt.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_text("not json")

        # When
        result = self.invoke("UserPromptSubmit")

        # Then
        self.assertEqual(json.loads(result.stdout)["decision"], "block")
        self.assertEqual(self.registry()["sessions"]["claude:session-test-1234"]["refresh_transaction_id"], transaction_id)

    def test_registry가_손상되면_prompt를_차단한다(self):
        """세션 registry를 읽지 못하면 새 입력을 통과시키지 않는다."""
        # Given
        self.invoke("SessionStart")
        registry_path = self.data_root / "plugin-session-refresh" / "registry-v1.json"
        registry_path.write_text("not json")

        # When
        result = self.invoke("UserPromptSubmit")

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["decision"], "block")

    def test_Orca_환경이_없으면_세션_정보를_저장하지_않는다(self):
        """Orca 환경 밖에서는 lifecycle hook이 세션 정보를 기록하지 않는다."""
        # Given
        env = {"PATH": os.defpath, "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)}

        # When
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            env=env,
            input=json.dumps({"hook_event_name": "SessionStart", "session_id": "session-test", "cwd": "/tmp"}),
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertFalse(self.data_root.exists())

    def test_동시_세션_이벤트가_registry를_손상시키지_않는다(self):
        """동시 lifecycle 이벤트가 registry의 모든 세션 기록을 보존한다."""
        # Given
        session_ids = [f"session-{index:02d}" for index in range(12)]

        # When
        def start(session_id: str):
            payload = {"hook_event_name": "SessionStart", "session_id": session_id, "cwd": "/tmp/sample"}
            return subprocess.run(
                [sys.executable, str(HOOK)],
                env=self.env,
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(start, session_ids))

        # Then
        self.assertTrue(all(result.returncode == 0 for result in results))
        self.assertEqual(len(self.registry()["sessions"]), len(session_ids))

    def test_registry와_잠금파일은_사용자만_읽을_수_있다(self):
        """registry와 잠금 파일은 사용자 전용 권한으로 생성한다."""
        # Given
        self.invoke("SessionStart")
        app_root = self.data_root / "plugin-session-refresh"

        # When
        registry_mode = (app_root / "registry-v1.json").stat().st_mode & 0o777
        lock_mode = (app_root / ".registry.lock").stat().st_mode & 0o777
        directory_mode = app_root.stat().st_mode & 0o777

        # Then
        self.assertEqual(registry_mode, 0o600)
        self.assertEqual(lock_mode, 0o600)
        self.assertEqual(directory_mode, 0o700)


if __name__ == "__main__":
    unittest.main()
