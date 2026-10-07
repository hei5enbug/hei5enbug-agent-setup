"""Structural checks for the Claude Code worker definition and adapter.

These checks confirm the shipped metadata and the stated host policy. They do not prove that a live
Claude Code session selects the model or follows the policy; native trials cover that.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER = REPO_ROOT / "agents/worker.md"
WORKER_MIRROR = REPO_ROOT / "agents/ko/worker.ko.md"
CLAUDE_AGENTS = REPO_ROOT / "instructions/claude-agents.md"
PLUGIN_MANIFEST = REPO_ROOT / ".claude-plugin/plugin.json"
UNSUPPORTED_FIELDS = {
    "tools",
    "permissionMode",
    "isolation",
    "skills",
    "hooks",
    "mcpServers",
    "background",
    "memory",
    "initialPrompt",
}


def split_definition(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if match is None:
        raise AssertionError(f"missing frontmatter: {path}")
    return yaml.safe_load(match[1]), match[2]


def implementation_section() -> str:
    text = CLAUDE_AGENTS.read_text(encoding="utf-8")
    return " ".join(text.split("## Implementation", 1)[1].split())


class ClaudeWorkerDefinitionTest(unittest.TestCase):
    def test_worker_메타데이터는_고정_Sonnet_ID_high와_Agent_금지를_정한다(self):
        """worker 정의는 이름, 고정된 Sonnet 전체 ID, high, Agent 금지를 선언하고 우회나 자동 격리 필드를 두지 않는다."""
        # Given
        path = WORKER

        # When
        metadata, _ = split_definition(path)

        # Then
        self.assertEqual(metadata["name"], "worker")
        self.assertEqual(metadata["model"], "claude-sonnet-5-5")
        self.assertEqual(metadata["effort"], "high")
        self.assertIn("Agent", [tool.strip() for tool in str(metadata["disallowedTools"]).split(",")])
        self.assertEqual(UNSUPPORTED_FIELDS & set(metadata), set())

    def test_worker_설명은_조정자가_할당한_구현에만_쓰게_한다(self):
        """worker 설명은 조정자가 할당한 구현 작업으로 사용 범위를 제한한다."""
        # Given
        path = WORKER

        # When
        metadata, _ = split_definition(path)

        # Then
        description = " ".join(metadata["description"].split())
        self.assertTrue(description.startswith("Coordinator-assigned implementation task only."))
        self.assertIn("Never use it for investigation, planning, review", description)

    def test_worker_본문은_공유_worker_계약을_가리킨다(self):
        """worker 본문은 규칙을 복사하지 않고 공유 실행 규칙의 worker 섹션을 가리킨다."""
        # Given
        path = WORKER

        # When
        _, body = split_definition(path)

        # Then
        normalized = " ".join(body.split())
        self.assertIn('Follow the "Assigned workers" section of the implementation execution rules', normalized)
        self.assertIn("report it to the coordinator and make no edit", normalized)
        self.assertNotIn("min(6", normalized)
        self.assertIsNone(re.search(r"claude-sonnet-\d", body))

    def test_플러그인은_영어_정의만_에이전트로_등록하고_한국어_미러는_제외한다(self):
        """기본 agents 스캔은 하위 폴더까지 등록하므로 매니페스트가 영어 정의 파일만 나열해 agents/ko 미러를 뺀다."""
        # Given
        manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))

        # When
        listed = manifest.get("agents")
        definitions = sorted(f"./agents/{path.name}" for path in (REPO_ROOT / "agents").glob("*.md"))

        # Then
        self.assertEqual(listed, ["./agents/scout.md", "./agents/worker.md", "./agents/researcher.md", "./agents/designer.md"])
        self.assertEqual(sorted(listed), definitions)
        self.assertFalse(any("/ko/" in path for path in listed))
        mirror = WORKER_MIRROR.read_text(encoding="utf-8")
        self.assertIn("영어 원본: [worker.md](../worker.md)", mirror)
        self.assertIn("비권위", mirror)

    def test_designer_메타데이터는_고정_Opus_ID_xhigh와_Agent_금지를_정한다(self):
        """designer 정의는 이름, 고정된 Opus 전체 ID, xhigh, Agent 금지를 선언하고 worker와 같은 할당 규칙을 따른다."""
        # Given
        path = REPO_ROOT / "agents/designer.md"

        # When
        metadata, body = split_definition(path)
        normalized = " ".join(body.split())

        # Then
        self.assertEqual(metadata["name"], "designer")
        self.assertEqual(metadata["model"], "claude-opus-5-5")
        self.assertEqual(metadata["effort"], "xhigh")
        self.assertEqual(metadata["disallowedTools"], "Agent")
        self.assertEqual(set(metadata) & UNSUPPORTED_FIELDS, set())
        self.assertIn("UI code (HTML, CSS, JS, components)", normalized)
        self.assertIn("flowcharts or diagrams", normalized)
        self.assertIn('Follow the "Assigned workers" section of the implementation execution rules', normalized)
        self.assertIn("report it to the coordinator and make no edit", normalized)
        mirror = (REPO_ROOT / "agents/ko/designer.ko.md").read_text(encoding="utf-8")
        self.assertIn("영어 원본: [designer.md](../designer.md)", mirror)
        self.assertIn("비권위", mirror)

    def test_매니페스트는_Mod_설정을_가리키고_토글_다섯_개를_기본_켜짐으로_선언한다(self):
        """hooks는 Mod 설정 파일이고, 설정 파일의 모듈이 존재하며, userConfig는 영어 title과 description을 가진 boolean 다섯 개다."""
        # Given
        manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))

        # When
        config_path = REPO_ROOT / manifest["hooks"]
        modules = json.loads(config_path.read_text(encoding="utf-8"))["modules"]
        options = manifest["userConfig"]

        # Then
        self.assertEqual(manifest["hooks"], "./config/claude-mod.json")
        self.assertEqual(modules, ["../hooks/mod/register.js"])
        self.assertTrue(all((config_path.parent / module).is_file() for module in modules))
        self.assertEqual(
            list(options),
            ["agent_guard", "session_approval", "role_pinning", "language_guard", "datagrip_guard"],
        )
        for key, option in options.items():
            with self.subTest(key=key):
                self.assertEqual(option["type"], "boolean")
                self.assertIs(option["default"], True)
                self.assertTrue(option["title"].isascii() and option["description"].isascii())


class ClaudeWorkerAdapterTest(unittest.TestCase):
    def test_구현은_플러그인_worker와_정의에_고정된_모델을_사용한다(self):
        """Claude에서 구현을 위임할 때는 플러그인 worker를 쓰고 호출 단위 모델을 넘기지 않는다."""
        # Given
        expected = (
            "[implementation execution rules](implementation-execution.md)",
            "When delegating implementation, use only `hei5enbug-agent-setup:worker`, or `hei5enbug-agent-setup:designer` "
            "for UI code, visual design, and diagram work.",
            "Their definitions pin `claude-sonnet-5-5` with `high` and `claude-opus-5-5` with `xhigh`.",
            "Never pass a per-invocation model on an invocation or resume, because that overrides the definition.",
            "Never switch to an agent outside these two.",
        )

        # When
        section = implementation_section()

        # Then
        for phrase in expected:
            self.assertIn(phrase, section)
        self.assertNotIn("alias", section)
        self.assertNotIn("model-config", section)

    def test_실제_모델과_사고_강도를_낮출_수_있는_설정을_확인한다(self):
        """강제 모델, 사고 강도 재정의, 상한, 대체 경고를 확인하고 부족한 근거를 거부한다."""
        # Given
        inputs = (
            "`CLAUDE_CODE_SUBAGENT_MODEL`",
            "`CLAUDE_CODE_SUBAGENT_MODEL_FORCE`",
            "`CLAUDE_CODE_EFFORT_LEVEL`",
            "`maxEffortLevel`",
            "substitution or fallback warning",
        )

        # When
        section = implementation_section()

        # Then
        for name in inputs:
            self.assertIn(name, section)
        self.assertIn("Never change user settings.", section)
        self.assertIn("names `claude-sonnet-5-5` as the actual model and `high` as the effort", section)
        self.assertIn("For `designer`, the evidence is `claude-opus-5-5` with `xhigh`.", section)
        self.assertIn(
            "A different recorded model, a cap below the pinned effort, a contradictory override, or unknown effective "
            "precedence is insufficient.",
            section,
        )

    def test_이어_보내기_지원_여부에_따라_준비_확인_경로가_갈린다(self):
        """고정 표시 줄이 없으면 시작 결과에 모델이 없으므로 준비 확인 뒤 같은 worker에 구현을 보내고, 이어 보내기가 없으면 메인 대체 처리를 사용한다."""
        # Given
        readiness = (
            "Without that line, the launch result does not name the model, so start each worker with a "
            "readiness-only assignment."
        )
        supported = "Use this path only when that follow-up keeps the pinned model."
        unsupported = "When that continuation is unavailable, skip the two-phase path and use the session fallback."

        # When
        section = implementation_section()

        # Then
        self.assertIn(readiness, section)
        self.assertIn("After its record passes, send the implementation assignment to the same worker.", section)
        self.assertIn(supported, section)
        self.assertIn(unsupported, section)
        self.assertIn("Recheck the settings after any resume.", section)

    def test_역할_고정_표시가_있으면_준비_확인_없이_바로_할당하고_기록은_계속_확인한다(self):
        """세션 컨텍스트에 역할 고정 표시 줄이 있으면 준비 확인 호출 없이 할당하되 설정 점검과 기록 확인은 유지한다."""
        # Given
        expected = (
            "When the session context contains `hei5enbug-agent-setup mod: role pinning active`",
            "blocks tool calls from a subagent that answered on another model",
            "Send the assignment directly, with no readiness-only call.",
            "In both cases, keep the settings inspection before the first invocation",
            "read the subagent record to confirm the actual model and effort before accepting delegated work",
        )

        # When
        section = implementation_section()

        # Then
        for phrase in expected:
            self.assertIn(phrase, section)

    def test_worker나_기록이_없으면_위임을_멈추고_메인_대체_처리를_쓴다(self):
        """플러그인 worker나 실제 모델 기록이 없으면 위임을 멈추고 공통 대체 처리를 적용한다."""
        # Given
        blocker = "A missing plugin worker or a missing subagent record stops the affected delegation."

        # When
        section = implementation_section()

        # Then
        self.assertIn(blocker, section)
        self.assertIn("Apply the session fallback.", section)

    def test_호스트_한도는_메인_세션을_빼고_세며_바꾸지_않는다(self):
        """Claude 동시 실행 한도는 실행 중인 서브에이전트만 세고 조정자는 그 값을 바꾸지 않는다."""
        # Given
        limit = "`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`, which counts running subagents but not the main session"

        # When
        section = implementation_section()

        # Then
        self.assertIn(limit, section)
        self.assertIn("never change it", section)

    def test_구현_후속_메시지마다_강제_모델_설정을_다시_확인한다(self):
        """Claude Code는 세션 중 설정을 다시 읽으므로 구현 후속 메시지마다 강제 모델 입력을 다시 확인한다."""
        # Given
        expected = (
            "in the environment and every settings file",
            "Claude Code can reload settings during a session, and a forced subagent model overrides the definition.",
            "Recheck these inputs before every follow-up that carries implementation work.",
        )

        # When
        section = implementation_section()

        # Then
        for phrase in expected:
            self.assertIn(phrase, section)

    def test_scout는_계획과_실행_중_범위가_한정된_조사에_쓰인다(self):
        """scout는 세션 기준에 맞는 계획·실행 중 조사에 쓰고 호출 단위 모델은 넘기지 않는다."""
        # Given
        text = CLAUDE_AGENTS.read_text(encoding="utf-8")

        # When
        investigation = " ".join(text.split("## Investigation", 1)[1].split("## Skill workers", 1)[0].split())

        # Then
        self.assertIn("Use `hei5enbug-agent-setup:scout` for bounded investigation whenever the session delegation rule selects it", investigation)
        self.assertIn("Never pass a per-invocation model, because that overrides the definition.", investigation)

    def test_내장_서브에이전트는_예외_둘을_빼고_금지하고_차단_훅을_가리킨다(self):
        """내장 서브에이전트 이름과 fork는 금지하되 claude-code-guide와 statusline-setup만 예외로 두고, 종류를 비우는 호출도 막는다."""
        # Given
        text = CLAUDE_AGENTS.read_text(encoding="utf-8")

        # When
        built_in = " ".join(text.split("## Built-in subagents", 1)[1].split("## Investigation", 1)[0].split())

        # Then
        forbidden, exceptions = built_in.split("The exceptions are", 1)
        for name in ("`general-purpose`", "`Explore`", "`Plan`", "`claude`", "a fork"):
            self.assertIn(name, forbidden)
        for name in ("`claude-code-guide`", "`statusline-setup`"):
            self.assertNotIn(name, forbidden)
            self.assertIn(name, exceptions.split("Always name", 1)[0])
        self.assertIn("Always name the subagent type, because an omitted type runs `general-purpose`.", built_in)
        self.assertIn(
            "The plugin's agent guard hook denies an omitted type and every built-in type except those two exceptions",
            built_in,
        )

    def test_스킬_작업자는_scout나_별도_CLI_프로세스를_쓴다(self):
        """스킬이 요구하는 읽기 전용 작업자는 scout, 시험 출력을 쓰는 작업자는 별도 claude -p 프로세스로 실행한다."""
        # Given
        text = CLAUDE_AGENTS.read_text(encoding="utf-8")

        # When
        skill_workers = " ".join(text.split("## Skill workers", 1)[1].split("## Implementation", 1)[0].split())

        # Then
        self.assertIn("use `hei5enbug-agent-setup:scout` only when its effective settings match the role's requirements", skill_workers)
        self.assertIn("For Skill Builder evaluation, use the required participant table", skill_workers)
        self.assertIn("target-skill metadata does not override it", skill_workers)
        self.assertIn("Give the role its instructions and output contract.", skill_workers)
        self.assertIn("use a verified Skill Builder-approved runner or its unavailable-capability path", skill_workers)
        self.assertIn("Do not lower the required effort or change production scout settings.", skill_workers)
        self.assertIn("The main conversation writes any file the role produces.", skill_workers)
        self.assertIn("run a separate `claude -p` process with the model and effort that the skill pins", skill_workers)
        self.assertIn("use `researcher` only when the skill's contract and any evaluation settings permit", skill_workers)
        self.assertIn("Private or authenticated remote access and all edits stay in the main conversation.", skill_workers)

    def test_공유_라우팅과_GPT_전환_후에도_Claude_Code_설정을_유지한다(self):
        """공유 라우팅을 조건부로 읽으며 GPT로 전환해도 Claude Code의 역할 설정을 유지한다."""
        # Given
        text = CLAUDE_AGENTS.read_text(encoding="utf-8")

        # When
        section = implementation_section()
        normalized = " ".join(text.split())

        # Then
        self.assertIn("read [shared model routing](model-routing.md)", normalized)
        self.assertIn("Selecting GPT as Claude Code's main model does not change this host", section)
        self.assertIn("`hei5enbug-agent-setup:researcher` only when public search and fetch tools are available", normalized)
        self.assertIn("Never pass a per-invocation model; its definition pins `claude-sonnet-5-5` and `medium`.", normalized)
        self.assertIn("Verify that definition, effective non-secret settings, and the host subagent record", normalized)


if __name__ == "__main__":
    unittest.main()
