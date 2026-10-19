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
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import session_context  # noqa: E402

HOOKS = json.loads((REPO_ROOT / "hooks/hooks.json").read_text())["hooks"]
LEGACY_EXPLORER = REPO_ROOT / "tests/fixtures/legacy-codex-explorer.toml"
LEGACY_WORKER = REPO_ROOT / "tests/fixtures/legacy-codex-worker.toml"
RETIRED_EXPLORER_DIGESTS = {"bfde4fbbe2740152ad537d576612a34619a57a45adb56072e3f945610ef820af"}
LEGACY_RESEARCHER = REPO_ROOT / "tests/fixtures/legacy-codex-researcher.toml"
RETIRED_RESEARCHER_DIGESTS = {"940a7daace75165d8eceeece93a3c4960c42d187754738a744244059d5a0e5c1"}
RETIRED_WORKER_DIGESTS = {"ce4488d0323832dc1563481875e7c26d693092c94865c37a4b4b89afd8274f83"}
PINNED_EFFORT_WORKER_DIGEST = "89d72db180d2d0a16707804125af045ac5bb81baa2d751bad078747258b84d49"


class SessionContextTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "plugin space (한글) $x"
        self.root.mkdir()
        agents = self.root / "AGENTS.md"
        shutil.copy2(REPO_ROOT / "AGENTS.md", agents)
        agents.write_text(agents.read_text() + "\nROOT PROJECT SENTINEL\n")
        for name in ("scripts", "instructions", "config", ".claude-plugin", "docs/ko/instructions"):
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
        self.designer = self.codex_home / "agents" / "designer.toml"
        self.reviewer = self.codex_home / "agents" / "reviewer.toml"
        shutil.copytree(REPO_ROOT / "standalone-agents", self.root / "standalone-agents")

    def run_hook(self, host="codex", event="SessionStart", source="startup", payload=None, extra_env=None):
        env = {
            "PATH": f"{self.bin}{os.pathsep}{os.defpath}",
            "CLAUDE_PLUGIN_ROOT": str(self.root),
            "CODEX_HOME": str(self.codex_home),
            "XDG_STATE_HOME": str(self.base / "state"),
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

    def use_short_root(self):
        """Run the hook from a short plugin path, as an installed plugin does, so notices fit the context budget."""
        short = Path(tempfile.mkdtemp(prefix="h5", dir="/tmp")).resolve()
        self.addCleanup(shutil.rmtree, short, True)
        root = short / "p"
        shutil.copytree(self.root, root)
        self.root = root

    def write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_Claude_세션_시작은_호스트_settings의_dontAsk를_알린다(self):
        """Claude 호스트 설정의 dontAsk가 있으면 승인 요청이 자동 거부된다는 한 줄을 알린다."""
        # Given
        self.use_short_root()
        home = self.base / "temporary home"
        config = self.base / "alternate Claude config"
        self.write_json(home / ".claude/settings.json", {
            "permissions": {"defaultMode": "dontAsk", "ignored": "do not print"},
            "ignored": "do not print",
        })
        self.write_json(config / "settings.json", {"permissions": {"defaultMode": "dontAsk"}})

        # When
        contexts = [
            self.context(self.run_hook("claude", extra_env={"HOME": str(home)})),
            self.context(self.run_hook("claude", extra_env={"HOME": str(home), "CLAUDE_CONFIG_DIR": str(config)})),
        ]

        # Then
        for context in contexts:
            self.assertIn("Notice: Claude Code defaultMode dontAsk denies every approval the guard asks for.", context)
            self.assertNotIn("do not print", context)

    def test_Claude_세션_시작은_Bash와_mcp_ask_규칙을_최대_세_개까지_알린다(self):
        """Claude 프로젝트 설정의 Bash와 mcp ask 규칙은 최대 세 개의 이름만 알린다."""
        # Given
        self.use_short_root()
        self.write_json(self.cwd / ".claude/settings.json", {
            "permissions": {
                "ask": [
                    "Bash(git diff:*)",
                    "mcp__server__tool",
                    "Bash(ls:*)",
                    "mcp__fourth__tool",
                    "Read(*)",
                ],
                "ignored": "do not print",
            },
        })
        self.write_json(self.cwd / ".claude/settings.local.json", {"permissions": {"ask": ["Bash(tail:*)"]}})

        # When
        with mock.patch.dict(os.environ, {"HOME": str(self.base / "temporary home")}, clear=False):
            named_notice = session_context.session_start_notices("claude", self.cwd)[0]
        context = self.context(self.run_hook("claude", extra_env={"HOME": str(self.base / "temporary home")}))

        # Then
        self.assertIn(session_context.CLAUDE_ASK_NOTICE_PREFIX, context)
        self.assertIn("Bash(git diff:*)", named_notice)
        self.assertIn("mcp__server__tool", named_notice)
        self.assertIn("Bash(ls:*)", named_notice)
        self.assertNotIn("mcp__fourth__tool", named_notice)
        self.assertNotIn("mcp__fourth__tool", context)
        self.assertNotIn("do not print", context)

    def test_Claude_defaultMode는_로컬_프로젝트_사용자_순서로_우선한다(self):
        """Claude는 실제 적용되는 defaultMode만 경고하고 모든 설정 파일의 ask 규칙은 합친다."""
        for modes, expected in [
            (("dontAsk", "default", None), False),
            (("dontAsk", None, "default"), False),
            (("default", "dontAsk", "acceptEdits"), False),
            (("default", "dontAsk", None), True),
            (("default", "acceptEdits", "dontAsk"), True),
            (("dontAsk", None, None), True),
        ]:
            with self.subTest(modes=modes):
                # given
                config = self.base / "precedence config"
                paths = (config / "settings.json", self.cwd / ".claude/settings.json",
                         self.cwd / ".claude/settings.local.json")
                for index, (path, mode) in enumerate(zip(paths, modes)):
                    permissions = {"ask": [f"Bash(rule{index}:*)"]}
                    if mode is not None:
                        permissions["defaultMode"] = mode
                    self.write_json(path, {"permissions": permissions})
                # when
                with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(config)}, clear=False):
                    notices = session_context.session_start_notices("claude", self.cwd)
                # then
                self.assertEqual(any("defaultMode dontAsk" in notice for notice in notices), expected)
                self.assertTrue(all(f"Bash(rule{index}:*)" in "\n".join(notices) for index in range(3)))

    def test_두_호스트의_세션_시작은_Codex_plugin_hooks가_true가_아니면_알린다(self):
        """Codex 설정의 plugin_hooks가 true가 아니면 Claude와 Codex 세션 모두 approval guard가 Codex에서 실행되지 않는다고 알린다."""
        # Given
        self.use_short_root()
        codex_home = self.base / "temporary Codex home"
        (codex_home / "config.toml").parent.mkdir(parents=True, exist_ok=True)
        (codex_home / "config.toml").write_text(
            '[features]\nplugin_hooks = false\nignored = "do not print"\n', encoding="utf-8",
        )

        # When
        contexts = [
            self.context(self.run_hook(host, extra_env={"CODEX_HOME": str(codex_home), "HOME": str(self.base / "home")}))
            for host in ("codex", "claude")
        ]

        # Then
        for context in contexts:
            self.assertIn("Notice: Codex runs no approval guard until [features] plugin_hooks = true.", context)
            self.assertNotIn("do not print", context)

    def test_한도를_넘는_notice는_줄이거나_빼고_세션_지침은_그대로_둔다(self):
        """notice가 context 한도를 넘으면 ask 규칙 목록을 줄이고, 그래도 넘는 notice는 빼되 세션 지침은 실패시키지 않는다."""
        # Given
        context = "x" * 90 + "\n"
        ask_notice = session_context.CLAUDE_ASK_NOTICE_PREFIX + ": Bash(git diff:*), mcp__server__tool."
        other_notice = "Notice: " + "y" * 200
        limit = len(context.encode("utf-8")) + len(session_context.CLAUDE_ASK_NOTICE_PREFIX) + 2

        # When
        result = session_context.append_session_notices(context, [ask_notice, other_notice], limit)

        # Then
        self.assertEqual(result, context + session_context.CLAUDE_ASK_NOTICE_PREFIX + ".\n")

    def test_문제가_없으면_세션_시작_notice를_추가하지_않는다(self):
        """정상 설정이면 두 호스트 모두 세션 시작 notice를 추가하지 않는다."""
        # Given
        home = self.base / "normal home"
        self.write_json(home / ".claude/settings.json", {
            "permissions": {"defaultMode": "acceptEdits", "ask": ["Read(*)"]},
        })
        codex_home = self.base / "normal Codex home"
        (codex_home / "config.toml").parent.mkdir(parents=True, exist_ok=True)
        (codex_home / "config.toml").write_text("[features]\nplugin_hooks = true\n", encoding="utf-8")

        # When
        claude = self.context(self.run_hook("claude", extra_env={"HOME": str(home)}))
        codex = self.context(self.run_hook("codex", extra_env={"CODEX_HOME": str(codex_home)}))

        # Then
        for context in (claude, codex):
            self.assertNotIn("Notice:", context)

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

    def subagent_context(self, host, agent_type=None):
        event = {"hook_event_name": "SubagentStart"}
        if agent_type is not None:
            event["agent_type"] = agent_type
        return self.context(self.run_hook(host, event="SubagentStart", payload=json.dumps(event)), "SubagentStart")

    def test_Codex는_에이전트_종류가_없는_하위_시작에_메인_컨텍스트를_준다(self):
        """Codex 하위 시작 이벤트에 agent_type이 없으면 메인 컨텍스트를 받고, Claude는 코어만 받는다."""
        # Given
        hosts = ("codex", "claude")

        # When
        contexts = {host: self.subagent_context(host) for host in hosts}

        # Then
        self.assertIn("# Common", contexts["codex"])
        self.assertIn("# Codex only", contexts["codex"])
        self.assertIn("Never expose secrets", contexts["claude"])
        self.assertNotIn("# Common", contexts["claude"])
        self.assertNotIn("# Claude Code only", contexts["claude"])

    def test_구현_에이전트는_코어와_할당받은_worker_절만_받는다(self):
        """구현 에이전트는 코어와 Assigned workers 절만 받고 공통과 호스트 지침, 실행 규칙의 나머지는 받지 않는다."""
        # Given
        agents = {
            "claude": (
                "hei5enbug-agent-setup:worker",
                "hei5enbug-agent-setup:sonnet-worker",
                "hei5enbug-agent-setup:designer",
            ),
            "codex": ("worker", "designer"),
        }

        for host, agent_types in agents.items():
            for agent_type in agent_types:
                with self.subTest(host=host, agent_type=agent_type):
                    # When
                    context = self.subagent_context(host, agent_type)

                    # Then
                    self.assertIn("Never expose secrets", context)
                    self.assertIn("## Assigned workers", context)
                    self.assertIn("An assigned worker executes its task directly", context)
                    self.assertNotIn("# Common", context)
                    self.assertNotIn("# Codex only", context)
                    self.assertNotIn("# Claude Code only", context)
                    self.assertNotIn("## Scheduling", context)
                    self.assertNotIn("Response language", context)
                    self.assertNotIn("Implementation worker route", context)
                    self.assertLess(len(context.encode("utf-8")), session_context.MAX_ROLE_CONTEXT_BYTES)

    def test_그_밖의_에이전트는_코어만_받는다(self):
        """구현 에이전트가 아닌 에이전트와 접두사 없는 Claude 이름은 코어만 받는다."""
        # Given
        agents = {
            "claude": ("hei5enbug-agent-setup:scout", "hei5enbug-agent-setup:reviewer", "worker", "general-purpose"),
            "codex": ("scout", "reviewer", "hei5enbug-agent-setup:worker"),
        }

        for host, agent_types in agents.items():
            for agent_type in agent_types:
                with self.subTest(host=host, agent_type=agent_type):
                    # When
                    context = self.subagent_context(host, agent_type)

                    # Then
                    self.assertIn("Never expose secrets", context)
                    self.assertNotIn("## Assigned workers", context)
                    self.assertNotIn("# Common", context)
                    self.assertNotIn("Implementation worker route", context)
                    self.assertLess(len(context.encode("utf-8")), session_context.MAX_ROLE_CONTEXT_BYTES)

    def test_할당된_역할_환경_변수가_있으면_세션_시작도_코어만_받는다(self):
        """HEI5ENBUG_ASSIGNED_ROLE이 있는 세션은 두 호스트 모두 코어만 받고, 빈 값은 메인 컨텍스트를 받는다."""
        for host in ("codex", "claude"):
            with self.subTest(host=host):
                # Given
                extra_env = {"HEI5ENBUG_ASSIGNED_ROLE": "worker"}

                # When
                role = self.context(self.run_hook(host, extra_env=extra_env))
                main = self.context(self.run_hook(host, extra_env={"HEI5ENBUG_ASSIGNED_ROLE": ""}))

                # Then
                self.assertIn("Never expose secrets", role)
                self.assertNotIn("# Common", role)
                self.assertNotIn("## Assigned workers", role)
                self.assertLess(len(role.encode("utf-8")), session_context.MAX_ROLE_CONTEXT_BYTES)
                self.assertIn("# Common", main)

    def test_할당받은_worker_절은_다음_제목_앞에서_끝난다(self):
        """공개 함수는 제목을 포함해 다음 같은 수준 제목 앞까지만 돌려주고 파일 끝까지 가는 경우도 처리한다."""
        # Given
        path = self.root / "instructions/implementation-delegation.md"

        # When
        section = session_context.assigned_workers_section(self.root)
        path.write_text("# T\n\n## Before\n\nx\n\n## Assigned workers\n\n- one\n- two\n", encoding="utf-8")
        last = session_context.assigned_workers_section(self.root)

        # Then
        self.assertTrue(section.startswith("## Assigned workers\n"))
        self.assertNotIn("\n## ", section)
        self.assertIn("Return the changed paths, check results, and remaining blockers.", section)
        self.assertEqual(last, "## Assigned workers\n\n- one\n- two")

    def test_할당받은_worker_절이_없으면_구현_에이전트_컨텍스트는_실패한다(self):
        """절이 없으면 구현 에이전트 시작은 부분 컨텍스트 없이 실패하고 메인 세션은 영향받지 않는다."""
        # Given
        path = self.root / "instructions/implementation-delegation.md"
        path.write_text(path.read_text().replace("## Assigned workers", "## Workers"), encoding="utf-8")

        # When
        failed = self.run_hook(
            "claude",
            event="SubagentStart",
            payload=json.dumps({"hook_event_name": "SubagentStart", "agent_type": "hei5enbug-agent-setup:worker"}),
        )
        other = self.subagent_context("claude", "hei5enbug-agent-setup:scout")
        main = self.context(self.run_hook("claude"))

        # Then
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(failed.stdout, "")
        self.assertIn("Assigned workers", failed.stderr)
        self.assertIn("Never expose secrets", other)
        self.assertIn("# Common", main)

    def test_역할_컨텍스트가_4000바이트를_넘으면_실패한다(self):
        """코어가 역할 한도를 넘으면 역할 컨텍스트는 예산 오류로 끝나고 빈 출력을 낸다."""
        # Given
        path = self.root / "instructions/session/core.md"
        path.write_text(path.read_text() + "\n" + "x" * 4000, encoding="utf-8")

        # When
        result = self.run_hook(
            "claude",
            event="SubagentStart",
            payload=json.dumps({"hook_event_name": "SubagentStart", "agent_type": "hei5enbug-agent-setup:scout"}),
        )

        # Then
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("context budget", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_코어_파일이_없으면_모든_컨텍스트가_실패한다(self):
        """core.md가 없으면 메인과 역할 컨텍스트 모두 부분 출력 없이 실패한다."""
        # Given
        (self.root / "instructions/session/core.md").unlink()

        # When
        results = [
            self.run_hook("claude"),
            self.run_hook(
                "claude",
                event="SubagentStart",
                payload=json.dumps({"hook_event_name": "SubagentStart", "agent_type": "hei5enbug-agent-setup:scout"}),
            ),
        ]

        # Then
        for result in results:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("core.md", result.stderr)
            self.assertEqual(result.stdout, "")

    def test_코어와_공통은_옮긴_규칙을_한_곳에만_둔다(self):
        """우선순위와 보호 규칙은 코어에만, 위임과 질문 규칙은 공통에만 있다."""
        # Given
        core = (REPO_ROOT / "instructions/session/core.md").read_text(encoding="utf-8")
        common = (REPO_ROOT / "instructions/session/common.md").read_text(encoding="utf-8")

        # When
        moved = (
            "take precedence over project instructions",
            "Prefer `rg`",
            "Never expose secrets",
            "Never use section-sign",
            "(../services.md)",
            "(../protected-values.md)",
            "(../infrastructure-access.md)",
            "(../documentation.md)",
            "(../testing.md)",
        )

        # Then
        for text in moved:
            with self.subTest(text=text):
                self.assertIn(text, core)
                self.assertNotIn(text, common)
        self.assertNotIn('An assigned worker reads only its "Assigned workers" section', common)
        self.assertIn("## Delegation", common)
        self.assertNotIn("## Delegation", core)

    def test_교체_대상_codex_역할_해시에_이전_worker와_designer가_들어_있다(self):
        """이전 버전 worker와 designer 파일의 해시는 교체 대상이고 현재 번들 파일은 교체 대상이 아니다."""
        # Given
        retired = session_context.RETIRED_CODEX_AGENTS
        expected = {
            "worker": "249b194b8c9e0cea3ff687298e58cee99ca6c330f79e04162029a60e2ecfeff0",
            "designer": "c8c525a3a7fdfb5adbff1cf7474d24dfba35527eb070f4a5206c164b248d43ed",
        }

        # When
        current = {
            name: hashlib.sha256((REPO_ROOT / "standalone-agents" / f"codex-{name}.toml").read_bytes()).hexdigest()
            for name in expected
        }

        # Then
        for name, digest in expected.items():
            with self.subTest(name=name):
                self.assertIn(digest, retired[name])
                self.assertNotIn(current[name], retired[name])

    def test_참조는_절대_경로이고_세부_본문은_불러오지_않는다(self):
        """작업 효율과 검토를 포함한 참조 11개는 절대 경로로 바뀌고 세부 본문은 시작 시 불러오지 않는다."""
        # Given
        host = "claude"

        # When
        context = self.context(self.run_hook(host))

        # Then
        links = re.findall(r"\]\(<([^>]+)>\)", context)
        self.assertEqual(len(links), 12)
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

    def test_Claude_세션은_기본_구현_경로로_Auto를_알린다(self):
        """구현 worker 옵션이 없거나 비어 있으면 Claude 세션 컨텍스트가 기본 Auto 경로 한 줄을 담는다."""
        # Given
        options = ({}, {"CLAUDE_PLUGIN_OPTION_IMPLEMENTATION_WORKER": ""})

        for extra_env in options:
            with self.subTest(extra_env=extra_env):
                # When
                context = self.context(self.run_hook("claude", extra_env=extra_env))

                # Then
                self.assertIn("Implementation worker route: Auto (`auto`).", context)
                self.assertEqual(context.count("Implementation worker route:"), 1)
                self.assertLess(len(context.encode("utf-8")), 9000)

    def test_auto_옵션은_Auto_경로를_알린다(self):
        """대소문자와 앞뒤 공백을 정규화한 auto 옵션은 Auto 경로 한 줄을 담는다."""
        # Given
        extra_env = {"CLAUDE_PLUGIN_OPTION_IMPLEMENTATION_WORKER": " AUTO "}

        # When
        context = self.context(self.run_hook("claude", extra_env=extra_env))

        # Then
        self.assertIn("Implementation worker route: Auto (`auto`).", context)
        self.assertEqual(context.count("Implementation worker route:"), 1)
        self.assertLess(len(context.encode("utf-8")), 9000)

    def test_codex_옵션은_Codex_경로를_알린다(self):
        """codex 옵션은 Codex 경로 한 줄을 담는다."""
        # Given
        extra_env = {"CLAUDE_PLUGIN_OPTION_IMPLEMENTATION_WORKER": "codex"}

        # When
        context = self.context(self.run_hook("claude", extra_env=extra_env))

        # Then
        self.assertIn("Implementation worker route: Codex (`codex`).", context)
        self.assertEqual(context.count("Implementation worker route:"), 1)
        self.assertLess(len(context.encode("utf-8")), 9000)

    def test_haiku_옵션은_worker_경로를_알린다(self):
        """대소문자와 앞뒤 공백을 정규화한 haiku 옵션은 worker 경로 한 줄을 담는다."""
        # Given
        extra_env = {"CLAUDE_PLUGIN_OPTION_IMPLEMENTATION_WORKER": " HaIku "}

        # When
        context = self.context(self.run_hook("claude", extra_env=extra_env))

        # Then
        self.assertIn("Implementation worker route: Haiku (`haiku`).", context)
        self.assertEqual(context.count("Implementation worker route:"), 1)
        self.assertLess(len(context.encode("utf-8")), 9000)

    def test_sonnet_옵션은_sonnet_worker_경로를_알린다(self):
        """대소문자와 앞뒤 공백을 정규화한 sonnet 옵션은 sonnet-worker 경로 한 줄을 담는다."""
        # Given
        extra_env = {"CLAUDE_PLUGIN_OPTION_IMPLEMENTATION_WORKER": " SoNnEt "}

        # When
        context = self.context(self.run_hook("claude", extra_env=extra_env))

        # Then
        self.assertIn("Implementation worker route: Sonnet (`sonnet`).", context)
        self.assertEqual(context.count("Implementation worker route:"), 1)
        self.assertLess(len(context.encode("utf-8")), 9000)

    def test_sol_옵션은_Sol_경로를_알린다(self):
        """대소문자와 앞뒤 공백을 정규화한 sol 옵션은 Sol 경로 한 줄을 담는다."""
        # Given
        extra_env = {"CLAUDE_PLUGIN_OPTION_IMPLEMENTATION_WORKER": " SoL "}

        # When
        context = self.context(self.run_hook("claude", extra_env=extra_env))

        # Then
        self.assertIn("Implementation worker route: Sol (`sol`).", context)
        self.assertEqual(context.count("Implementation worker route:"), 1)
        self.assertLess(len(context.encode("utf-8")), 9000)

    def test_알_수_없는_옵션은_Auto_경로를_알린다(self):
        """알 수 없는 구현 worker 옵션은 기본 Auto 경로 한 줄을 담는다."""
        # Given
        extra_env = {"CLAUDE_PLUGIN_OPTION_IMPLEMENTATION_WORKER": "unknown"}

        # When
        context = self.context(self.run_hook("claude", extra_env=extra_env))

        # Then
        self.assertIn("Implementation worker route: Auto (`auto`).", context)
        self.assertEqual(context.count("Implementation worker route:"), 1)
        self.assertLess(len(context.encode("utf-8")), 9000)

    def test_Claude_세션만_다이어그램_직접_작성_범위를_메인에_맡긴다(self):
        """Claude 메인 컨텍스트는 문서 안 다이어그램과 노드 일곱 개 이하 흐름도를 메인이 맡는다고 하고 Codex는 그렇지 않다."""
        # Given
        sentence = "makes new SVG or PNG flowcharts of up to seven nodes; other UI code and visual design go to the designer"

        # When
        claude = " ".join(self.context(self.run_hook("claude")).split())
        codex = " ".join(self.context(self.run_hook("codex")).split())

        # Then
        self.assertIn("The main session draws ASCII and Mermaid diagrams in documents, edits existing SVG diagrams", claude)
        self.assertIn(sentence, claude)
        self.assertIn("except the kinds the host session file assigns to the main session", claude)
        self.assertNotIn("seven nodes", codex)

    def test_Claude_SessionStart는_옵션으로_mod_역할_고정을_주장하지_않는다(self):
        """role_pinning 옵션 값과 무관하게 Claude 시작 문맥은 mod 고정 활성화를 주장하지 않고 예산을 지킨다."""
        # Given
        options = (None, "", "true", "false", " OFF ", "0", "no")

        for option in options:
            with self.subTest(option=option):
                extra_env = {} if option is None else {"CLAUDE_PLUGIN_OPTION_ROLE_PINNING": option}

                # When
                context = self.context(self.run_hook("claude", extra_env=extra_env))

                # Then
                self.assertNotIn("hei5enbug-agent-setup mod: role pinning active", context)
                self.assertNotIn("Role pinning: active (`role_pinning`).", context)
                self.assertLess(len(context.encode("utf-8")), 9000)

    def test_Codex와_역할_컨텍스트는_역할_고정_줄을_받지_않는다(self):
        """Codex 세션과 두 호스트의 역할 컨텍스트에는 역할 고정 줄이 없다."""
        # Given
        agents = {"claude": ("hei5enbug-agent-setup:worker", "hei5enbug-agent-setup:scout"), "codex": ("worker", "scout")}

        # When
        contexts = [self.context(self.run_hook("codex"))]
        contexts += [self.subagent_context(host, name) for host, names in agents.items() for name in names]
        contexts.append(self.context(self.run_hook("claude", extra_env={"HEI5ENBUG_ASSIGNED_ROLE": "worker"})))

        # Then
        for context in contexts:
            self.assertNotIn("Role pinning", context)

    def test_Claude_세션은_검토_모델_설정값_한_줄을_담는다(self):
        """review_model 옵션이 비면 기본 gpt-6-astra, 정규화한 허용 ID면 그 값을 한 줄로 담는다."""
        # Given
        cases = {
            None: "gpt-6-astra",
            "": "gpt-6-astra",
            " Claude-Opus-5-5 ": "claude-opus-5-5",
            "gpt-6.1-sol": "gpt-6.1-sol",
        }

        for option, expected in cases.items():
            with self.subTest(option=option):
                extra_env = {} if option is None else {"CLAUDE_PLUGIN_OPTION_REVIEW_MODEL": option}

                # When
                context = self.context(self.run_hook("claude", extra_env=extra_env))

                # Then
                self.assertIn(f"Review model: `{expected}`.", context)
                self.assertEqual(context.count("Review model:"), 1)
                self.assertLess(len(context.encode("utf-8")), session_context.MAX_CONTEXT_BYTES)

    def test_허용_목록에_없는_검토_모델은_기본값으로_바꾼다(self):
        """알 수 없는 review_model 값은 기본 gpt-6-astra 한 줄로 안전하게 바뀐다."""
        # Given
        extra_env = {"CLAUDE_PLUGIN_OPTION_REVIEW_MODEL": "gpt-9-unknown"}

        # When
        context = self.context(self.run_hook("claude", extra_env=extra_env))

        # Then
        self.assertIn("Review model: `gpt-6-astra`.", context)
        self.assertNotIn("gpt-9-unknown", context)

    def test_검토_모델_선택지는_모델_고정값_일곱_개와_같다(self):
        """review_model 선택지와 기본값은 role_runner의 허용 모델과 같고 최신 고정 ID로만 이뤄진다."""
        # Given
        spec = importlib.util.spec_from_file_location("model_pins", REPO_ROOT / "tests/test_model_pins.py")
        pins = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pins)
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import role_runner

        # When
        configured = json.loads((REPO_ROOT / ".claude-plugin/plugin.json").read_text())["userConfig"]["review_model"]

        # Then
        self.assertEqual(set(session_context.REVIEW_MODELS), set(pins.PINS.values()))
        self.assertEqual(session_context.REVIEW_MODELS, role_runner.REVIEW_MODELS)
        self.assertEqual(configured["options"], list(session_context.REVIEW_MODELS))
        self.assertEqual(configured["default"], session_context.DEFAULT_REVIEW_MODEL)
        self.assertEqual(session_context.DEFAULT_REVIEW_MODEL, role_runner.DEFAULT_REVIEW_MODEL)

    def test_Codex_호스트는_검토_모델_줄을_받지_않는다(self):
        """Codex 세션 컨텍스트에는 Claude 전용 검토 모델 줄이 없고, 서브에이전트 컨텍스트에도 없다."""
        # Given
        extra_env = {"CLAUDE_PLUGIN_OPTION_REVIEW_MODEL": "claude-opus-5-5"}

        # When
        codex = self.context(self.run_hook("codex", extra_env=extra_env))
        claude_subagent = self.subagent_context("claude", "hei5enbug-agent-setup:scout")

        # Then
        self.assertNotIn("(`review_model`)", codex)
        self.assertNotIn("Review model", claude_subagent)

    def test_Codex_호스트는_구현_경로_줄을_받지_않는다(self):
        """Codex 세션 컨텍스트에는 Claude 전용 구현 경로 줄이 없다."""
        # Given
        extra_env = {"CLAUDE_PLUGIN_OPTION_IMPLEMENTATION_WORKER": "sonnet"}

        # When
        context = self.context(self.run_hook("codex", extra_env=extra_env))

        # Then
        self.assertNotIn("Implementation worker route", context)

    def test_계획_라우팅은_트리거만_싣고_계획_정의와_절차는_참조에_둔다(self):
        """세션 문맥에는 계획 트리거와 참조 링크만 있고, 계획 정의와 단계 절차는 구현 계획 참조에만 있다."""
        # Given
        planning = " ".join((REPO_ROOT / "instructions/implementation-planning.md").read_text(encoding="utf-8").split())

        # When
        context = self.context(self.run_hook("codex"))

        # Then
        self.assertIn("This is an explicit exception to the preceding trigger boundary", context)
        self.assertIn("instructions/implementation-planning.md", context)
        self.assertIn("instructions/independent-model-validation.md", context)
        self.assertNotIn("An implementation plan must let an executor proceed", context)
        self.assertNotIn("## 1. Intent and scope freeze", context)
        self.assertIn("lets an executor make the requested change without adding design decisions", planning)

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
        path = self.root / "docs/ko/instructions/session/common.ko.md"
        path.write_text(path.read_text() + "\nKOREAN MIRROR SENTINEL\n")
        self.assertNotIn("KOREAN MIRROR SENTINEL", self.context(self.run_hook()))

    def test_missing_reference_reports_failure_without_partial_context(self):
        (self.root / "instructions/protected-values.md").unlink()
        result = self.run_hook()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("instructions were not loaded", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_인프라_접근_규칙은_조건부_참조로만_연결하고_본문은_컨텍스트에_넣지_않는다(self):
        """코어는 인프라 접근 규칙 파일로 연결만 하고, 그 파일이 없으면 부분 컨텍스트 없이 실패한다."""
        # Given
        guide = (self.root / "instructions/infrastructure-access.md").read_text(encoding="utf-8")

        # When
        loaded = self.context(self.run_hook())
        (self.root / "instructions/infrastructure-access.md").unlink()
        missing = self.run_hook()

        # Then
        self.assertIn("infrastructure-access.md", loaded)
        self.assertIn("protected-values.md", loaded)
        self.assertNotIn("EXPLAIN ANALYZE", loaded)
        self.assertIn("Never run `EXPLAIN ANALYZE`", guide)
        self.assertLessEqual(len(guide.splitlines()), 25)
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(missing.stdout, "")

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

    def test_모델_평가_참조가_없으면_부분_컨텍스트_없이_실패한다(self):
        """모델 평가 참조 파일이 없으면 훅은 일부 컨텍스트도 내보내지 않고 실패를 알린다."""
        # Given
        (self.root / "instructions/model-evaluation.md").unlink()

        # When
        result = self.run_hook()

        # Then
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("instructions were not loaded", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_실패와_유지보수_참조가_없으면_부분_컨텍스트_없이_실패한다(self):
        """실패와 유지보수 참조 파일이 없으면 훅은 일부 컨텍스트도 내보내지 않고 실패를 알린다."""
        # Given
        (self.root / "instructions/failure-and-maintenance.md").unlink()

        # When
        result = self.run_hook()

        # Then
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("instructions were not loaded", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_위임_참조가_없으면_구현_에이전트_컨텍스트는_실패하고_메인은_영향받지_않는다(self):
        """구현 위임 참조 파일이 없으면 구현 에이전트 시작은 부분 컨텍스트 없이 실패하고 메인 세션은 영향받지 않는다."""
        # Given
        (self.root / "instructions/implementation-delegation.md").unlink()

        # When
        failed = self.run_hook(
            "claude",
            event="SubagentStart",
            payload=json.dumps({"hook_event_name": "SubagentStart", "agent_type": "hei5enbug-agent-setup:worker"}),
        )
        main = self.context(self.run_hook("claude"))

        # Then
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(failed.stdout, "")
        self.assertIn("implementation-delegation.md", failed.stderr)
        self.assertIn("# Common", main)

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

    def test_codex_session_retires_only_an_unmodified_researcher_from_an_earlier_version(self):
        """이전 버전이 쓴 researcher.toml은 바이트 단위로 같을 때만 제거하고, 고친 파일은 그대로 둔다."""
        # Given
        shipped = LEGACY_RESEARCHER.read_bytes()
        self.assertIn(hashlib.sha256(shipped).hexdigest(), RETIRED_RESEARCHER_DIGESTS)
        self.researcher.parent.mkdir(parents=True)
        self.researcher.write_bytes(shipped)

        # When
        self.context(self.run_hook("codex"))

        # Then
        self.assertFalse(self.researcher.exists())

        # Given
        self.researcher.write_bytes(shipped + b"# edited by the user\n")

        # When
        self.context(self.run_hook("codex"))

        # Then
        self.assertEqual(self.researcher.read_bytes(), shipped + b"# edited by the user\n")

    def test_Codex_세션은_누락된_designer_역할을_설치하고_사용자_파일은_그대로_둔다(self):
        """Codex 세션은 designer 역할이 없을 때 번들 정의를 설치하고, 사용자가 작성한 파일은 덮어쓰지 않는다."""
        # Given
        self.assertFalse(self.designer.exists())

        # When
        self.context(self.run_hook("codex"))
        installed = self.designer.read_text(encoding="utf-8")
        custom = 'name = "designer"\ndescription = "user-owned"\n'
        self.designer.write_text(custom, encoding="utf-8")
        self.context(self.run_hook("codex"))

        # Then
        self.assertEqual(installed, (REPO_ROOT / "standalone-agents/codex-designer.toml").read_text(encoding="utf-8"))
        self.assertEqual(self.designer.read_text(encoding="utf-8"), custom)

    def test_Codex_세션은_누락된_reviewer_역할을_설치한다(self):
        """Codex 세션은 reviewer 역할이 없을 때 모델 없는 읽기 전용 번들 정의를 설치한다."""
        # Given
        self.reviewer.parent.mkdir(parents=True)
        self.assertFalse(self.reviewer.exists())

        # When
        self.context(self.run_hook("codex"))

        # Then
        role = self.reviewer.read_text(encoding="utf-8")
        bundled = (REPO_ROOT / "standalone-agents/codex-reviewer.toml").read_text(encoding="utf-8")
        self.assertEqual(role, bundled)
        self.assertIn('sandbox_mode = "read-only"', role)
        self.assertNotIn('model = ', role)

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
        """Codex 세션은 사용자가 작성한 researcher 역할을 덮어쓰지도 지우지도 않는다."""
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

    def pinned_effort_worker(self) -> bytes:
        bundled = (REPO_ROOT / "standalone-agents/codex-worker.toml").read_text(encoding="utf-8")
        line = 'model_reasoning_effort = "xhigh"\n'
        head, tail = bundled.split("\n", 2)[:2], bundled.split("\n", 2)[2]
        return ("\n".join(head) + "\n" + line + tail).encode("utf-8")

    def test_effort를_고정하던_worker_역할은_수정하지_않았을_때만_바꾸고_고친_파일은_남긴다(self):
        """spawn 값을 덮어쓰던 effort 줄이 있는 worker.toml은 바이트가 같을 때만 현재 파일로 바꾸고, 고친 파일은 그대로 둔다."""
        # Given
        shipped = self.pinned_effort_worker()
        self.assertEqual(PINNED_EFFORT_WORKER_DIGEST, hashlib.sha256(shipped).hexdigest())
        bundled = (REPO_ROOT / "standalone-agents/codex-worker.toml").read_bytes()
        self.assertNotIn(b"model_reasoning_effort", bundled)
        edited = shipped + b"# edited by the user\n"
        self.worker.parent.mkdir(parents=True)
        self.worker.write_bytes(shipped)

        # When
        self.context(self.run_hook("codex"))
        replaced = self.worker.read_bytes()
        self.worker.write_bytes(edited)
        self.context(self.run_hook("codex"))

        # Then
        self.assertEqual(bundled, replaced)
        self.assertEqual(edited, self.worker.read_bytes())

    def test_Claude_세션은_worker_모델과_effort_옵션을_알린다(self):
        """Claude 세션 컨텍스트는 구현 경로 줄 다음에 옵션으로 고른 worker 모델과 effort 줄을 담는다."""
        # Given
        extra_env = {
            "CLAUDE_PLUGIN_OPTION_WORKER_MODEL": "claude-sonnet-5-5",
            "CLAUDE_PLUGIN_OPTION_WORKER_EFFORT": "xhigh",
        }

        # When
        context = self.context(self.run_hook("claude", extra_env=extra_env))

        # Then
        self.assertIn(
            "Implementation worker route: Auto (`auto`).\nWorker agent model: `claude-sonnet-5-5` at `xhigh`.\n", context
        )
        self.assertLess(len(context.encode("utf-8")), 9000)

    def test_Claude_세션은_옵션이_없으면_기본_worker_모델을_알리고_잘못된_값은_알림으로_적는다(self):
        """옵션이 없으면 매니페스트 기본값을 알리고, 목록에 없는 모델은 기본값으로 되돌려 괄호 알림에 값을 적는다."""
        # Given
        self.use_short_root()
        invalid = {"CLAUDE_PLUGIN_OPTION_WORKER_MODEL": "claude-unknown-9"}

        # When
        default = self.context(self.run_hook("claude"))
        ignored = self.context(self.run_hook("claude", extra_env=invalid))

        # Then
        self.assertIn("Worker agent model: `claude-haiku-5-5` at `high`.\n", default)
        self.assertIn("Worker agent model: `claude-haiku-5-5` at `high`. (Ignored worker_model 'claude-unknown-9'", ignored)
        self.assertLess(len(ignored.encode("utf-8")), 9000)

    def test_Claude_세션은_역할_고정이_꺼져_있으면_설정값_대신_기본_모델과_알림을_알린다(self):
        """role_pinning이 꺼지면 설정한 opus와 xhigh는 적용되지 않으므로 기본 쌍과 역할 고정 알림을 적고, 켜져 있으면 설정한 쌍을 적는다."""
        # Given
        self.use_short_root()
        configured = {
            "CLAUDE_PLUGIN_OPTION_WORKER_MODEL": "claude-opus-5-5",
            "CLAUDE_PLUGIN_OPTION_WORKER_EFFORT": "xhigh",
        }

        # When
        off = self.context(self.run_hook("claude", extra_env={**configured, "CLAUDE_PLUGIN_OPTION_ROLE_PINNING": "false"}))
        on = self.context(self.run_hook("claude", extra_env={**configured, "CLAUDE_PLUGIN_OPTION_ROLE_PINNING": "true"}))

        # Then
        self.assertIn(
            "Worker agent model: `claude-haiku-5-5` at `high`. "
            "(role pinning is off, so the worker runs on its definition's model)\n",
            off,
        )
        self.assertIn("Worker agent model: `claude-opus-5-5` at `xhigh`.\n", on)

    def test_알림이_컨텍스트_한도를_넘기게_하면_알림만_빼고_세션_지침은_그대로_불러온다(self):
        """긴 설치 경로에서 알림 때문에 한도를 넘으면 알림 괄호만 생략하고 지침 로드는 실패하지 않는다."""
        # Given
        extra_env = {"CLAUDE_PLUGIN_OPTION_WORKER_MODEL": "x" * 40}

        # When
        context = self.context(self.run_hook("claude", extra_env=extra_env))

        # Then
        self.assertIn("Worker agent model: `claude-haiku-5-5` at `high`.\n", context)
        self.assertLessEqual(len(context.encode("utf-8")), 9000)

    def test_Codex_세션은_저장된_옵션의_Codex_worker_모델을_알린다(self):
        """Codex 세션 컨텍스트는 Claude 사용자 설정에 저장된 Codex worker 값을 담고, 환경 변수가 있으면 그 값이 이긴다."""
        # Given
        config = self.base / "claude config"
        self.write_json(config / "settings.json", {"pluginConfigs": {"hei5enbug-agent-setup@hei5enbug": {"options": {
            "codex_worker_model": "gpt-6.1-sol", "codex_worker_effort": "high"}}}})
        env = {"CLAUDE_CONFIG_DIR": str(config)}

        # When
        saved = self.context(self.run_hook("codex", extra_env=env))
        overridden = self.context(self.run_hook("codex", extra_env={**env, "HEI5ENBUG_CODEX_WORKER_EFFORT": "xhigh"}))

        # Then
        self.assertIn("Codex worker model: `gpt-6.1-sol` at `high`.\n", saved)
        self.assertIn("Codex worker model: `gpt-6.1-sol` at `xhigh`.\n", overridden)
        self.assertNotIn("Worker agent model", saved)
        self.assertLess(len(saved.encode("utf-8")), 9000)

    def test_Codex_세션_시작은_알린_worker_쌍을_그_세션_기록으로_남긴다(self):
        """세션 id가 있으면 알린 gpt-6.1-sol과 high를 상태 폴더의 worker-settings 기록에 남기고 Claude 설정 파일은 쓰지 않는다."""
        # Given
        config = self.base / "claude config"
        self.write_json(config / "settings.json", {"pluginConfigs": {"hei5enbug-agent-setup@hei5enbug": {"options": {
            "codex_worker_model": "gpt-6.1-sol", "codex_worker_effort": "high"}}}})
        before = (config / "settings.json").read_bytes()
        payload = json.dumps({"hook_event_name": "SessionStart", "source": "startup", "session_id": "session-one"})

        # When
        result = self.run_hook("codex", payload=payload, extra_env={"CLAUDE_CONFIG_DIR": str(config)})

        # Then
        record = self.base / "state" / "hei5enbug-agent-setup" / "worker-settings" / "codex-session-one.json"
        self.assertIn("Codex worker model: `gpt-6.1-sol` at `high`.\n", self.context(result))
        self.assertEqual({"model": "gpt-6.1-sol", "effort": "high"}, json.loads(record.read_text(encoding="utf-8")))
        self.assertEqual(before, (config / "settings.json").read_bytes())

    def test_Codex_세션_시작은_상태_폴더에_쓸_수_없어도_컨텍스트를_정상_출력한다(self):
        """XDG_STATE_HOME이 일반 파일을 가리켜 기록이 실패해도 SessionStart는 성공하고 worker 모델을 알린다."""
        # Given
        blocked = self.base / "blocked"
        blocked.write_text("file", encoding="utf-8")
        payload = json.dumps({"hook_event_name": "SessionStart", "source": "startup", "session_id": "session-one"})

        # When
        result = self.run_hook("codex", payload=payload, extra_env={"XDG_STATE_HOME": str(blocked)})

        # Then
        self.assertIn("Codex worker model: `gpt-5.6-luna` at `xhigh`.\n", self.context(result))

    def test_Codex_세션은_설정이_없으면_기본_Codex_worker_모델을_알린다(self):
        """저장된 설정이 없으면 매니페스트 기본값 gpt-5.6-luna와 xhigh를 알리고 알림은 붙지 않는다."""
        # Given
        env = {"CLAUDE_CONFIG_DIR": str(self.base / "empty claude config")}

        # When
        context = self.context(self.run_hook("codex", extra_env=env))

        # Then
        self.assertIn("Codex worker model: `gpt-5.6-luna` at `xhigh`.\n", context)

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
        mirror = other / "docs/ko/instructions/session/common.ko.md"
        mirror.write_text(mirror.read_text(encoding="utf-8") + "\n번역 수정\n", encoding="utf-8")
        after_mirror = module.instructions_digest(other)
        rule = other / "instructions/testing.md"
        rule.write_text(rule.read_text(encoding="utf-8") + "\nNew rule.\n", encoding="utf-8")
        after_rule = module.instructions_digest(other)

        # Then
        self.assertEqual(original, moved)
        self.assertEqual(original, after_mirror)
        self.assertNotEqual(original, after_rule)

    def test_repository_has_agents_md_without_claude_md(self):
        """저장소 루트에는 AGENTS.md만 있고, Claude Code가 AGENTS.md를 직접 읽도록 CLAUDE.md는 없다."""
        # Given
        root = REPO_ROOT

        # When
        names = {path.name for path in root.iterdir()}

        # Then
        self.assertIn("AGENTS.md", names)
        self.assertNotIn("CLAUDE.md", names)


BLOCK = (
    "<!-- hei5enbug:subagents -->\n"
    "When hei5enbug-agent-setup is active, use subagents according to its situation-based delegation rules.\n"
    "<!-- /hei5enbug:subagents -->\n"
)
FLAG = "default_mode_request_user_input"
FAKE_CODEX = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_CODEX_LOG"
case " $FAKE_CODEX_SLOW " in *" $2 "*) sleep 6;; esac
case " $FAKE_CODEX_FAIL " in *" $2 "*) exit 1;; esac
if [ "$2" = "list" ]; then cat "$FAKE_CODEX_LIST"; fi
exit 0
"""


class CodexAutoSettingsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "plugin"
        self.root.mkdir()
        for name in ("scripts", ".codex-plugin", ".claude-plugin", "config"):
            shutil.copytree(REPO_ROOT / name, self.root / name)
        session = self.root / "instructions" / "session"
        session.mkdir(parents=True)
        for name, text in (
            ("core.md", "# Core\nNever expose secrets.\n"),
            ("common.md", "# Common\n"),
            ("codex.md", "# Codex only\n"),
            ("claude-code.md", "# Claude Code only\n"),
        ):
            (session / name).write_text(text, encoding="utf-8")
        self.cwd = self.base / "project"
        self.cwd.mkdir()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.codex_home = self.base / "codex home"
        self.agents = self.codex_home / "AGENTS.md"
        self.data = self.base / "plugin data"
        self.state = self.data / "codex-auto-settings.json"
        self.log = self.base / "codex.log"
        self.listing = self.base / "features.txt"
        self.set_flag("false")
        fake = self.bin / "codex"
        fake.write_text(FAKE_CODEX, encoding="utf-8")
        fake.chmod(0o755)

    def set_flag(self, value):
        self.listing.write_text(
            f"fast_mode                            stable             true\n{FLAG}          under development  {value}\n",
            encoding="utf-8",
        )

    def calls(self):
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def run_hook(self, host="codex", event="SessionStart", extra_env=None, with_codex=True):
        env = {
            "PATH": f"{self.bin}{os.pathsep}{os.defpath}" if with_codex else os.defpath,
            "CLAUDE_PLUGIN_ROOT": str(self.root),
            "CODEX_HOME": str(self.codex_home),
            "PLUGIN_DATA": str(self.data),
            "FAKE_CODEX_LOG": str(self.log),
            "FAKE_CODEX_LIST": str(self.listing),
        }
        if host == "codex":
            env["PLUGIN_ROOT"] = str(self.root)
        env.update(extra_env or {})
        return subprocess.run(
            [sys.executable, str(self.root / "scripts/session_context.py")],
            cwd=self.cwd,
            env=env,
            input=json.dumps({"hook_event_name": event, "source": "startup"}),
            text=True,
            capture_output=True,
            timeout=20,
        )

    def assert_context_loaded(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertIn("Never expose secrets", output["additionalContext"])

    def saved(self):
        return json.loads(self.state.read_text(encoding="utf-8"))

    def test_Codex_세션_시작은_하위_에이전트_블록을_빈_줄_뒤에_추가한다(self):
        """기존 AGENTS.md 내용은 그대로 두고 블록을 빈 줄 하나 뒤에 붙인다."""
        # Given
        self.codex_home.mkdir()
        self.agents.write_text("# 내 규칙\n- 한국어로 답한다\n", encoding="utf-8")

        # When
        result = self.run_hook()

        # Then
        self.assert_context_loaded(result)
        self.assertEqual(self.agents.read_text(encoding="utf-8"), "# 내 규칙\n- 한국어로 답한다\n\n" + BLOCK)

    def test_AGENTS_파일과_폴더가_없으면_만들고_블록만_쓴다(self):
        """Codex 설정 폴더가 없어도 파일을 만들어 블록만 기록한다."""
        # Given
        self.assertFalse(self.codex_home.exists())

        # When
        result = self.run_hook()

        # Then
        self.assert_context_loaded(result)
        self.assertEqual(self.agents.read_text(encoding="utf-8"), BLOCK)

    def test_블록이_이미_있으면_파일을_다시_쓰지_않는다(self):
        """사용자가 블록 안팎을 손봤어도 블록이 있으면 그대로 둔다."""
        # Given
        self.codex_home.mkdir()
        existing = "앞\n\n" + BLOCK.replace("use subagents", "use subagents carefully") + "\n뒤\n"
        self.agents.write_text(existing, encoding="utf-8")

        # When
        self.run_hook()

        # Then
        self.assertEqual(self.agents.read_text(encoding="utf-8"), existing)

    def test_토글을_끄면_블록과_앞의_빈_줄만_지우고_나머지를_보존한다(self):
        """블록 앞뒤의 사용자 텍스트는 한 글자도 바뀌지 않는다."""
        # Given
        self.codex_home.mkdir()
        original = "# 앞 규칙\n\n내용\n"
        self.agents.write_text(original + "\n" + BLOCK + "\n# 뒤 규칙\n", encoding="utf-8")

        # When
        result = self.run_hook(extra_env={"HEI5ENBUG_SUBAGENT_POLICY": "off"})

        # Then
        self.assert_context_loaded(result)
        self.assertEqual(self.agents.read_text(encoding="utf-8"), original + "\n# 뒤 규칙\n")

    def test_추가했던_블록을_끄면_원래_파일로_돌아간다(self):
        """켠 뒤 끄면 추가 전 내용과 바이트까지 같아진다."""
        # Given
        self.codex_home.mkdir()
        original = "# 내 규칙\n"
        self.agents.write_text(original, encoding="utf-8")
        self.run_hook()
        self.assertNotEqual(self.agents.read_text(encoding="utf-8"), original)

        # When
        self.run_hook(extra_env={"HEI5ENBUG_SUBAGENT_POLICY": "off"})

        # Then
        self.assertEqual(self.agents.read_text(encoding="utf-8"), original)

    def test_토글이_꺼져_있고_AGENTS_파일이_없으면_만들지_않는다(self):
        """끄기 요청은 파일이나 폴더를 새로 만들지 않는다."""
        # When
        self.run_hook(extra_env={"HEI5ENBUG_SUBAGENT_POLICY": "off"})

        # Then
        self.assertFalse(self.agents.exists())

    def test_질문_플래그가_꺼져_있으면_켜고_플러그인이_켰다고_기록한다(self):
        """features list가 false이면 enable을 한 번 실행하고 상태 파일에 기록한다."""
        # Given
        self.set_flag("false")

        # When
        result = self.run_hook()

        # Then
        self.assert_context_loaded(result)
        self.assertEqual(self.calls(), ["features list", f"features enable {FLAG}"])
        saved = self.saved()
        self.assertTrue(saved["ask_tool_enabled_by_plugin"])
        self.assertEqual(saved["codex_ask_tool"], {"value": True, "ok": True})
        self.assertEqual(saved["subagent_policy"], {"value": True, "ok": True})
        self.assertEqual(saved["version"], json.loads((REPO_ROOT / ".codex-plugin/plugin.json").read_text())["version"])

    def test_질문_플래그를_사용자가_이미_켰으면_enable하지_않는다(self):
        """이미 true이면 명령을 더 실행하지 않고 플러그인이 켰다고 기록하지 않는다."""
        # Given
        self.set_flag("true")

        # When
        self.run_hook()

        # Then
        self.assertEqual(self.calls(), ["features list"])
        self.assertFalse(self.saved()["ask_tool_enabled_by_plugin"])
        self.assertTrue(self.saved()["codex_ask_tool"]["ok"])

    def test_토글을_끄면_플러그인이_켠_플래그만_끈다(self):
        """플러그인이 켠 기록이 있으면 disable을 실행하고 기록을 지운다."""
        # Given
        self.run_hook()
        self.set_flag("true")
        self.log.unlink()

        # When
        result = self.run_hook(extra_env={"HEI5ENBUG_CODEX_ASK_TOOL": "off"})

        # Then
        self.assert_context_loaded(result)
        self.assertEqual(self.calls(), [f"features disable {FLAG}"])
        self.assertFalse(self.saved()["ask_tool_enabled_by_plugin"])
        self.assertEqual(self.saved()["codex_ask_tool"], {"value": False, "ok": True})

    def test_토글을_꺼도_사용자가_직접_켠_플래그는_그대로_둔다(self):
        """플러그인이 켠 기록이 없으면 disable도 list도 실행하지 않는다."""
        # Given
        self.set_flag("true")
        self.run_hook()
        self.log.unlink()

        # When
        self.run_hook(extra_env={"HEI5ENBUG_CODEX_ASK_TOOL": "off"})

        # Then
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.saved()["codex_ask_tool"], {"value": False, "ok": True})

    def test_토글을_끄고_시작하면_질문_플래그_명령을_실행하지_않는다(self):
        """질문 토글이 꺼져 있으면 처음부터 codex 명령을 부르지 않는다."""
        # When
        self.run_hook(extra_env={"HEI5ENBUG_CODEX_ASK_TOOL": "false"})

        # Then
        self.assertEqual(self.calls(), [])

    def test_명령이_실패하면_성공으로_기록하지_않고_다음_세션에서_다시_시도한다(self):
        """enable이 실패한 세션은 실패로 남기고, 다음 세션에서 성공하면 그때 기록한다."""
        # Given
        self.set_flag("false")

        # When
        first = self.run_hook(extra_env={"FAKE_CODEX_FAIL": "enable"})
        failed_state = self.saved()
        second = self.run_hook()

        # Then
        self.assert_context_loaded(first)
        self.assertEqual(failed_state["codex_ask_tool"], {"value": True, "ok": False})
        self.assertFalse(failed_state["ask_tool_enabled_by_plugin"])
        self.assertEqual(failed_state["subagent_policy"]["ok"], True)
        self.assert_context_loaded(second)
        self.assertEqual(
            self.calls(),
            ["features list", f"features enable {FLAG}", "features list", f"features enable {FLAG}"],
        )
        self.assertEqual(self.saved()["codex_ask_tool"], {"value": True, "ok": True})
        self.assertTrue(self.saved()["ask_tool_enabled_by_plugin"])

    def test_목록_명령이_실패하거나_플래그가_없으면_아무것도_하지_않는다(self):
        """list 실패와 플래그 부재는 enable 없이 조용히 넘어가며 성공으로 기록하지 않는다."""
        for name, extra, listing in (
            ("실패", {"FAKE_CODEX_FAIL": "list"}, None),
            ("플래그 없음", {}, "fast_mode  stable  true\n"),
        ):
            with self.subTest(name):
                # Given
                self.log.unlink(missing_ok=True)
                self.state.unlink(missing_ok=True)
                if listing is not None:
                    self.listing.write_text(listing, encoding="utf-8")

                # When
                result = self.run_hook(extra_env=extra)

                # Then
                self.assert_context_loaded(result)
                self.assertEqual(self.calls(), ["features list"])
                self.assertEqual(self.saved()["codex_ask_tool"]["ok"], False)

    def test_codex_실행_파일이_없어도_지침은_정상_출력된다(self):
        """codex가 PATH에 없으면 플래그는 건드리지 않고 지침과 AGENTS 블록 처리만 끝낸다."""
        # When
        result = self.run_hook(with_codex=False)

        # Then
        self.assert_context_loaded(result)
        self.assertEqual(self.agents.read_text(encoding="utf-8"), BLOCK)
        self.assertEqual(self.saved()["codex_ask_tool"]["ok"], False)

    def test_명령이_3초를_넘기면_기다리지_않고_실패로_남긴다(self):
        """시간 초과한 codex 명령은 성공으로 기록하지 않고 지침 출력도 막지 않는다."""
        # When
        result = self.run_hook(extra_env={"FAKE_CODEX_SLOW": "list"})

        # Then
        self.assert_context_loaded(result)
        self.assertEqual(self.saved()["codex_ask_tool"]["ok"], False)

    def test_같은_버전과_같은_토글로_성공한_설정은_다음_세션에서_건너뛴다(self):
        """성공한 설정은 AGENTS.md도 codex도 다시 만지지 않는다."""
        # Given
        self.run_hook()
        self.agents.write_text("사용자가 블록을 지웠다\n", encoding="utf-8")
        self.log.unlink()

        # When
        self.run_hook()

        # Then
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.agents.read_text(encoding="utf-8"), "사용자가 블록을 지웠다\n")

    def test_토글_값이_바뀌면_성공한_설정도_다시_처리한다(self):
        """같은 버전이어도 토글 값이 달라지면 해당 설정만 다시 실행한다."""
        # Given
        self.run_hook()
        self.log.unlink()

        # When
        self.run_hook(extra_env={"HEI5ENBUG_SUBAGENT_POLICY": "off"})

        # Then
        self.assertEqual(self.calls(), [])
        self.assertNotIn("hei5enbug:subagents", self.agents.read_text(encoding="utf-8"))
        self.assertEqual(self.saved()["subagent_policy"], {"value": False, "ok": True})

    def test_플러그인_버전이_바뀌면_성공한_설정도_다시_처리한다(self):
        """버전이 달라지면 두 설정을 다시 확인하고, 플러그인이 켠 기록은 유지한다."""
        # Given
        self.run_hook()
        manifest = self.root / ".codex-plugin/plugin.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["version"] = "9.9.9"
        manifest.write_text(json.dumps(data), encoding="utf-8")
        self.agents.write_text("", encoding="utf-8")
        self.set_flag("true")
        self.log.unlink()

        # When
        self.run_hook()

        # Then
        self.assertEqual(self.agents.read_text(encoding="utf-8"), BLOCK)
        self.assertEqual(self.calls(), ["features list"])
        self.assertEqual(self.saved()["version"], "9.9.9")
        self.assertTrue(self.saved()["ask_tool_enabled_by_plugin"])

    def test_데이터_폴더가_없으면_캐시_없이_매번_처리한다(self):
        """PLUGIN_DATA와 CLAUDE_PLUGIN_DATA가 모두 없으면 상태 파일을 만들지 않고 세션마다 확인한다."""
        # Given
        env = {"PLUGIN_DATA": ""}

        # When
        self.run_hook(extra_env=env)
        self.run_hook(extra_env=env)

        # Then
        self.assertFalse(self.state.exists())
        self.assertEqual(self.calls().count("features list"), 2)

    def test_CLAUDE_PLUGIN_DATA를_대체_위치로_쓴다(self):
        """PLUGIN_DATA가 없으면 CLAUDE_PLUGIN_DATA 아래에 상태를 저장한다."""
        # Given
        fallback = self.base / "fallback data"

        # When
        self.run_hook(extra_env={"PLUGIN_DATA": "", "CLAUDE_PLUGIN_DATA": str(fallback)})

        # Then
        self.assertTrue((fallback / "codex-auto-settings.json").is_file())

    def test_Claude_호스트와_하위_에이전트_시작은_설정을_건드리지_않는다(self):
        """Claude 호스트의 시작과 Codex의 SubagentStart는 파일도 codex 명령도 쓰지 않는다."""
        for host, event in (("claude", "SessionStart"), ("claude", "SubagentStart"), ("codex", "SubagentStart")):
            with self.subTest(host=host, event=event):
                # When
                result = self.run_hook(host, event)

                # Then
                self.assert_context_loaded(result)
                self.assertFalse(self.agents.exists())
                self.assertFalse(self.state.exists())
                self.assertEqual(self.calls(), [])

    def test_AGENTS_파일을_쓸_수_없어도_지침은_출력되고_다음에_다시_시도한다(self):
        """AGENTS.md 쓰기가 막히면 실패로 기록하고 지침 출력은 그대로이며, 막힘이 풀리면 다음 세션에서 성공한다."""
        # Given
        self.codex_home.mkdir()
        self.agents.mkdir()

        # When
        first = self.run_hook()
        failed = self.saved()["subagent_policy"]
        self.agents.rmdir()
        self.run_hook()

        # Then
        self.assert_context_loaded(first)
        self.assertEqual(failed, {"value": True, "ok": False})
        self.assertEqual(self.agents.read_text(encoding="utf-8"), BLOCK)
        self.assertEqual(self.saved()["subagent_policy"], {"value": True, "ok": True})


if __name__ == "__main__":
    unittest.main()
