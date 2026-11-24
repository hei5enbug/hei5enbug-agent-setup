"""Check that text_review.py counts the runs that returned findings for one draft and marks the stops of a repeated review."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import text_review  # noqa: E402

FINDING = {"type": "removable", "quote": "x", "reason": "y"}


class RoundsTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.draft = self.root / "draft.txt"
        self.draft.write_text("A sentence.\n", encoding="utf-8")
        patcher = mock.patch.dict(os.environ, {text_review.STATE_DIR_ENV: str(self.root / "state")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_review(self, findings):
        outcome = {"findings": findings, "over_budget_facts": [], "runner": {"exit": 0, "verified": True}}
        output = []
        with mock.patch.object(text_review, "run_reviewer", return_value=outcome), \
                mock.patch.object(text_review, "emit", side_effect=output.append):
            code = text_review.main(["review", "--kind", "ticket-comment", "--draft", str(self.draft)])
        return code, output[-1]

    def test_지적을_낸_실행마다_라운드가_늘고_네_번째와_그_뒤_세_번째마다_멈춤이_켜진다(self):
        """네 번째 정지와 계속하라는 답 뒤 세 라운드 정지가 스크립트 출력으로 정해져야 규칙 문장이 실행 횟수를 세지 않는다."""
        # given
        stops = []
        # when
        for _ in range(8):
            _, payload = self.run_review([FINDING])
            stops.append((payload["round"], payload.get("stop", False)))
        # then
        self.assertEqual(stops, [(1, False), (2, False), (3, False), (4, True), (5, False), (6, False), (7, True), (8, False)])

    def test_지적이_없는_실행은_횟수를_지우고_다른_초안은_따로_센다(self):
        """통과한 초안이나 다른 파일의 지적이 이 초안의 정지에 섞이면 안 된다."""
        # given
        self.run_review([FINDING])
        self.run_review([FINDING])
        # when
        code, passed = self.run_review([])
        _, again = self.run_review([FINDING])
        other = self.root / "other.txt"
        other.write_text("Another.\n", encoding="utf-8")
        self.draft = other
        _, separate = self.run_review([FINDING])
        # then
        self.assertEqual((code, "round" in passed, again["round"], separate["round"]), (0, False, 1, 1))

    def test_오래_쉰_초안의_횟수는_다시_시작한다(self):
        """며칠 전 같은 경로의 초안이 새 글의 정지를 앞당기면 안 된다."""
        # given
        path = text_review.rounds_file("ticket-comment", str(self.draft))
        # when
        first = text_review.count_round(path, 0.0)
        second = text_review.count_round(path, 10.0)
        later = text_review.count_round(path, 10.0 + text_review.ROUNDS_IDLE_SECONDS)
        # then
        self.assertEqual((first, second, later), (1, 2, 1))

    def test_표준_입력_초안은_횟수를_저장하지_않는다(self):
        """파일이 없는 초안에는 같은 초안을 알아볼 방법이 없다."""
        self.assertIsNone(text_review.rounds_file("ticket-comment", "-"))
        self.assertEqual(text_review.count_round(None, 0.0), 1)


if __name__ == "__main__":
    unittest.main()
