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


if __name__ == "__main__":
    unittest.main()
