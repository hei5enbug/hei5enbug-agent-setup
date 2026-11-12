from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_orca_plugin_refresh as base
import test_refresh_resume as resume_base
import refresh_codex_release as releases
import refresh_codex_session as sessions
import refresh_core
import refresh_install
import refresh_process
import refresh_resume
import refresh_sessions

refresh = base.refresh
SESSION_ID = resume_base.SESSION_ID


class ReleasePinTest(unittest.TestCase):
    setUp = base.UpdateTest.setUp
    install = base.UpdateTest.install
    plugin_root = base.UpdateTest.plugin_root
    companion = base.UpdateTest.companion
    stage = base.UpdateTest.stage
    stage_companion = base.UpdateTest.stage_companion
    run_with = base.UpdateTest.run_with

    def test_보류_뒤_재실행은_남아_있는_최신_스크립트를_사용한다(self):
        """최신 스크립트가 남아 있으면 재실행 명령이 태그 고정을 지원하지 않는 옛 설치본으로 돌아가지 않는다."""
        # Given
        relative = Path("skills/orca-plugin-refresh/scripts/orca_plugin_refresh.py")
        current_root, old_root = self.base / "current", self.base / "old"
        for root in (current_root, old_root):
            script = root / relative
            script.parent.mkdir(parents=True)
            script.write_text("pass\n")

        # When
        with patch.object(refresh, "__file__", str(current_root / relative)), patch.object(refresh, "PLUGIN_ROOT", current_root.resolve()):
            command = refresh.recovery_command(str(old_root), ["demo@market"])

        # Then
        self.assertEqual(str((current_root / relative).resolve()), shlex.split(command)[1])
        self.assertIn("--also demo@market", command)
    def test_첫_Codex_실행_전에_최신_정식_태그를_고정하고_태그_없는_마켓은_설치하지_않는다(self):
        """정식 태그가 있는 마켓은 첫 Codex 실행 전에 고정하고 태그 없는 마켓은 설정을 보존하고 설치하지 않는다."""
        # Given
        fake = base.FakeCli()
        self.stage(fake)
        self.stage_companion(fake, "codex", "demo@empty", "1.0.0")
        config = self.base / "codex-home/config.toml"
        config.write_text('[marketplaces.hei5enbug]\nsource_type = "git"\nsource = "https://example.com/main.git"\nref = "main"\n'
                          '[marketplaces.empty]\nsource_type = "git"\nsource = "https://example.com/empty.git"\nref = "main"\n')
        observed = []
        original = fake.__call__

        def call(argv, **kwargs):
            if argv[0] == "codex":
                observed.append(releases.read_config()[2]["marketplaces"]["hei5enbug"]["ref"])
            return original(argv, **kwargs)

        # When
        with patch.object(releases, "remote_tags", side_effect=lambda source: {} if "empty" in source else
                          {"v1.2.0": "a" * 40, "v1.3.0": "b" * 40}), \
             patch.object(refresh_core, "run", side_effect=call), \
             patch.object(refresh_core, "executable", side_effect=lambda name: name), \
             patch.object(refresh, "run_claude_update", return_value={"status": "skipped", "reason": "test"}), \
             patch.object(refresh, "claude_unreleased_changes", return_value=([], None)):
            result = refresh.command_update(["demo@empty"])

        # Then
        self.assertTrue(observed)
        self.assertEqual({"v1.3.0"}, set(observed))
        self.assertEqual("main", releases.read_config()[2]["marketplaces"]["empty"]["ref"])
        self.assertEqual("codex_marketplace_untagged", result["hosts"]["codex"]["plugins"][0]["code"])
        self.assertFalse(any(call[-1] in {"empty", "demo@empty"} for call in fake.installs()))

    def test_활성_Codex_턴에서는_목록_조회도_실행하지_않는다(self):
        """목록 조회도 자동 설치를 일으킬 수 있으므로 활성 턴에서는 Codex 명령을 보내지 않는다."""
        # Given
        fake = base.FakeCli()
        self.stage(fake)

        config = self.base / "codex-home/config.toml"
        config.write_text('[marketplaces.hei5enbug]\nsource_type = "git"\nsource = "https://example.com/main.git"\nref = "main"\n')

        # When
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "active"}), \
             patch.object(releases, "remote_tags", return_value={"v1.0.0": "a" * 40}), \
             patch.object(refresh, "run_claude_update", return_value={"status": "skipped", "reason": "test"}):
            result = self.run_with(fake, refresh.command_update)

        # Then
        self.assertEqual("update_deferred_active_session", result["hosts"]["codex"]["error"]["code"])
        self.assertFalse(any(call[0] == "codex" for call in fake.commands))


