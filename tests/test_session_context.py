from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS = json.loads((REPO_ROOT / "hooks/hooks.json").read_text())["hooks"]


class SessionContextTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "plugin space (한글) $literal"
        self.root.mkdir()
        for name in ("AGENTS.md", "CLAUDE.md"):
            shutil.copy2(REPO_ROOT / name, self.root / name)
            path = self.root / name
            path.write_text(path.read_text() + "\nROOT PROJECT SENTINEL\n")
        for name in ("scripts", "instructions"):
            shutil.copytree(REPO_ROOT / name, self.root / name)
        self.cwd = self.base / "unrelated project"
        self.cwd.mkdir()
        (self.cwd / "AGENTS.md").write_text("UNRELATED PROJECT SENTINEL")
        self.bin = self.base / "bin"
        self.bin.mkdir()
        (self.bin / "python3").symlink_to(sys.executable)

    def run_hook(self, host="codex", event="SessionStart", source="startup", payload=None, extra_env=None):
        env = {"PATH": f"{self.bin}{os.pathsep}{os.defpath}", "CLAUDE_PLUGIN_ROOT": str(self.root)}
        if host == "codex":
            env["PLUGIN_ROOT"] = str(self.root)
        env.update(extra_env or {})
        handler = HOOKS[event][0]["hooks"][0]
        return subprocess.run(
            handler["command"],
            shell=True,
            cwd=self.cwd,
            env=env,
            input=payload if payload is not None else json.dumps({"hook_event_name": event, "source": source}),
            text=True,
            capture_output=True,
            timeout=handler["timeout"],
        )

    def context(self, result, event="SessionStart"):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], event)
        return output["additionalContext"]

    def test_both_hosts_receive_core_rules_for_all_session_sources(self):
        for host in ("codex", "claude"):
            for source in ("startup", "resume", "clear", "compact", "fork"):
                with self.subTest(host=host, source=source):
                    context = self.context(self.run_hook(host, source=source))
                    self.assertIn("Never expose secrets", context)
                    self.assertEqual(context.count("# Common"), 1)
                    self.assertEqual("# Codex only" in context, host == "codex")
                    self.assertEqual("# Claude Code only" in context, host == "claude")
                    self.assertNotIn("UNRELATED PROJECT SENTINEL", context)
                    self.assertNotIn("ROOT PROJECT SENTINEL", context)

    def test_subagents_receive_their_host_instructions(self):
        for host in ("codex", "claude"):
            with self.subTest(host=host):
                context = self.context(self.run_hook(host, event="SubagentStart"), "SubagentStart")
                self.assertIn("Never expose secrets", context)
                self.assertEqual("# Codex only" in context, host == "codex")
                self.assertEqual("# Claude Code only" in context, host == "claude")

    def test_references_are_absolute_and_details_stay_unloaded(self):
        context = self.context(self.run_hook("claude"))
        links = re.findall(r"\]\(<([^>]+)>\)", context)
        self.assertEqual(len(links), 4)
        for link in links:
            self.assertTrue(Path(link).is_relative_to(self.root))
            self.assertTrue(Path(link).is_file())
        self.assertNotIn("## Azure skill authorization", context)
        self.assertNotIn("## Investigation", context)
        self.assertNotIn("# Documentation files", context)
        self.assertLess(len(context.encode("utf-8")), 9000)

    def test_changed_instructions_are_read_on_the_next_event(self):
        self.context(self.run_hook())
        path = self.root / "instructions/session/common.md"
        path.write_text(path.read_text() + "\nUPDATED INSTRUCTION SENTINEL\n")
        self.assertIn("UPDATED INSTRUCTION SENTINEL", self.context(self.run_hook(source="compact")))

    def test_changed_project_instructions_do_not_change_hook_context(self):
        before = self.context(self.run_hook())
        path = self.root / "AGENTS.md"
        path.write_text(path.read_text() + "\nPROJECT CHANGE SENTINEL\n")
        self.assertEqual(before, self.context(self.run_hook(source="compact")))

    def test_korean_mirrors_are_not_loaded(self):
        path = self.root / "instructions/session/common.ko.md"
        path.write_text(path.read_text() + "\nKOREAN MIRROR SENTINEL\n")
        self.assertNotIn("KOREAN MIRROR SENTINEL", self.context(self.run_hook()))

    def test_missing_reference_reports_failure_without_partial_context(self):
        (self.root / "instructions/protected-values.md").unlink()
        result = self.run_hook()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("instructions were not loaded", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_invalid_event_reports_failure(self):
        for payload in ("not json", "null", "[]", "{}", '{"hook_event_name":"Stop"}'):
            with self.subTest(payload=payload):
                result = self.run_hook(payload=payload)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("instructions were not loaded", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_missing_host_file_is_rejected(self):
        (self.root / "instructions/session/claude-code.md").unlink()
        result = self.run_hook("claude")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("instructions were not loaded", result.stderr)

    def test_oversized_context_reports_failure(self):
        (self.root / "instructions/session/common.md").write_text("x" * 9001)
        result = self.run_hook()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("context budget", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_unrelated_inherited_plugin_root_does_not_select_codex(self):
        context = self.context(self.run_hook("claude", extra_env={"PLUGIN_ROOT": str(self.cwd)}))
        self.assertIn("# Claude Code only", context)

    def test_hook_does_not_modify_user_or_project_files(self):
        before = {p.relative_to(self.base): p.read_bytes() for p in self.base.rglob("*") if p.is_file()}
        self.context(self.run_hook())
        self.context(self.run_hook("claude"))
        after = {p.relative_to(self.base): p.read_bytes() for p in self.base.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_all_instruction_links_resolve_in_the_bundle(self):
        paths = sorted((REPO_ROOT / "instructions").rglob("*.md"))
        for path in paths:
            for link in re.findall(r"\]\(([^)]+)\)", path.read_text()):
                with self.subTest(path=path, link=link):
                    target = (path.parent / link).resolve()
                    self.assertTrue(target.is_relative_to(REPO_ROOT))
                    self.assertTrue(target.is_file())

    def test_repository_has_project_instruction_files(self):
        self.assertTrue((REPO_ROOT / "AGENTS.md").is_file())
        self.assertEqual((REPO_ROOT / "CLAUDE.md").read_text(), "@AGENTS.md\n")


if __name__ == "__main__":
    unittest.main()
