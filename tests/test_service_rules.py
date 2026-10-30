#!/usr/bin/env python3
"""호스팅 서비스 접근 규칙이 읽기 크기를 정하는지 검사한다."""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICES = REPO_ROOT / "instructions/services.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


class ServiceRulesTest(unittest.TestCase):
    def test_한_항목을_찾을_때는_검색이나_단건_조회를_쓰고_목록은_좁힌_작은_페이지로_읽는다(self):
        """한 항목을 찾는 읽기는 전체 목록 대신 검색이나 단건 조회를 쓰고, 목록이 필요하면 시간, 필드, 질의로 좁힌 작은 페이지부터 읽는다."""
        # Given
        services = normalized(SERVICES)

        # When
        rules = (
            "When a read targets one item, such as a user, a message, a page, or an issue, use the service's search or "
            "single-item lookup instead of a full list.",
            "When a list is needed, request a small page narrowed by time, field, or query, and read further pages only "
            "when the answer needs them.",
        )

        # Then
        for rule in rules:
            with self.subTest(rule=rule):
                self.assertIn(rule, services)

    def test_이슈를_만들기_전에_열린_이슈와_닫힌_이슈를_모두_찾아_중복_완료_충돌을_가린다(self):
        """어느 트래커든 이슈를 만들기 전에 모든 상태를 검색하고, report-skill-gap 4단계도 닫힌 이슈와 충돌까지 같은 결과로 다룬다."""
        # Given
        services = normalized(SERVICES)
        skill = normalized(REPO_ROOT / "skills/report-skill-gap/SKILL.md")

        # When
        rules = (
            "Before creating an issue or ticket on any tracker, search its open and closed items with two or three "
            "keyword sets.",
            "When an open item covers it, create nothing and offer a comment on that item.",
            "When a closed item already finished it, create nothing and report that item.",
            "When an item or a recorded decision conflicts with or contradicts it, show both and ask before creating.",
            "When a related item neither duplicates nor conflicts with it, name that item in the new issue.",
            "Report the searches you ran.",
        )
        skill_rules = (
            "Search the target's open and closed issues with two or three keyword sets",
            "--state all",
            "Under the condition that a closed issue already finished the gap, create nothing and report that issue.",
            "show both and ask before drafting.",
            "name it in the new issue.",
        )

        # Then
        for rule in rules:
            with self.subTest(rule=rule):
                self.assertIn(rule, services)
        for rule in skill_rules:
            with self.subTest(skill_rule=rule):
                self.assertIn(rule, skill)
        self.assertNotIn("--state open", skill)


if __name__ == "__main__":
    unittest.main()
