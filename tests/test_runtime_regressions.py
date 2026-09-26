from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import orca_plugin_refresh as refresh
import session_lifecycle as lifecycle
from orca_refresh_fixture import OrcaRefreshFixture

SPEC = importlib.util.spec_from_file_location("session_context_regression", SCRIPTS / "session_context.py")
context = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(context)


class RegistryRegressionTest(unittest.TestCase):
    def test_unchanged_reads_do_not_write(self):
        """변경 없는 조회는 상태를 보존하고 디스크에 다시 저장하지 않는다."""
        # Given
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with lifecycle.registry_lock(root) as registry:
                registry["sessions"]["codex:test"] = {"state": "idle"}
            writer = lifecycle._write_json_atomic
            # When
            with patch.object(lifecycle, "_write_json_atomic", wraps=writer) as writes:
                snapshots = [refresh.registry_sessions(root) for _ in range(5)]
            # Then
            writes.assert_not_called()
            self.assertEqual(snapshots, [{"codex:test": {"state": "idle"}}] * 5)

    def test_nested_mutation_is_saved(self):
        """중첩 세션 상태가 바뀌면 변경 내용을 저장한다."""
        # Given
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with lifecycle.registry_lock(root) as registry:
                registry["sessions"]["codex:test"] = {"state": "idle"}
            # When
            with lifecycle.registry_lock(root) as registry:
                registry["sessions"]["codex:test"]["state"] = "busy"
            # Then
            self.assertEqual(refresh.registry_sessions(root)["codex:test"]["state"], "busy")

    def test_naive_timestamp_does_not_break_registry(self):
        """시간대가 없는 과거 기록은 다른 세션의 상태 저장을 방해하지 않는다."""
        # Given
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # When
            with lifecycle.registry_lock(root) as registry:
                registry["sessions"]["old"] = {"state": "ended", "updated_at": "2000-01-01T00:00:00"}
            # Then
            self.assertIn("old", refresh.registry_sessions(root))

    def test_concurrent_explorer_creation_keeps_user_file(self):
        """설정 파일이 확인 직후 생성되어도 사용자 내용을 덮어쓰지 않는다."""
        # Given
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "standalone-agents" / "codex-explorer.toml"
            source.parent.mkdir()
            source.write_text('name = "bundled"')
            home = root / "home"
            target = home / "agents" / "explorer.toml"
            target.parent.mkdir(parents=True)
            real_read = Path.read_text

            def racing_read(path, *args, **kwargs):
                if path == source:
                    target.write_text('name = "user"')
                return real_read(path, *args, **kwargs)

            # When
            with patch.dict(context.os.environ, {"CODEX_HOME": str(home)}), patch.object(Path, "read_text", racing_read):
                context.provision_codex_explorer(root)
            # Then
            self.assertEqual(target.read_text(), 'name = "user"')


