#!/usr/bin/env python3
"""항상 로드되는 공통 규칙이 두 호스트의 메인 세션 문맥에 실리는지 검사한다."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import session_context  # noqa: E402


def contexts() -> dict[str, str]:
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("PLUGIN_ROOT", None)
        return {host: " ".join(session_context.render_context(REPO_ROOT, host).split()) for host in ("claude", "codex")}


class CommonRulesTest(unittest.TestCase):
    def assert_in_every_context(self, *phrases: str) -> None:
        for host, context in contexts().items():
            for phrase in phrases:
                with self.subTest(host=host, phrase=phrase):
                    self.assertIn(phrase, context)

    def test_답변은_추천을_먼저_두고_처음_읽는_사람에게_간결하며_기존_스레드에는_새_내용만_더한다(self):
        """결정을 묻는 답변은 추천과 이유를 먼저 쓰고, 필요한 내용만 한 가지로 읽히게 쓰며, 기존 스레드에는 새 내용만 더한다."""
        # Given
        phrases = (
            "for a decision, one recommendation and its reason, then the alternatives",
            "Keep only what the reader needs, give each sentence one reading",
            "define terms a first-time reader would not know",
            "In an existing thread, read it first and add only what is new.",
        )

        # When / Then
        self.assert_in_every_context(*phrases)


if __name__ == "__main__":
    unittest.main()
