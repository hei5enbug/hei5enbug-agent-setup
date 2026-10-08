from __future__ import annotations

import json
import re
import tomllib
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_ROLE = REPO_ROOT / "agents/researcher.md"
CODEX_ROLE = REPO_ROOT / "standalone-agents/codex-researcher.toml"


def frontmatter(content: str) -> str:
    return content.split("---", 2)[1]


def value(source: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}:\s*(.*?)\s*$", source, re.MULTILINE)
    if match is None:
        raise AssertionError(f"Missing frontmatter field: {name}")
    return match.group(1)


class ResearcherContractTest(unittest.TestCase):
    def test_Claude_역할은_공개조사에_필요한_도구만_허용한다(self):
        """Claude researcher는 공개 조사 도구만 허용하고 변경이나 하위 에이전트 호출을 금지한다."""
        # Given
        source = CLAUDE_ROLE.read_text(encoding="utf-8")
        header = frontmatter(source)

        # When
        allowed = {tool.strip() for tool in value(header, "tools").split(",")}
        denied = {tool.strip() for tool in value(header, "disallowedTools").split(",")}

        # Then
        self.assertEqual(value(header, "name"), "researcher")
        self.assertEqual(allowed, {"Read", "Grep", "Glob", "WebSearch", "WebFetch"})
        self.assertTrue({"Agent", "Bash", "Edit", "Write", "NotebookEdit"}.issubset(denied))
        self.assertEqual(value(header, "model"), "claude-haiku-5-5")
        self.assertEqual(value(header, "effort"), "medium")

    def test_Codex_역할은_읽기전용이고_모델_ID를_고정하지_않는다(self):
        """Codex researcher는 읽기 전용 sandbox와 xhigh를 쓰며 모델 ID를 역할 파일에 고정하지 않는다."""
        # Given
        role = tomllib.loads(CODEX_ROLE.read_text(encoding="utf-8"))

        # When
        instructions = role["developer_instructions"]

        # Then
        self.assertEqual(role["name"], "researcher")
        self.assertEqual(role["model_reasoning_effort"], "xhigh")
        self.assertEqual(role["sandbox_mode"], "read-only")
        self.assertNotIn("model", role)
        self.assertIn("host-native public search and fetch tools only when the host exposes them", instructions)
        self.assertIn("Never use shell commands for network access", instructions)
        self.assertIn("Never start or delegate to another agent", instructions)

    def test_연구원은_누락된_조사조건을_메인세션에_넘긴다(self):
        """필요한 질문 범위나 공개 도구, 권한, 설정 근거가 없으면 연구원은 메인 세션에 넘긴다."""
        # Given
        claude = CLAUDE_ROLE.read_text(encoding="utf-8")
        codex = tomllib.loads(CODEX_ROLE.read_text(encoding="utf-8"))["developer_instructions"]

        # When
        combined = f"{claude}\n{codex}".lower()

        # Then
        for phrase in (
            "exactly one question",
            "source scope",
            "remote material only when it is publicly accessible",
            "main-session fallback",
            "contradictions, and gaps",
            "authenticated or private remote sources",
            "the main session owns them",
            "acceptance decisions",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_Claude_manifest는_researcher와_reviewer를_등록한다(self):
        """Claude manifest는 기존 역할을 유지하면서 researcher와 reviewer를 한 번씩 등록한다."""
        # Given
        manifest = json.loads((REPO_ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))

        # When
        agents = manifest["agents"]

        # Then
        self.assertEqual(agents.count("./agents/researcher.md"), 1)
        self.assertEqual(agents.count("./agents/reviewer.md"), 1)
        self.assertIn("./agents/scout.md", agents)
        self.assertIn("./agents/worker.md", agents)
        self.assertIn("./agents/designer.md", agents)


if __name__ == "__main__":
    unittest.main()
