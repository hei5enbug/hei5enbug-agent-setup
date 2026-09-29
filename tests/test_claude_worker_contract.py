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
    def test_worker_메타데이터는_sonnet_xhigh와_Agent_금지를_정한다(self):
        """worker 정의는 이름, sonnet, xhigh, Agent 금지를 선언하고 우회나 자동 격리 필드를 두지 않는다."""
        # Given
        path = WORKER

        # When
        metadata, _ = split_definition(path)

        # Then
        self.assertEqual(metadata["name"], "worker")
        self.assertEqual(metadata["model"], "sonnet")
        self.assertEqual(metadata["effort"], "xhigh")
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

    def test_플러그인이_worker와_한국어_미러를_기존_규칙대로_배포한다(self):
        """Claude 플러그인은 agents 폴더에서 worker를 찾고 한국어 미러는 agents/ko에 둔다."""
        # Given
        manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))

        # When
        agent_dirs = manifest.get("agents", "./agents/")
        discovered = sorted(path.name for path in (REPO_ROOT / "agents").glob("*.md"))

        # Then
        self.assertIn(agent_dirs, ("./agents", "./agents/"))
        self.assertEqual(discovered, ["scout.md", "worker.md"])
        mirror = WORKER_MIRROR.read_text(encoding="utf-8")
        self.assertIn("영어 원본: [worker.md](../worker.md)", mirror)
        self.assertIn("비권위", mirror)


class ClaudeWorkerAdapterTest(unittest.TestCase):
    def test_구현은_플러그인_worker와_호출별_sonnet_별칭을_사용한다(self):
        """Claude 구현은 플러그인 worker만 쓰고 호출과 재개마다 sonnet 별칭을 넘기며 전체 ID는 공식 문서로 확정한다."""
        # Given
        expected = (
            "[implementation execution rules](implementation-execution.md)",
            "Use only `hei5enbug-agent-setup:worker` for implementation.",
            "Pass the `sonnet` alias as the per-invocation model on every invocation and resume.",
            "Never switch to another agent.",
            "The required family is the latest production Claude Sonnet.",
            "Resolve its full ID from the Sonnet mapping",
            "https://code.claude.com/docs/en/model-config",
        )

        # When
        section = implementation_section()

        # Then
        for phrase in expected:
            self.assertIn(phrase, section)
        self.assertIsNone(re.search(r"claude-sonnet-\d", section))

    def test_실제_모델과_사고_강도를_낮출_수_있는_설정을_확인한다(self):
        """강제 모델, 사고 강도 재정의, 상한, 대체 경고를 확인하고 부족한 근거를 거부한다."""
        # Given
        inputs = (
            "`CLAUDE_CODE_SUBAGENT_MODEL`",
            "`CLAUDE_CODE_SUBAGENT_MODEL_FORCE`",
            "`ANTHROPIC_DEFAULT_SONNET_MODEL`",
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
        self.assertIn("names the resolved full ID as the actual model and `xhigh` as the effort", section)
        self.assertIn(
            "A different recorded model, a cap below `xhigh`, a contradictory override, or unknown effective "
            "precedence is insufficient.",
            section,
        )

    def test_이어_보내기_지원_여부에_따라_준비_확인_경로가_갈린다(self):
        """시작 결과에 모델이 없으므로 준비 확인 뒤 같은 worker에 구현을 보내고, 이어 보내기가 없으면 수정하지 않는다."""
        # Given
        readiness = "The launch result does not name the model, so start each worker with a readiness-only assignment."
        supported = "Use this path only when that follow-up keeps the per-invocation model."
        unsupported = "When that continuation is unavailable, skip the two-phase path and make no edits."

        # When
        section = implementation_section()

        # Then
        self.assertIn(readiness, section)
        self.assertIn("After its record passes, send the implementation assignment to the same worker.", section)
        self.assertIn(supported, section)
        self.assertIn(unsupported, section)
        self.assertIn("Recheck the settings after any resume.", section)

    def test_worker나_서브에이전트_기록이_없으면_막는다(self):
        """플러그인 worker나 실제 모델을 보여 주는 서브에이전트 기록이 없으면 대체 없이 구현을 막는다."""
        # Given
        blocker = "A missing plugin worker or a missing subagent record blocks the affected implementation."

        # When
        section = implementation_section()

        # Then
        self.assertIn(blocker, section)
        self.assertIn("Report the exact capability and make no edit.", section)

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
            "Claude Code can reload settings during a session, and a forced subagent model overrides the per-invocation model.",
            "Recheck these inputs before every follow-up that carries implementation work.",
        )

        # When
        section = implementation_section()

        # Then
        for phrase in expected:
            self.assertIn(phrase, section)

    def test_scout_조사_규칙은_그대로_남는다(self):
        """구현 규칙을 바꿔도 계획 중 scout 조사 규칙과 범용 에이전트 금지는 유지된다."""
        # Given
        text = CLAUDE_AGENTS.read_text(encoding="utf-8")

        # When
        investigation = " ".join(text.split("## Investigation", 1)[1].split("## Implementation", 1)[0].split())

        # Then
        self.assertIn("Use `hei5enbug-agent-setup:scout` for investigation, only while planning", investigation)
        self.assertIn("catch-all `general-purpose` and `claude` subagents", investigation)


if __name__ == "__main__":
    unittest.main()
