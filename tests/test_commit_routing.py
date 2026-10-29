"""Structural checks that every new commit goes through suggest-commit's commit mode on both hosts."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_EXCLUSION = (
    "Amend, rebase, merge, revert, and cherry-pick run outside commit mode; "
    "every other new commit uses it, including each one a squash or split creates."
)
COMMON = REPO_ROOT / "instructions/session/common.md"
SKILL = REPO_ROOT / "skills/suggest-commit/SKILL.md"
CODEX_METADATA = REPO_ROOT / "skills/suggest-commit/agents/openai.yaml"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def section(text: str, heading: str) -> str:
    return text.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]


class CommitRoutingTest(unittest.TestCase):
    def test_공통_지침은_새_커밋을_모두_커밋_모드로_보낸다(self):
        """항상 로드되는 공통 지침은 요청이든 작업이든 새 커밋을 suggest-commit 커밋 모드로 만들게 한다."""
        # Given
        common = normalized(COMMON)

        # When
        routes = "Create every new commit, whether the user asked for it or a task requires it, through the `suggest-commit` skill in its commit mode" in common

        # Then
        self.assertTrue(routes)

    def test_제외_명령은_스킬_한_곳에만_적고_공통_지침은_그곳을_가리킨다(self):
        """제외 목록과 기록 정리 커밋 포함 규칙은 스킬의 Modes 절에만 있고, 공통 지침은 그 절을 가리키며 옛 문구는 어디에도 없다."""
        # Given
        common, skill = normalized(COMMON), normalized(SKILL)

        # When
        modes = " ".join(section(SKILL.read_text(encoding="utf-8"), "Modes").split())
        old_phrases = [phrase for phrase in ("rewrite existing commits", "are outside this rule") if phrase in common + skill]

        # Then
        self.assertIn(SHARED_EXCLUSION, modes)
        self.assertNotIn("cherry-pick", common)
        self.assertIn("Only the commands its Modes section names run outside it.", common)
        self.assertEqual([], old_phrases)

    def test_스킬_설명은_커밋_요청에도_실행된다(self):
        """스킬 설명은 두 호스트의 자동 실행 신호이므로 커밋 요청과 제목 하나 선택을 담는다."""
        # Given
        text = SKILL.read_text(encoding="utf-8")

        # When
        description = " ".join(yaml.safe_load(text.split("---", 2)[1])["description"].split())

        # Then
        self.assertIn("When the user asks to create a commit", description)
        self.assertIn("single most appropriate subject", description)
        self.assertLessEqual(len(description), 1024)

    def test_커밋_모드는_범위만_한_번_커밋하고_우회하지_않는다(self):
        """커밋 모드는 범위만 스테이징해 한 번 커밋하고 훅 우회, amend, 푸시를 하지 않는다."""
        # Given
        text = SKILL.read_text(encoding="utf-8")

        # When
        commit_mode = " ".join(section(text, "Commit Mode").split())
        scope = " ".join(section(text, "Scope of the Change").split())

        # Then
        self.assertIn("With no named scope and a non-empty index, the staged changes are the scope", scope)
        for rule in (
            "Never commit a placeholder such as `[TICKET]`.",
            "Never run `git add -A`, `git add .`, or `git commit -a`.",
            "with exactly one `-m`",
            "Never add `--no-verify`, `--amend`, `--allow-empty`, `--signoff`, or `--trailer`.",
            "`git log -1 --format=%B` must show the subject alone.",
            "Show no table and no alternative subjects, and ask no follow-up question.",
            "This skill never pushes.",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, commit_mode)

    def test_추천_모드는_읽기_전용으로_남는다(self):
        """추천만 요청하면 여전히 저장소를 바꾸지 않는다."""
        # Given
        text = SKILL.read_text(encoding="utf-8")

        # When
        constraints = " ".join(section(text, "Constraints").split())

        # Then
        self.assertIn("**Suggestion mode is read-only.** It never stages, commits, amends, pushes, or edits files.", constraints)
        self.assertIsNone(re.search(r"^- \*\*Read-only\.\*\*", text, re.MULTILINE))

    def test_Codex는_커밋_요청에서_스킬을_암시적으로_실행할_수_있다(self):
        """Codex 메타데이터가 암시적 실행을 막으면 커밋 요청에서 스킬이 불리지 않으므로 막지 않는다."""
        # Given
        metadata = yaml.safe_load(CODEX_METADATA.read_text(encoding="utf-8"))

        # When
        policy = metadata.get("policy", {})

        # Then
        self.assertNotEqual(policy.get("allow_implicit_invocation"), False)


if __name__ == "__main__":
    unittest.main()
