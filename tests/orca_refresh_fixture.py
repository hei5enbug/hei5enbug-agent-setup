from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(ROOT_SCRIPTS))
import orca_plugin_refresh as refresh
from session_lifecycle import registry_lock, session_key


class OrcaRefreshFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app_root = self.root / "orca data" / "plugin-session-refresh"
        self.codex_root = self.root / "codex-marketplace"
        self.claude_root = self.root / "claude-marketplace"
        self.codex_root.mkdir()
        self.claude_root.mkdir()
        (self.codex_root / ".codex-plugin").mkdir()
        (self.claude_root / ".claude-plugin").mkdir()
        (self.codex_root / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "hei5enbug-agent-setup", "version": "0.6.0"})
        )
        (self.claude_root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "hei5enbug-agent-setup", "version": "0.6.0"})
        )
        self.codex_item = {
            "pluginId": "hei5enbug-agent-setup@hei5enbug",
            "name": "hei5enbug-agent-setup",
            "marketplaceName": "hei5enbug",
            "version": "0.5.2+codex.old",
            "enabled": True,
            "source": {"source": "local", "path": str(self.codex_root)},
            "marketplaceSource": {"sourceType": "git", "source": refresh.EXPECTED_REPO_URL},
        }
        self.claude_item = {
            "id": "hei5enbug-agent-setup@hei5enbug",
            "version": "0.5.2",
            "scope": "user",
            "enabled": True,
        }
        self.versions = {
            "codex": {
                "root": str(self.codex_root),
                "catalog_version": "0.6.0",
                "installed_version": "0.5.2",
                "catalog_revision": "a" * 40,
            },
            "claude": {
                "root": str(self.claude_root),
                "catalog_version": "0.6.0",
                "installed_version": "0.5.2",
                "catalog_revision": "b" * 40,
            },
        }
        self.terminals = [
            self.terminal("codex", "term-init", "repo-init::/tmp/init", "/tmp/init", "tab-init", "leaf-init"),
            self.terminal("claude", "term-other", "repo-other::/tmp/other", "/tmp/other", "tab-other", "leaf-other"),
        ]
        self.env = patch.dict(os.environ, {
            "ORCA_USER_DATA_PATH": str(self.root / "orca data"),
            "ORCA_TERMINAL_HANDLE": "term-init",
            "ORCA_TAB_ID": "tab-init",
            "ORCA_PANE_KEY": "tab-init:leaf-init",
            "ORCA_WORKTREE_ID": "repo-init::/tmp/init",
            "PLUGIN_ROOT": str(Path(refresh.__file__).resolve().parents[1]),
            "CLAUDE_PLUGIN_ROOT": str(Path(refresh.__file__).resolve().parents[1]),
            "TERM_PROGRAM": "Orca",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        for session in self.terminals:
            self.register(session)
        self.inventory_patch = patch.object(refresh, "terminal_inventory", side_effect=lambda: [dict(item) for item in self.terminals])
        self.inventory_patch.start()
        self.addCleanup(self.inventory_patch.stop)
        self.patches = [
            patch.object(refresh, "_manifest_snapshots", side_effect=self.snapshots),
            patch.object(refresh, "wait_terminal", side_effect=lambda handle, condition, timeout: self.wait_result(handle, condition)),
            patch.object(refresh, "executable", side_effect=lambda name: name),
            patch.object(refresh, "terminal_has_draft", return_value=False),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    @staticmethod
    def terminal(host, handle, worktree_id, path, tab_id, leaf_id):
        return {
            "host": host,
            "terminal_handle": handle,
            "incarnation_id": f"incarnation-{handle}",
            "worktree_id": worktree_id,
            "worktree_path": path,
            "tab_id": tab_id,
            "leaf_id": leaf_id,
            "connected": True,
            "writable": True,
            "orphaned": False,
            "title": f"{host}-{leaf_id}",
        }

    def snapshots(self):
        return {host: dict(value) for host, value in self.versions.items()}

    @staticmethod
    def wait_result(handle, condition):
        return True

    def register(self, terminal, *, state="idle", plugin_version="0.5.2", last_event="Stop"):
        with registry_lock(self.app_root) as registry:
            records = registry["sessions"]
            session_id = f"session-{terminal['leaf_id']}"
            records[session_key(terminal["host"], session_id)] = {
                "host": terminal["host"],
                "session_id": session_id,
                "terminal_handle": terminal["terminal_handle"],
                "worktree_id": terminal["worktree_id"],
                "cwd": terminal["worktree_path"],
                "tab_id": terminal["tab_id"],
                "leaf_id": terminal["leaf_id"],
                "plugin_version": plugin_version,
                "state": state,
                "event_sequence": 1,
                "last_event": last_event,
                "updated_at": "2026-09-23T00:00:00Z",
            }
