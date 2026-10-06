from __future__ import annotations

import hashlib
import importlib.util
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
LEGACY_EXPLORER = REPO_ROOT / "tests/fixtures/legacy-codex-explorer.toml"
LEGACY_WORKER = REPO_ROOT / "tests/fixtures/legacy-codex-worker.toml"
RETIRED_EXPLORER_DIGESTS = {"bfde4fbbe2740152ad537d576612a34619a57a45adb56072e3f945610ef820af"}
RETIRED_WORKER_DIGESTS = {"ce4488d0323832dc1563481875e7c26d693092c94865c37a4b4b89afd8274f83"}


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
        self.codex_home = self.base / "codex home"
        self.scout = self.codex_home / "agents" / "scout.toml"
        self.worker = self.codex_home / "agents" / "worker.toml"
        self.researcher = self.codex_home / "agents" / "researcher.toml"
        shutil.copytree(REPO_ROOT / "standalone-agents", self.root / "standalone-agents")

    def run_hook(self, host="codex", event="SessionStart", source="startup", payload=None, extra_env=None):
        env = {
            "PATH": f"{self.bin}{os.pathsep}{os.defpath}",
            "CLAUDE_PLUGIN_ROOT": str(self.root),
            "CODEX_HOME": str(self.codex_home),
        }
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

    def test_참조는_절대_경로이고_세부_본문은_불러오지_않는다(self):
        """작업 효율과 검토를 포함한 참조 11개는 절대 경로로 바뀌고 세부 본문은 시작 시 불러오지 않는다."""
        # Given
        host = "claude"

        # When
        context = self.context(self.run_hook(host))

        # Then
        links = re.findall(r"\]\(<([^>]+)>\)", context)
        self.assertEqual(len(links), 11)
        for link in links:
            self.assertTrue(Path(link).is_relative_to(self.root))
            self.assertTrue(Path(link).is_file())
        self.assertIn((self.root / "instructions/implementation-execution.md").as_posix(), links)
        self.assertIn((self.root / "instructions/work-efficiency.md").as_posix(), links)
        self.assertNotIn("## Azure skill authorization", context)
        self.assertNotIn("## Investigation", context)
        self.assertNotIn("# Documentation files", context)
        self.assertNotIn("# Test code", context)
        self.assertNotIn("## 1. Intent and scope freeze", context)
        self.assertNotIn("## Reviewer selection", context)
        self.assertNotIn("Latest available Claude Fable", context)
        self.assertNotIn("# Implementation execution", context)
        self.assertNotIn("## Scheduling", context)
        self.assertNotIn("## Assigned workers", context)
        self.assertNotIn("## Model evaluations", context)
        self.assertLess(len(context.encode("utf-8")), 9000)

    def test_작업_효율_참조가_없으면_부분_문맥을_반환하지_않는다(self):
        """두 호스트 모두 작업 효율 참조가 누락되면 오류를 알리고 부분 시작 문맥을 반환하지 않는다."""
        for host in ("codex", "claude"):
            with self.subTest(host=host):
                # Given
                path = self.root / "instructions/work-efficiency.md"
                if path.exists():
                    path.unlink()

                # When
                result = self.run_hook(host)

                # Then
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("work-efficiency.md", result.stderr)

    def test_worker도_실행_규칙_경로와_worker_섹션_안내를_받는다(self):
        """하위 에이전트 시작 컨텍스트도 실행 규칙 링크와 할당받은 worker 섹션 안내를 담는다."""
        # Given
        expected = (self.root / "instructions/implementation-execution.md").as_posix()

        # When
        contexts = {
            host: self.context(self.run_hook(host, event="SubagentStart"), "SubagentStart")
            for host in ("codex", "claude")
        }

        # Then
        for host, context in contexts.items():
            with self.subTest(host=host):
                self.assertIn(f"[implementation execution rules](<{expected}>)", context)
                self.assertIn('reads only its "Assigned workers" section', context)
                self.assertNotIn("## Assigned workers", context)
                self.assertLess(len(context.encode("utf-8")), 9000)

    def test_planning_routing_is_loaded_without_detailed_workflow(self):
        context = self.context(self.run_hook("codex"))
        self.assertIn("An implementation plan must let an executor proceed", context)
        self.assertIn("This is an explicit exception to the preceding trigger boundary", context)
        self.assertIn("instructions/implementation-planning.md", context)
        self.assertIn("instructions/independent-model-validation.md", context)
        self.assertNotIn("## 1. Intent and scope freeze", context)

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

    def test_missing_planning_reference_reports_failure_without_partial_context(self):
        (self.root / "instructions/implementation-planning.md").unlink()
        result = self.run_hook()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("instructions were not loaded", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_실행_규칙이_없으면_부분_컨텍스트_없이_실패한다(self):
        """구현 실행 참조 파일이 없으면 훅은 일부 컨텍스트도 내보내지 않고 실패를 알린다."""
        # Given
        (self.root / "instructions/implementation-execution.md").unlink()

        # When
        result = self.run_hook()

        # Then
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("instructions were not loaded", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_missing_validation_reference_reports_failure_without_partial_context(self):
        (self.root / "instructions/independent-model-validation.md").unlink()
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
        def snapshot():
            return {
                p.relative_to(self.base): p.read_bytes()
                for p in self.base.rglob("*")
                if p.is_file() and not p.is_relative_to(self.codex_home)
            }

        before = snapshot()
        self.context(self.run_hook())
        self.context(self.run_hook("claude"))
        self.assertEqual(before, snapshot())

    def test_codex_session_provisions_the_bundled_scout_and_worker_agents(self):
        self.assertFalse(self.scout.exists())
        self.assertFalse(self.worker.exists())
        self.context(self.run_hook("codex"))
        for target, bundled in ((self.scout, "codex-scout.toml"), (self.worker, "codex-worker.toml")):
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                (REPO_ROOT / "standalone-agents" / bundled).read_text(encoding="utf-8"),
            )

    def test_Codex_세션은_누락된_연구원_역할을_설치한다(self):
        """Codex 세션은 researcher 역할이 없을 때 번들 정의를 설치한다."""
        # Given
        self.researcher.parent.mkdir(parents=True)

        # When
        self.context(self.run_hook("codex"))

        # Then
        self.assertEqual(
            self.researcher.read_text(encoding="utf-8"),
            (REPO_ROOT / "standalone-agents/codex-researcher.toml").read_text(encoding="utf-8"),
        )

    def test_provisioning_never_overwrites_an_existing_agent(self):
        self.scout.parent.mkdir(parents=True)
        self.worker.write_text('name = "worker"\n', encoding="utf-8")
        self.context(self.run_hook("codex"))
        self.assertEqual(self.worker.read_text(encoding="utf-8"), 'name = "worker"\n')
        self.assertEqual(
            self.scout.read_text(encoding="utf-8"),
            (REPO_ROOT / "standalone-agents/codex-scout.toml").read_text(encoding="utf-8"),
        )

    def test_Codex_세션은_사용자가_작성한_연구원_역할을_그대로_둔다(self):
        """Codex 세션은 사용자가 작성한 researcher 역할을 덮어쓰지 않는다."""
        # Given
        custom = 'name = "researcher"\ndescription = "user-owned"\n'
        self.researcher.parent.mkdir(parents=True)
        self.researcher.write_text(custom, encoding="utf-8")

        # When
        self.context(self.run_hook("codex"))

        # Then
        self.assertEqual(self.researcher.read_text(encoding="utf-8"), custom)

    def test_codex_session_retires_only_an_unmodified_explorer_from_an_earlier_version(self):
        shipped = LEGACY_EXPLORER.read_bytes()
        self.assertIn(hashlib.sha256(shipped).hexdigest(), RETIRED_EXPLORER_DIGESTS)
        explorer = self.codex_home / "agents" / "explorer.toml"
        explorer.parent.mkdir(parents=True)
        explorer.write_bytes(shipped)
        self.context(self.run_hook("codex"))
        self.assertFalse(explorer.exists())

        explorer.write_bytes(shipped + b"# edited by the user\n")
        self.context(self.run_hook("codex"))
        self.assertEqual(explorer.read_bytes(), shipped + b"# edited by the user\n")

    def test_이전_버전의_worker_역할은_수정하지_않았을_때만_현재_파일로_바꾼다(self):
        """이전 플러그인 버전이 쓴 worker.toml은 바이트 단위로 같을 때만 현재 번들 파일로 바꾸고, 고친 파일은 그대로 둔다."""
        # Given
        shipped = LEGACY_WORKER.read_bytes()
        self.assertIn(hashlib.sha256(shipped).hexdigest(), RETIRED_WORKER_DIGESTS)
        bundled = (REPO_ROOT / "standalone-agents/codex-worker.toml").read_bytes()
        self.assertNotEqual(shipped, bundled)
        self.worker.parent.mkdir(parents=True)
        self.worker.write_bytes(shipped)

        # When
        self.context(self.run_hook("codex"))

        # Then
        self.assertEqual(self.worker.read_bytes(), bundled)

    def test_사용자가_고친_이전_버전_worker_역할은_남긴다(self):
        """이전 버전 worker.toml에 사용자가 한 글자라도 더했으면 훅은 그 파일을 바꾸지 않는다."""
        # Given
        edited = LEGACY_WORKER.read_bytes() + b"# edited by the user\n"
        self.worker.parent.mkdir(parents=True)
        self.worker.write_bytes(edited)

        # When
        self.context(self.run_hook("codex"))

        # Then
        self.assertEqual(self.worker.read_bytes(), edited)

    def test_claude_session_never_retires_a_codex_agent(self):
        explorer = self.codex_home / "agents" / "explorer.toml"
        explorer.parent.mkdir(parents=True)
        explorer.write_bytes(LEGACY_EXPLORER.read_bytes())
        self.context(self.run_hook("claude"))
        self.assertTrue(explorer.exists())

    def test_claude_session_never_provisions_a_codex_agent(self):
        self.context(self.run_hook("claude"))
        self.assertFalse(self.scout.exists())
        self.assertFalse(self.worker.exists())

    def test_unwritable_codex_home_still_delivers_context(self):
        self.codex_home.write_text("not a directory", encoding="utf-8")
        self.assertIn("Never expose secrets", self.context(self.run_hook("codex")))

    def test_지침의_로컬_링크는_모두_번들_안에서_해석된다(self):
        """지침 파일의 로컬 링크는 번들 안의 파일을 가리키고, 로더처럼 URI 스킴이 있는 외부 링크는 건너뛴다."""
        # Given
        paths = sorted((REPO_ROOT / "instructions").rglob("*.md"))

        # When
        links = [
            (path, link)
            for path in paths
            for link in re.findall(r"\]\(([^)]+)\)", path.read_text())
            if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", link)
        ]

        # Then
        self.assertTrue(links)
        for path, link in links:
            with self.subTest(path=path, link=link):
                target = (path.parent / link.split("#", 1)[0]).resolve()
                self.assertTrue(target.is_relative_to(REPO_ROOT))
                self.assertTrue(target.is_file())

    def orca_env(self):
        return {"ORCA_USER_DATA_PATH": str(self.base / "orca"), "ORCA_TERMINAL_HANDLE": "term_marker-1"}

    def marker_path(self):
        return self.base / "orca" / "hei5enbug-agent-setup" / "terminals" / "term_marker-1.json"

    def load_context_module(self):
        spec = importlib.util.spec_from_file_location("session_context_digest", self.root / "scripts" / "session_context.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_Orca_세션_시작은_불러온_지침의_표식을_남긴다(self):
        """Orca 터미널의 세션 시작 훅은 호스트, 플러그인 경로, 지침 요약값, 시작 이유를 사용자 전용 파일로 남긴다."""
        # Given
        env = self.orca_env()

        transcript = (self.base / "rollout.jsonl").as_posix()
        Path(transcript).write_text(json.dumps({"type": "session_meta", "payload": {"source": "cli"}}) + "\n", encoding="utf-8")
        payload = json.dumps({"hook_event_name": "SessionStart", "source": "compact", "transcript_path": transcript})

        # When
        self.context(self.run_hook("codex", payload=payload, extra_env=env))

        # Then
        marker = json.loads(self.marker_path().read_text(encoding="utf-8"))
        self.assertEqual(("codex", self.root.as_posix(), "compact", 1), (marker["host"], marker["root"], marker["source"], marker["schema"]))
        self.assertEqual(transcript, marker["transcript_path"])
        self.assertEqual(self.load_context_module().instructions_digest(self.root), marker["digest"])
        self.assertEqual(0o600, self.marker_path().stat().st_mode & 0o777)

    def test_하위_CLI_세션은_터미널_표식을_덮어쓰지_않는다(self):
        """같은 Orca 터미널에서 띄운 claude -p나 codex exec는 대화형 세션의 표식을 쓰지 않는다."""
        # Given
        env = self.orca_env()
        exec_rollout = self.base / "exec.jsonl"
        exec_rollout.write_text(json.dumps({"type": "session_meta", "payload": {"source": "exec"}}) + "\n", encoding="utf-8")
        codex_payload = json.dumps({"hook_event_name": "SessionStart", "source": "startup", "transcript_path": exec_rollout.as_posix()})

        self.context(self.run_hook("claude", extra_env={**env, "CLAUDE_CODE_ENTRYPOINT": "cli"}))
        interactive = self.marker_path().read_bytes()

        # When
        self.context(self.run_hook("claude", source="compact", extra_env={**env, "CLAUDE_CODE_ENTRYPOINT": "sdk-cli"}))
        self.context(self.run_hook("codex", payload=codex_payload, extra_env=env))

        # Then
        self.assertEqual(interactive, self.marker_path().read_bytes())

    def test_서브에이전트_시작과_Orca_밖_세션은_표식을_남기지_않는다(self):
        """표식은 Orca 터미널의 본 세션 시작에만 쓰고 서브에이전트나 Orca 밖 세션에서는 쓰지 않는다."""
        # Given
        env = self.orca_env()

        # When
        self.context(self.run_hook("claude", event="SubagentStart", extra_env=env), "SubagentStart")
        self.context(self.run_hook("claude"))

        # Then
        self.assertFalse(self.marker_path().exists())

    def test_지침_요약값은_설치_위치와_번역본에_영향받지_않는다(self):
        """같은 지침을 다른 경로에 설치해도 요약값이 같고, 한국어 번역본만 바뀌면 그대로이며, 실행 지침이 바뀌면 달라진다."""
        # Given
        module = self.load_context_module()
        other = self.base / "other install"
        shutil.copytree(self.root, other)
        original = module.instructions_digest(self.root)

        # When
        moved = module.instructions_digest(other)
        mirror = other / "instructions/session/common.ko.md"
        mirror.write_text(mirror.read_text(encoding="utf-8") + "\n번역 수정\n", encoding="utf-8")
        after_mirror = module.instructions_digest(other)
        rule = other / "instructions/testing.md"
        rule.write_text(rule.read_text(encoding="utf-8") + "\nNew rule.\n", encoding="utf-8")
        after_rule = module.instructions_digest(other)

        # Then
        self.assertEqual(original, moved)
        self.assertEqual(original, after_mirror)
        self.assertNotEqual(original, after_rule)

    def test_repository_has_project_instruction_files(self):
        self.assertTrue((REPO_ROOT / "AGENTS.md").is_file())
        self.assertEqual((REPO_ROOT / "CLAUDE.md").read_text(), "@AGENTS.md\n")


if __name__ == "__main__":
    unittest.main()
