from __future__ import annotations

import os
import json
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from unittest.mock import patch

ROOT_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(ROOT_SCRIPTS))
import orca_plugin_refresh as refresh
from session_lifecycle import registry_lock
from orca_refresh_fixture import OrcaRefreshFixture


class OrcaPluginRefreshTest(OrcaRefreshFixture):
    def test_계획이_두_호스트와_등록된_세션을_모두_미리보기한다(self):
        """계획 미리보기에는 두 호스트와 등록된 세션이 모두 포함된다."""
        # Given
        plan = refresh.create_plan(self.app_root)

        # When
        output = refresh.plan_output(plan)

        # Then
        self.assertTrue(output["ok"], output["blockers"])
        self.assertEqual(output["target_versions"], {"codex": "0.6.0", "claude": "0.6.0"})
        self.assertEqual(len(output["sessions"]), 2)
        self.assertTrue(plan["needs_plugin_update"])
        self.assertTrue(plan["needs_session_restart"])
        self.assertNotIn("session_id", output["sessions"][0])

    def test_미등록_agent_terminal이_있으면_계획을_차단한다(self):
        """registry에 없는 agent terminal이 있으면 계획을 차단한다."""
        # Given
        unregistered = self.terminal("claude", "term-new", "repo-new::/tmp/new", "/tmp/new", "tab-new", "leaf-new")
        self.terminals.append(unregistered)

        # When
        plan = refresh.create_plan(self.app_root)

        # Then
        self.assertFalse(plan["eligible"])
        self.assertIn("session_unregistered", {item["code"] for item in plan["blockers"]})

    def test_기록된_프로세스와_다른_incarnation은_계획을_차단한다(self):
        """같은 handle이 재사용돼도 등록된 native session과 다른 프로세스를 대상으로 삼지 않는다."""
        # Given
        with registry_lock(self.app_root) as registry:
            registry["sessions"]["claude:session-leaf-other"]["incarnation_id"] = "old-incarnation"

        # When
        plan = refresh.create_plan(self.app_root)

        # Then
        self.assertFalse(plan["eligible"])
        self.assertIn("session_unregistered", {item["code"] for item in plan["blockers"]})

    def test_다른_세션이_busy이면_계획을_차단한다(self):
        """개시 세션이 아닌 다른 세션이 busy이면 계획을 차단한다."""
        # Given
        self.register(self.terminals[1], state="busy", last_event="UserPromptSubmit")

        # When
        plan = refresh.create_plan(self.app_root)

        # Then
        self.assertFalse(plan["eligible"])
        self.assertIn("session_busy", {item["code"] for item in plan["blockers"]})

    def test_마켓플레이스_버전이_계획_후_바뀌면_apply가_아무것도_실행하지_않는다(self):
        """계획 뒤 마켓플레이스 버전이 바뀌면 외부 명령 전에 적용을 중단한다."""
        # Given
        plan = refresh.create_plan(self.app_root)
        self.versions["claude"]["catalog_version"] = "0.6.1"
        command_runner = patch.object(refresh, "run_command")
        popen = patch.object(refresh.subprocess, "Popen")
        mocked_command = command_runner.start()
        mocked_popen = popen.start()
        self.addCleanup(command_runner.stop)
        self.addCleanup(popen.stop)

        # When
        with self.assertRaises(refresh.RefreshError) as caught:
            refresh.apply_plan(self.app_root, plan["plan_id"])

        # Then
        self.assertEqual(caught.exception.code, "stale_plan")
        mocked_command.assert_not_called()
        mocked_popen.assert_not_called()

    def test_승인된_apply는_worker를_분리하고_각_세션에_lease를_건다(self):
        """승인된 적용은 worker를 분리하고 대상 세션에 lease를 기록한다."""
        # Given
        plan = refresh.create_plan(self.app_root)
        popen = patch.object(refresh.subprocess, "Popen")
        mocked_popen = popen.start()
        self.addCleanup(popen.stop)

        # When
        result = refresh.apply_plan(self.app_root, plan["plan_id"])

        # Then
        self.assertEqual(result["state"], "queued")
        mocked_popen.assert_called_once()
        records = refresh.registry_sessions(self.app_root)
        self.assertEqual(records["codex:session-leaf-init"]["refresh_transaction_id"], result["transaction_id"])
        self.assertEqual(records["claude:session-leaf-other"]["refresh_transaction_id"], result["transaction_id"])

    def test_마켓플레이스_루트가_계획_뒤_바뀌면_apply를_거부한다(self):
        """마켓플레이스 루트가 계획 뒤 달라지면 외부 명령 전에 적용을 거부한다."""
        # Given
        plan = refresh.create_plan(self.app_root)
        original = self.versions["codex"]["root"]
        self.versions["codex"]["root"] = str(self.root / "unexpected")
        popen = patch.object(refresh.subprocess, "Popen")
        mocked_popen = popen.start()
        self.addCleanup(popen.stop)

        # When
        with self.assertRaises(refresh.RefreshError) as caught:
            refresh.apply_plan(self.app_root, plan["plan_id"])

        # Then
        self.assertEqual(caught.exception.code, "stale_plan")
        self.assertNotEqual(self.versions["codex"]["root"], original)
        mocked_popen.assert_not_called()

    def test_같은_초에_다른_세션의_턴이_끝나도_기존_계획을_거부한다(self):
        """타임스탬프가 같아도 lifecycle 순번이 바뀌면 새 계획을 요구한다."""
        # Given
        plan = refresh.create_plan(self.app_root)
        with registry_lock(self.app_root) as registry:
            record = registry["sessions"]["claude:session-leaf-other"]
            record["event_sequence"] += 1

        # When
        with patch.object(refresh.subprocess, "Popen") as popen:
            with self.assertRaises(refresh.RefreshError) as caught:
                refresh.apply_plan(self.app_root, plan["plan_id"])

        # Then
        self.assertEqual(caught.exception.code, "stale_plan")
        popen.assert_not_called()

    def test_worker가_시작전에_plan을_잃으면_실패_영수증과_lease_해제를_남긴다(self):
        """분리된 worker가 계획을 읽지 못해도 거래를 실패로 마무리한다."""
        # Given
        plan = refresh.create_plan(self.app_root)
        with patch.object(refresh.subprocess, "Popen"):
            queued = refresh.apply_plan(self.app_root, plan["plan_id"])
        refresh.plan_path(self.app_root, plan["plan_id"]).unlink()

        # When
        result = refresh._run_worker(self.app_root, queued["transaction_id"])

        # Then
        receipt = refresh._load_receipt(self.app_root, queued["transaction_id"])
        self.assertEqual(result, 1)
        self.assertEqual(receipt["state"], "failed")
        records = refresh.registry_sessions(self.app_root)
        self.assertTrue(all("refresh_transaction_id" not in record for record in records.values()))

    def test_개시_턴이_끝나기_전에는_marketplace를_갱신하지_않는다(self):
        """개시 세션의 Stop을 기다려 기존 훅이 남아 있을 때 상태를 확정한다."""
        # Given
        plan = refresh.create_plan(self.app_root)
        with patch.object(refresh.subprocess, "Popen"):
            queued = refresh.apply_plan(self.app_root, plan["plan_id"])
        with registry_lock(self.app_root) as registry:
            registry["sessions"]["codex:session-leaf-init"]["state"] = "busy"
            registry["sessions"]["codex:session-leaf-init"]["last_event"] = "UserPromptSubmit"

        # When
        with patch.object(refresh, "_wait_session_idle", side_effect=refresh.RefreshError("session_not_idle", "still busy")), patch.object(refresh, "run_command") as commands:
            result = refresh._run_worker(self.app_root, queued["transaction_id"])

        # Then
        self.assertEqual(result, 1)
        commands.assert_not_called()
        self.assertEqual(refresh._load_receipt(self.app_root, queued["transaction_id"])["state"], "failed")

    def test_Codex_업데이트가_실패하면_Claude의_갱신된_버전을_영수증에_남긴다(self):
        """두 host 중 하나만 갱신되어도 확인된 설치 버전을 보존한다."""
        # Given
        transaction_id = "6" * 32
        receipt = refresh._make_receipt({"plan_id": "7" * 32, "sessions": []}, transaction_id)
        refresh._save_receipt(self.app_root, receipt)
        installed = {"codex": "0.5.2", "claude": "0.5.2"}

        def fake_run(argv, *, timeout=30.0, check=True):
            command = list(argv)
            if command[:3] == ["claude", "plugin", "update"]:
                installed["claude"] = "0.6.0"
                return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")
            if command[:3] == ["codex", "plugin", "add"]:
                raise refresh.RefreshError("command_failed", "Codex update failed.")
            self.fail(f"unexpected command: {command}")

        # When
        with patch.object(refresh, "_installed_versions", side_effect=lambda: dict(installed)), patch.object(refresh, "run_command", side_effect=fake_run):
            with self.assertRaises(refresh.RefreshError) as caught:
                refresh._update_plugins(self.app_root, receipt, {"codex": "0.6.0", "claude": "0.6.0"})

        # Then
        self.assertEqual(caught.exception.code, "command_failed")
        saved = refresh._load_receipt(self.app_root, transaction_id)
        self.assertEqual(saved["installed_versions"], {"codex": "0.5.2", "claude": "0.6.0"})

    def test_Claude의_marketplace_command는_자동_승인하지_않는다(self):
        """Claude Code가 별도 marketplace command 승인을 요구하면 worker를 멈춘다."""
        # Given
        transaction_id = "c" * 32
        receipt = refresh._make_receipt({"plan_id": "d" * 32, "sessions": []}, transaction_id)
        result = subprocess.CompletedProcess(
            ["claude", "plugin", "update"],
            1,
            stdout=json.dumps({"shownCommand": {"sha256": "e" * 64, "command": "private-command"}}),
            stderr="",
        )

        # When
        with patch.object(refresh, "run_command", return_value=result):
            refresh._claude_update(self.app_root, receipt, "0.6.0")

        # Then
        self.assertEqual(receipt["state"], "needs_manual_command")
        self.assertEqual(receipt["manual_action"]["command_sha256"], "e" * 64)
        saved = refresh._load_receipt(self.app_root, transaction_id)
        self.assertNotIn("private-command", json.dumps(saved))

    def test_명시한_Claude_command_hash만_승인한다(self):
        """사용자가 승인한 Claude marketplace command hash만 update에 전달한다."""
        # Given
        command_hash = "f" * 64
        receipt = {"claude_command_hash": command_hash}
        observed: list[list[str]] = []

        def fake_run(argv, *, timeout=30.0, check=True):
            observed.append(list(argv))
            return subprocess.CompletedProcess(list(argv), 0, stdout="{}", stderr="")

        # When
        with patch.object(refresh, "run_command", side_effect=fake_run):
            refresh._claude_update(self.app_root, receipt, "0.6.0")

        # Then
        self.assertIn("--accept-command", observed[0])
        self.assertEqual(observed[0][observed[0].index("--accept-command") + 1], command_hash)

    def test_fresh_plan은_pending_command와_일치하는_hash만_받는다(self):
        """새 계획은 pending receipt의 정확한 command hash만 승인한다."""
        # Given
        plan = refresh.create_plan(self.app_root)
        parent_id = "3" * 32
        command_hash = "4" * 64
        parent = refresh._make_receipt(plan, parent_id)
        parent["state"] = "needs_manual_command"
        parent["manual_action"] = {
            "kind": "claude_marketplace_command_approval",
            "plugin": refresh.PLUGIN_NAME,
            "marketplace": refresh.MARKETPLACE_NAME,
            "command_sha256": command_hash,
        }
        refresh._save_receipt(self.app_root, parent)
        popen = patch.object(refresh.subprocess, "Popen")
        mocked_popen = popen.start()
        self.addCleanup(popen.stop)

        # When
        result = refresh.apply_plan(self.app_root, plan["plan_id"], accept_command=command_hash)

        # Then
        self.assertEqual(result["state"], "queued")
        mocked_popen.assert_called_once()
        receipt = refresh._load_receipt(self.app_root, result["transaction_id"])
        self.assertEqual(receipt["claude_command_hash"], command_hash)
        self.assertEqual(receipt["parent_transaction_id"], parent_id)

    def test_update_실패에서는_어떤_세션도_종료하지_않는다(self):
        """plugin update가 실패하면 세션을 종료하지 않고 lease를 해제한다."""
        # Given
        plan = refresh.create_plan(self.app_root)
        with patch.object(refresh.subprocess, "Popen"):
            queued = refresh.apply_plan(self.app_root, plan["plan_id"])
        transaction_id = queued["transaction_id"]
        with registry_lock(self.app_root) as registry:
            initiator = registry["sessions"]["codex:session-leaf-init"]
            initiator["state"] = "idle"
            initiator["last_event"] = "Stop"
        commands: list[list[str]] = []

        def fail_claude_update(argv, *, timeout=30.0, check=True):
            command = list(argv)
            commands.append(command)
            if command[:3] == ["claude", "plugin", "update"]:
                return subprocess.CompletedProcess(command, 2, stdout="not-json", stderr="ignored")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        # When
        with patch.object(refresh, "run_command", side_effect=fail_claude_update):
            result = refresh._run_worker(self.app_root, transaction_id)

        # Then
        receipt = refresh._load_receipt(self.app_root, transaction_id)
        self.assertEqual(result, 1)
        self.assertEqual(receipt["state"], "failed")
        self.assertFalse(any(command[1:3] == ["terminal", "send"] for command in commands))
        records = refresh.registry_sessions(self.app_root)
        self.assertNotIn("refresh_transaction_id", records["codex:session-leaf-init"])
        self.assertNotIn("refresh_transaction_id", records["claude:session-leaf-other"])

    def test_worker_lock이_유지되는_동안_복구하지_않는다(self):
        """worker lock이 잡혀 있으면 수동 복구를 거부한다."""
        # Given
        transaction_id = "f" * 32
        receipt = refresh._make_receipt({"plan_id": "e" * 32, "sessions": []}, transaction_id)
        receipt["state"] = "running"
        receipt["updated_at"] = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
        refresh._save_receipt(self.app_root, receipt)
        worker_lock = refresh.transaction_directory(self.app_root, transaction_id) / ".worker.lock"

        # When
        with refresh.file_lock(worker_lock):
            with self.assertRaises(refresh.RefreshError) as caught:
                refresh.recover_transaction(self.app_root, transaction_id, confirmed=True)

        # Then
        self.assertEqual(caught.exception.code, "worker_active")
        self.assertEqual(refresh._load_receipt(self.app_root, transaction_id)["state"], "running")

    def test_수동_복구는_해당_transaction의_lease만_해제한다(self):
        """수동 복구는 worker가 멈춘 뒤 해당 transaction lease만 해제한다."""
        # Given
        transaction_id = "1" * 32
        receipt = refresh._make_receipt({"plan_id": "2" * 32, "sessions": []}, transaction_id)
        receipt["state"] = "running"
        receipt["updated_at"] = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
        refresh._save_receipt(self.app_root, receipt)
        with registry_lock(self.app_root) as registry:
            for record in registry["sessions"].values():
                record["refresh_transaction_id"] = transaction_id
        terminal_list = patch.object(refresh, "terminal_inventory", return_value=[dict(item) for item in self.terminals])
        wait = patch.object(refresh, "wait_terminal", return_value=True)
        terminal_list.start()
        wait.start()
        self.addCleanup(terminal_list.stop)
        self.addCleanup(wait.stop)

        # When
        result = refresh.recover_transaction(self.app_root, transaction_id, confirmed=True)

        # Then
        self.assertEqual(result["state"], "recovered")
        records = refresh.registry_sessions(self.app_root)
        self.assertTrue(all("refresh_transaction_id" not in record for record in records.values()))

    def test_복구중_handle이_바뀌면_살아있는_세션을_ended로_표시하지_않는다(self):
        """Orca 재시작 후 handle이 바뀐 세션은 확인 전까지 busy로 남긴다."""
        # Given
        transaction_id = "8" * 32
        receipt = refresh._make_receipt({"plan_id": "9" * 32, "sessions": []}, transaction_id)
        receipt["state"] = "running"
        receipt["updated_at"] = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
        refresh._save_receipt(self.app_root, receipt)
        with registry_lock(self.app_root) as registry:
            registry["sessions"]["claude:session-leaf-other"]["refresh_transaction_id"] = transaction_id
        replacement = dict(self.terminals[1], terminal_handle="term-replacement")

        # When
        with patch.object(refresh, "terminal_inventory", return_value=[replacement]):
            result = refresh.recover_transaction(self.app_root, transaction_id, confirmed=True)

        # Then
        record = refresh.registry_sessions(self.app_root)["claude:session-leaf-other"]
        self.assertEqual(record["state"], "busy")
        saved = refresh._load_receipt(self.app_root, transaction_id)
        self.assertEqual(saved["recovered_sessions"][0]["verification"], "terminal_identity_unverified")
        self.assertEqual(result["state"], "recovered")

    def test_복구중_같은_handle을_다른_프로세스가_쓰면_idle로_표시하지_않는다(self):
        """handle이 같아도 프로세스 incarnation이 달라지면 세션 신원을 확인하지 않는다."""
        # Given
        transaction_id = "a" * 32
        receipt = refresh._make_receipt({"plan_id": "b" * 32, "sessions": []}, transaction_id)
        receipt["state"] = "running"
        receipt["updated_at"] = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
        refresh._save_receipt(self.app_root, receipt)
        with registry_lock(self.app_root) as registry:
            record = registry["sessions"]["claude:session-leaf-other"]
            record["refresh_transaction_id"] = transaction_id
            record["incarnation_id"] = "old-incarnation"

        # When
        with patch.object(refresh, "terminal_inventory", return_value=[dict(self.terminals[1])]):
            refresh.recover_transaction(self.app_root, transaction_id, confirmed=True)

        # Then
        record = refresh.registry_sessions(self.app_root)["claude:session-leaf-other"]
        self.assertEqual(record["state"], "busy")

    def test_Orca가_잘린_terminal_목록을_주면_적용하지_않는다(self):
        # Given
        response = {"result": {"terminals": [], "totalCount": 2, "truncated": True}}
        runner = patch.object(refresh, "run_json", return_value=response)
        self.inventory_patch.stop()
        runner.start()
        self.addCleanup(runner.stop)

        # When
        with self.assertRaises(refresh.RefreshError) as caught:
            refresh.terminal_inventory()

        # Then
        self.assertEqual(caught.exception.code, "terminal_list_truncated")

    def test_Orca가_프로세스_incarnation을_주지_않으면_대상_목록을_거부한다(self):
        """프로세스 신원을 확인할 수 없는 Orca 응답으로는 세션을 종료하지 않는다."""
        # Given
        response = {"result": {"terminals": [{
            "agentIdentity": "claude", "handle": "term-other", "worktreeId": "repo-other::/tmp/other",
            "worktreePath": "/tmp/other", "connected": True, "writable": True,
        }], "totalCount": 1, "truncated": False}}
        self.inventory_patch.stop()

        # When
        with patch.object(refresh, "run_json", return_value=response):
            with self.assertRaises(refresh.RefreshError) as caught:
                refresh.terminal_inventory()

        # Then
        self.assertEqual(caught.exception.code, "terminal_incarnation_missing")

    def test_워크트리_경로가_빈_floating_agent_terminal이면_대상_목록을_거부한다(self):
        """워크트리가 없는 floating agent terminal을 스크립트 실행 위치의 워크트리로 오인하지 않는다."""
        # Given
        response = {"result": {"terminals": [{
            "agentIdentity": "claude", "handle": "term-floating", "incarnationId": "incarnation-floating",
            "worktreeId": "global-floating-terminal", "worktreePath": "", "connected": True, "writable": True,
        }], "totalCount": 1, "truncated": False}}
        self.inventory_patch.stop()

        # When
        with patch.object(refresh, "run_json", return_value=response):
            with self.assertRaises(refresh.RefreshError) as caught:
                refresh.terminal_inventory()

        # Then
        self.assertEqual(caught.exception.code, "terminal_worktree_missing")

    def test_상대_경로_워크트리를_가진_agent_terminal이면_대상_목록을_거부한다(self):
        """실행 위치에 따라 달라지는 상대 경로를 세션의 워크트리로 받아들이지 않는다."""
        # Given
        response = {"result": {"terminals": [{
            "agentIdentity": "codex", "handle": "term-relative", "incarnationId": "incarnation-relative",
            "worktreeId": "repo-relative::relative/worktree", "worktreePath": "relative/worktree",
            "connected": True, "writable": True,
        }], "totalCount": 1, "truncated": False}}
        self.inventory_patch.stop()

        # When
        with patch.object(refresh, "run_json", return_value=response):
            with self.assertRaises(refresh.RefreshError) as caught:
                refresh.terminal_inventory()

        # Then
        self.assertEqual(caught.exception.code, "terminal_worktree_missing")

    def test_agent가_없는_floating_terminal은_건너뛰고_agent_terminal을_절대_경로로_고른다(self):
        """agent가 없는 floating shell은 대상에서 빼고 agent terminal은 절대 워크트리 경로로 선택한다."""
        # Given
        worktree = self.root / "worktree"
        worktree.mkdir()
        response = {"result": {"terminals": [
            {"handle": "term-shell", "incarnationId": "incarnation-shell",
             "worktreeId": "global-floating-terminal", "worktreePath": ""},
            {"agentIdentity": "claude", "handle": "term-other", "incarnationId": "incarnation-other",
             "worktreeId": f"repo-other::{worktree}", "worktreePath": str(worktree),
             "connected": True, "writable": True},
        ], "totalCount": 2, "truncated": False}}
        self.inventory_patch.stop()

        # When
        with patch.object(refresh, "run_json", return_value=response):
            terminals = refresh.terminal_inventory()

        # Then
        self.assertEqual([item["terminal_handle"] for item in terminals], ["term-other"])
        self.assertEqual(terminals[0]["worktree_path"], str(worktree.resolve()))

    def test_설치_목록의_marketplace와_scope를_확인한다(self):
        """설치 목록과 marketplace가 예상한 플러그인 소스를 가리키는지 확인한다."""
        # Given
        def fake_run_json(argv, *, timeout=30.0):
            command = list(argv)
            if command[:3] == ["codex", "plugin", "list"]:
                return {"installed": [self.codex_item], "available": []}
            if command[:4] == ["codex", "plugin", "marketplace", "list"]:
                return {"marketplaces": [{
                    "name": "hei5enbug",
                    "root": str(self.codex_root),
                    "marketplaceSource": {"sourceType": "git", "source": refresh.EXPECTED_REPO_URL},
                }]}
            if command[:3] == ["claude", "plugin", "list"]:
                return [self.claude_item]
            if command[:4] == ["claude", "plugin", "marketplace", "list"]:
                return [{"name": "hei5enbug", "repo": refresh.EXPECTED_CLAUDE_REPO, "installLocation": str(self.claude_root)}]
            self.fail(f"unexpected command: {command[:4]}")

        # When
        with patch.object(refresh, "run_json", side_effect=fake_run_json):
            codex_item, codex_snapshot = refresh.installed_plugins("codex")
            claude_item, claude_snapshot = refresh.installed_plugins("claude")

        # Then
        self.assertTrue(codex_item["enabled"])
        self.assertEqual(codex_snapshot["catalog_version"], "0.6.0")
        self.assertTrue(claude_item["enabled"])
        self.assertEqual(claude_snapshot["catalog_version"], "0.6.0")

    def test_다른_GitHub_marketplace를_자동으로_갱신하지_않는다(self):
        """설치 source가 다른 저장소를 가리키면 marketplace 갱신을 거부한다."""
        # Given
        def fake_run_json(argv, *, timeout=30.0):
            command = list(argv)
            if command[:3] == ["codex", "plugin", "list"]:
                item = dict(self.codex_item)
                item["marketplaceSource"] = {"sourceType": "git", "source": "https://example.invalid/other.git"}
                return {"installed": [item], "available": []}
            self.fail(f"unexpected command: {command[:4]}")

        # When
        with patch.object(refresh, "run_json", side_effect=fake_run_json):
            with self.assertRaises(refresh.RefreshError) as caught:
                refresh.installed_plugins("codex")

        # Then
        self.assertEqual(caught.exception.code, "codex_marketplace_mismatch")

    def test_새_handle의_tab과_pane이_같아도_기존_계획으로_재연결하지_않는다(self):
        """Orca 재시작으로 handle이 바뀌면 새 lifecycle 등록과 계획을 요구한다."""
        # Given
        session = {
            "host": "claude",
            "terminal_handle": "term-old",
            "worktree_id": "repo-other::/tmp/other",
            "tab_id": "tab-other",
            "leaf_id": "leaf-other",
        }
        replacement = dict(self.terminals[1], terminal_handle="term-new")

        # When
        with self.assertRaises(refresh.RefreshError) as caught:
            refresh._reconcile_terminal(session, [replacement])

        # Then
        self.assertEqual(caught.exception.code, "terminal_missing")

    def test_종료된_대화의_기록은_같은_terminal의_새_대화를_가리지_않는다(self):
        """같은 터미널에서 새 대화가 시작되면 종료된 기록을 live 후보에서 제외한다."""
        # Given
        terminal = dict(self.terminals[1])
        records = refresh.registry_sessions(self.app_root)
        records["claude:old-session"] = dict(records["claude:session-leaf-other"], state="ended", session_id="old-session")

        # When
        key, record, problem = refresh.session_record_for_terminal(terminal, records)

        # Then
        self.assertIsNone(problem)
        self.assertEqual(key, "claude:session-leaf-other")
        self.assertEqual(record["session_id"], "session-leaf-other")

    def test_다른_terminal_하나만_남아도_계획한_세션으로_대체하지_않는다(self):
        """계획한 터미널의 handle과 tab·pane이 모두 달라지면 종료 대상을 추측하지 않는다."""
        # Given
        session = dict(self.terminals[1], terminal_handle="term-old", tab_id="tab-old", leaf_id="leaf-old")
        unrelated = dict(self.terminals[1], terminal_handle="term-other", tab_id="tab-new", leaf_id="leaf-new")

        # When
        with self.assertRaises(refresh.RefreshError) as caught:
            refresh._reconcile_terminal(session, [unrelated])

        # Then
        self.assertEqual(caught.exception.code, "terminal_missing")

    def test_같은_handle이라도_프로세스_incarnation이_바뀌면_중단한다(self):
        """Orca가 handle을 다시 사용해도 다른 프로세스를 원래 세션으로 취급하지 않는다."""
        # Given
        session = dict(self.terminals[1])
        replacement = dict(session, incarnation_id="replacement-incarnation")

        # When
        with self.assertRaises(refresh.RefreshError) as caught:
            refresh._reconcile_terminal(session, [replacement])

        # Then
        self.assertEqual(caught.exception.code, "terminal_changed")

    def test_새_handle이_registry에_같은_세션으로_등록되지_않으면_중단한다(self):
        """tab·pane이 같아도 native session ID가 새 handle로 등록되지 않으면 종료하지 않는다."""
        # Given
        session = dict(self.terminals[1], registry_key="claude:session-leaf-other", session_id="session-leaf-other")
        replacement = dict(self.terminals[1], terminal_handle="term-replacement")
        transaction_id = "a" * 32
        with registry_lock(self.app_root) as registry:
            registry["sessions"]["claude:session-leaf-other"]["refresh_transaction_id"] = transaction_id
        receipt = {"transaction_id": transaction_id}

        # When
        with patch.object(refresh, "terminal_inventory", return_value=[replacement]):
            with self.assertRaises(refresh.RefreshError) as caught:
                refresh._wait_session_idle(self.app_root, session, timeout_seconds=1, receipt=receipt)

        # Then
        self.assertEqual(caught.exception.code, "terminal_missing")

    def test_lease_뒤에_다른_세션에서_새_턴이_기록되면_exit를_거부한다(self):
        """업데이트 도중 다른 세션의 lifecycle 순번이 바뀌면 종료하지 않는다."""
        # Given
        plan = refresh.create_plan(self.app_root)
        session = next(item for item in plan["sessions"] if item["host"] == "claude")
        transaction_id = "b" * 32
        with registry_lock(self.app_root) as registry:
            record = registry["sessions"]["claude:session-leaf-other"]
            record["refresh_transaction_id"] = transaction_id
            record["incarnation_id"] = session["incarnation_id"]
            record["event_sequence"] += 1

        # When
        with self.assertRaises(refresh.RefreshError) as caught:
            refresh._wait_session_idle(self.app_root, session, timeout_seconds=1, receipt={"transaction_id": transaction_id})

        # Then
        self.assertEqual(caught.exception.code, "stale_plan")

    def test_같은_버전의_marketplace_revision이_바뀌면_계획을_폐기한다(self):
        """버전 문자열이 같아도 marketplace 내용이 바뀌면 새 승인을 요구한다."""
        # Given
        plan = refresh.create_plan(self.app_root)
        self.versions["codex"]["catalog_revision"] = "c" * 40

        # When
        with self.assertRaises(refresh.RefreshError) as caught:
            refresh._check_catalog_after_refresh(plan)

        # Then
        self.assertEqual(caught.exception.code, "stale_plan")

    def test_marketplace_revision을_확인할_수_없으면_계획을_차단한다(self):
        """Git revision을 알 수 없는 marketplace는 업데이트 계획에 포함하지 않는다."""
        # Given
        self.versions["codex"]["catalog_revision"] = None

        # When
        plan = refresh.create_plan(self.app_root)

        # Then
        self.assertFalse(plan["eligible"])
        self.assertIn("catalog_revision_missing", {item["code"] for item in plan["blockers"]})

    def test_marketplace_복제본에_커밋되지_않은_변경이_있으면_revision을_신뢰하지_않는다(self):
        """같은 HEAD라도 marketplace 파일이 수정되었으면 승인 대상 내용을 확인할 수 없다고 본다."""
        # Given
        revision = subprocess.CompletedProcess(["git", "rev-parse"], 0, stdout="a" * 40 + "\n", stderr="")
        dirty = subprocess.CompletedProcess(["git", "status"], 0, stdout=" M skills/example/SKILL.md\n", stderr="")

        # When
        with patch.object(refresh, "run_command", side_effect=[revision, dirty]):
            result = refresh.git_revision(self.codex_root)

        # Then
        self.assertIsNone(result)

    def test_영수증이_없어도_기존_lease를_활성으로_취급한다(self):
        """기존 거래의 영수증을 읽을 수 없으면 새 거래가 lease를 덮어쓰지 않는다."""
        # Given
        with registry_lock(self.app_root) as registry:
            registry["sessions"]["claude:session-leaf-other"]["refresh_transaction_id"] = "a" * 32

        # When
        plan = refresh.create_plan(self.app_root)

        # Then
        self.assertFalse(plan["eligible"])
        self.assertIn("transaction_active", {item["code"] for item in plan["blockers"]})

    def test_resume_검증_실패시_수동_명령과_중복실행_주의를_남긴다(self):
        """새 터미널이 열린 뒤 resume이 실패하면 확인을 전제로 복구 명령을 남긴다."""
        # Given
        session = {
            "host": "claude", "cwd": "/tmp/other", "session_id": "session-leaf-other",
            "previous_terminal_closed": True, "new_terminal_handle": "term-new",
        }

        # When
        refresh._record_resume_recovery(session, "resume_hook_missing")

        # Then
        self.assertIn("claude --resume session-leaf-other", session["manual_resume_command"])
        self.assertTrue(session["manual_resume_requires_terminal_check"])

    def test_완료_알림은_Orca의_실제_send_구조와_턴_시작을_검사한다(self):
        """입력 수락만 확인되면 완료 알림을 전달 완료로 기록하지 않는다."""
        # Given
        accepted_only = {"result": {"send": {"accepted": True, "prompt": {"stages": ["input_accepted"]}}}}

        # When
        with patch.object(refresh, "run_json", return_value=accepted_only) as runner:
            status = refresh._notify_initiator("term-new", "a" * 32)

        # Then
        self.assertEqual(status, "complete_but_not_confirmed")
        self.assertIn("--wait-submit", runner.call_args.args[0])

    def test_Orca가_종료_입력을_거부하면_exit를_기다리지_않는다(self):
        """실제 send 영수증에서 accepted가 거짓이면 종료 성공으로 간주하지 않는다."""
        # Given
        rejected = {"result": {"send": {"accepted": False}}}

        # When
        with patch.object(refresh, "run_json", return_value=rejected), patch.object(refresh, "terminal_agent_running") as probe:
            with self.assertRaises(refresh.RefreshError) as caught:
                refresh._send_exit("term-other", "claude")

        # Then
        self.assertEqual(caught.exception.code, "input_not_accepted")
        probe.assert_not_called()

    def test_중복된_replacement_candidate도_종료_대상으로_선택하지_않는다(self):
        """tab·pane이 같은 터미널이 여럿 있어도 계획한 handle이 없으면 중단한다."""
        # Given
        session = {
            "host": "claude",
            "terminal_handle": "term-old",
            "worktree_id": "repo-other::/tmp/other",
            "tab_id": "tab-other",
            "leaf_id": "leaf-other",
        }
        candidates = [dict(self.terminals[1], terminal_handle="term-a"), dict(self.terminals[1], terminal_handle="term-b")]

        # When
        with self.assertRaises(refresh.RefreshError) as caught:
            refresh._reconcile_terminal(session, candidates)

        # Then
        self.assertEqual(caught.exception.code, "terminal_missing")

    def test_재개_명령은_원래_cwd와_native_ID를_사용한다(self):
        # Given
        session = {"host": "codex", "cwd": "/tmp/project with space", "session_id": "session-abc"}
        executable = patch.object(refresh, "executable", side_effect=lambda name: f"/bin/{name}")
        executable.start()
        self.addCleanup(executable.stop)

        # When
        command = refresh._resume_command(session)

        # Then
        self.assertEqual(command, ["/bin/codex", "-C", "/tmp/project with space", "resume", "session-abc"])

    def test_설치된_버전이_목표보다_높으면_계획을_다운그레이드하지_않는다(self):
        # Given
        self.versions["codex"]["installed_version"] = "0.7.0"

        # When
        plan = refresh.create_plan(self.app_root)

        # Then
        self.assertFalse(plan["eligible"])
        self.assertIn("downgrade_refused", {item["code"] for item in plan["blockers"]})


if __name__ == "__main__":
    unittest.main()