class CompanionTrustTest(unittest.TestCase):
    def test_태그와_같은_동반_훅만_신뢰하고_외부_명령과_변조된_파일은_거부한다(self):
        """릴리스 원본과 같은 파일만 신뢰하며 외부 명령과 변조 파일에서는 신뢰 쓰기를 하지 않는다."""
        # Given
        with tempfile.TemporaryDirectory() as directory:
            repo, root = Path(directory) / "remote", Path(directory) / "installed"
            repo.mkdir()
            root.mkdir()
            files = {".agents/plugins/marketplace.json": json.dumps({"plugins": [{"name": "demo", "source": {"source": "local", "path": "./"}}]}),
                     "hooks/hooks.json": "{}", "scripts/run.py": "print('demo')\n"}
            for folder in (repo, root):
                for name, text in files.items():
                    path = folder / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text)
            def git(*args):
                return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()
            git("init", "-q")
            git("add", ".")
            git("-c", "user.name=Demo", "-c", "user.email=demo@example.com", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
            git("tag", "v1.0.0")
            pin = {"source": str(repo), "ref": "v1.0.0", "revision": git("rev-parse", "HEAD")}
            (root / releases.INSTALL_MARKER).write_text(json.dumps({"source": str(repo), "ref_name": "v1.0.0", "revision": pin["revision"]}))
            hook = {"pluginId": "demo@market", "key": "demo@market:hook", "trustStatus": "modified", "currentHash": "current",
                    "sourcePath": str(root / "hooks/hooks.json"), "command": f"python3 {shlex.quote(str(root / 'scripts/run.py'))}"}
            outcomes = []
            written_paths = []
            for case in ("clean", "outside", "changed"):
                calls = []
                selected = {**hook, **({"command": "python3 /tmp/outside.py"} if case == "outside" else {})}
                if case == "changed":
                    (root / "scripts/run.py").write_text("print('changed')\n")
                def app_server(command, env, cwd, batch, timeout):
                    calls.extend(method for method, _ in batch)
                    written_paths.extend(params["keyPath"] for method, params in batch if method == "config/value/write")
                    trusted = any(method == "config/value/write" for method, _ in batch)
                    return [{"data": [{"cwd": cwd, "hooks": [{**selected, "trustStatus": "trusted" if trusted else "modified"}]}]}]
                plugin = {"plugin": "demo@market", "root": str(root), "warnings": [dict(refresh.HOOKS_TRUST_WARNING)]}
                context = {"trust_reset": ["demo@market"], "release_pins": {"market": pin}}

                # When
                with patch.object(refresh.CODEX_HOOK_TRUST, "app_server_calls", side_effect=app_server), \
                     patch.object(refresh_core, "executable", side_effect=lambda name: name):
                    result = refresh.settle_companion_trust([plugin], context)[0]
                outcomes.append(("config/value/write" in calls, bool(result["warnings"])))

        # Then
        self.assertEqual([(True, False), (False, True), (False, True)], outcomes)
        self.assertEqual(['hooks.state."demo@market:hook".trusted_hash'], written_paths)


class CodexResumeTest(resume_base.ResumeCase):
    def setUp(self):
        super().setUp()
        self.processes.table.clear()
        self.launch_args = ["codex", "-m", "demo-model", "-c", 'model_reasoning_effort="high"', "--no-alt-screen"]
        self.processes.help_text = '  -m, --model <MODEL>\n  -c, --config <KEY=VALUE>\n      --no-alt-screen\n'
        self.pid = self.processes.add("term_claude", self.launch_args, "/tmp/codex", None, comm="codex", extra_env={"CODEX_HOME": "/tmp/profile"})
        self.fake.list[0]["agentIdentity"] = "codex"
        self.fake.screens["term_claude"] = list(__import__('test_orca_plugin_refresh').CODEX_EMPTY)
        self.transcript.write_text(json.dumps({"type": "session_meta", "payload": {"id": SESSION_ID}}) + "\n" +
                                   json.dumps({"type": "turn_context", "payload": {}}) + "\n" +
                                   json.dumps({"type": "event_msg", "payload": {"type": "task_complete"}}) + "\n")
        path = refresh.SESSION_CONTEXT.marker_directory() / "term_claude.json"
        marker = json.loads(path.read_text())
        marker["host"] = "codex"
        path.write_text(json.dumps(marker))
        self.state["hosts"]["codex"]["installed_at"] = 200.0
        refresh.save_json(refresh.run_path(self.run_id), {**self.state, "run_id": self.run_id})

    def test_교체_전_프로세스만_재개를_요청하고_승인된_세션의_옵션과_대화를_보존한다(self):
        """교체 전 시작한 세션만 재개를 요청하고 승인 뒤 같은 터미널에서 원래 옵션으로 같은 대화를 재개한다."""
        # Given
        marker = refresh_sessions.read_marker("term_claude")
        system = SimpleNamespace(**{**vars(self.processes.system()), "started_at": lambda pid: 100.0,
                                    "which": lambda name: "/tmp/codex"})
        def simulate(fake, handle, text):
            if text == "/exit":
                self.processes.table.pop(self.pid)
                fake.screens[handle] = list(resume_base.SHELL_AFTER_EXIT)
            elif " resume " in text:
                self.processes.add(handle, ["codex", *shlex.split(text)[2:]], "/tmp/codex", None, comm="codex",
                                   extra_env={"CODEX_HOME": "/tmp/profile"})
                fake.screens[handle] = list(base.CODEX_EMPTY)
                path = refresh.SESSION_CONTEXT.marker_directory() / f"{handle}.json"
                path.write_text(json.dumps({**marker, "source": "resume", "written_at": resume_base.LATER()}))
        self.fake.on_send = simulate

        # When
        with patch.object(sessions, "ProcessOs", return_value=system):
            entry = refresh_sessions.plan_sessions(self.fake, self.state, "auto", ["term_claude"])[0]
            result = refresh_resume.run_resume(self.run_id, ["term_claude"], orca=self.fake, system=system, sleep=lambda seconds: None)
        captured = [text for _, text in self.fake.sent]

        # Then
        self.assertTrue(refresh.public(entry)["resume_approval_needed"])
        self.assertEqual("done", result["sessions"][0]["status"])
        self.assertEqual("/exit", captured[0])
        self.assertEqual(["CODEX_HOME=/tmp/profile", "/tmp/codex", "resume", SESSION_ID, *self.launch_args[1:]], shlex.split(captured[1]))

    def test_설치_뒤_시작했거나_턴이_없으면_재개_대상에서_제외한다(self):
        """설치 뒤 시작한 프로세스와 턴이 없는 세션은 재개에서 제외하고 시작 시각을 모르면 확인되지 않은 상태를 반환한다."""
        # Given
        marker = refresh_sessions.read_marker("term_claude")
        system = replace(self.processes.system(), started_at=lambda pid: 100.0)
        later = replace(system, started_at=lambda pid: 300.0)
        unknown = replace(system, started_at=lambda pid: None)
        fresh = Path(self.temp.name) / "fresh.jsonl"
        fresh.write_text(json.dumps({"type": "session_meta", "payload": {"id": SESSION_ID}}) + "\n")

        # When
        detection = [sessions.replaced_before_start("term_claude", item, self.state["hosts"]["codex"], environment)
                     for item, environment in ((marker, system), (marker, later), ({**marker, "transcript_path": str(fresh)}, system),
                                               (marker, unknown))]

        # Then
        self.assertEqual([True, False, False, None], detection)

    def test_재개_승인이_있어도_진행_중인_턴에는_종료_명령을_보내지_않는다(self):
        """재개를 요청해도 턴이 아직 끝나지 않았으면 세션을 종료하지 않는다."""
        # Given
        with self.transcript.open("a") as stream:
            stream.write(json.dumps({"type": "event_msg", "payload": {"type": "task_started"}}) + "\n")
        system = replace(self.processes.system(), started_at=lambda pid: 100.0, which=lambda name: "/tmp/codex")

        # When
        with patch.object(sessions, "ProcessOs", return_value=system):
            result = refresh_resume.run_resume(self.run_id, ["term_claude"], orca=self.fake, system=system, sleep=lambda seconds: None)

        # Then
        self.assertEqual("busy", result["sessions"][0]["detail"])
        self.assertEqual([], self.fake.sent)