class RefreshRegressionTest(OrcaRefreshFixture):
    def test_unknown_draft_blocks_preview(self):
        """미전송 입력 유무를 확인하지 못하면 재시작 계획을 차단한다."""
        # Given
        # When
        with patch.object(refresh, "terminal_has_draft", return_value=None):
            plan = refresh.create_plan(self.app_root)
        # Then
        self.assertFalse(plan["eligible"])
        self.assertIn("session_draft_unknown", {item["code"] for item in plan["blockers"]})

    def test_draft_read_failure_blocks_preview(self):
        """입력 상태 조회 오류를 입력이 없는 상태로 처리하지 않는다."""
        # Given
        error = refresh.RefreshError("command_timeout", "timeout")
        # When
        with patch.object(refresh, "terminal_has_draft", side_effect=error):
            plan = refresh.create_plan(self.app_root)
        # Then
        self.assertFalse(plan["eligible"])
        self.assertIn("command_timeout", {item["code"] for item in plan["blockers"]})

    def test_unknown_draft_blocks_apply(self):
        """계획 이후 입력 상태가 불명확해지면 worker를 시작하지 않는다."""
        # Given
        plan = refresh.create_plan(self.app_root)
        # When
        with patch.object(refresh, "terminal_has_draft", return_value=None), patch.object(refresh.subprocess, "Popen") as start:
            with self.assertRaises(refresh.RefreshError) as caught:
                refresh.apply_plan(self.app_root, plan["plan_id"])
        # Then
        self.assertEqual(caught.exception.code, "session_draft_unknown")
        start.assert_not_called()

    def test_failed_plan_save_releases_leases(self):
        """계획 저장이 실패하면 worker 없이 남은 세션 잠금을 해제한다."""
        # Given
        plan = refresh.create_plan(self.app_root)
        writer = refresh.write_json

        def fail_plan(path, payload):
            if path.parent.name == "plans":
                raise OSError("disk full")
            return writer(path, payload)

        # When
        with patch.object(refresh, "write_json", side_effect=fail_plan), patch.object(refresh.subprocess, "Popen") as start:
            with self.assertRaises(refresh.RefreshError):
                refresh.apply_plan(self.app_root, plan["plan_id"])
        # Then
        start.assert_not_called()
        self.assertTrue(all("refresh_transaction_id" not in record for record in refresh.registry_sessions(self.app_root).values()))
        receipt = next((self.app_root / "transactions").glob("*/receipt.json"))
        self.assertEqual(json.loads(receipt.read_text())["state"], "failed")

    def test_recovery_checks_receipt_after_lock(self):
        """복구 잠금을 얻기 전에 완료된 거래를 복구 상태로 덮어쓰지 않는다."""
        # Given
        transaction_id = "9" * 32
        receipt = refresh._make_receipt({"sessions": []}, transaction_id)
        receipt["updated_at"] = (refresh.utc_now() - timedelta(minutes=2)).isoformat()
        refresh._save_receipt(self.app_root, receipt)
        original_lock = refresh.file_lock

        @contextmanager
        def completing_lock(*args, **kwargs):
            receipt["state"] = "complete"
            refresh._save_receipt(self.app_root, receipt)
            with original_lock(*args, **kwargs):
                yield

        # When
        with patch.object(refresh, "file_lock", completing_lock):
            with self.assertRaises(refresh.RefreshError) as caught:
                refresh.recover_transaction(self.app_root, transaction_id, confirmed=True)
        # Then
        self.assertEqual(caught.exception.code, "transaction_not_active")
        self.assertEqual(refresh._load_receipt(self.app_root, transaction_id)["state"], "complete")

    def test_naive_plan_timestamp_is_rejected(self):
        """시간대 없는 만료 시각은 예외 traceback 없이 거부한다."""
        # Given
        plan = refresh.create_plan(self.app_root)
        plan["expires_at"] = "2099-01-01T00:00:00"
        plan["plan_hash"] = refresh._plan_hash(plan)
        refresh.write_json(refresh.plan_path(self.app_root, plan["plan_id"]), plan)
        # When
        with self.assertRaises(refresh.RefreshError) as caught:
            refresh.load_plan(self.app_root, plan["plan_id"])
        # Then
        self.assertEqual(caught.exception.code, "plan_expired")

    def test_late_end_does_not_replace_resumed_handle(self):
        """이전 터미널의 늦은 종료 이벤트는 재개한 세션을 덮어쓰지 않는다."""
        # Given
        key = "codex:session-leaf-init"
        with lifecycle.registry_lock(self.app_root) as registry:
            registry["sessions"][key]["terminal_handle"] = "replacement"
        event = {"hook_event_name": "SessionEnd", "session_id": "session-leaf-init", "cwd": "/tmp/init"}
        # When
        result = lifecycle.handle_event(event)
        # Then
        self.assertEqual(result, 0)
        record = refresh.registry_sessions(self.app_root)[key]
        self.assertEqual(record["terminal_handle"], "replacement")
        self.assertEqual(record["state"], "idle")
