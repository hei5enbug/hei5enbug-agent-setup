"""Check the scoring of the seeded reviewer-recall drafts that measure loop-shape candidate (d) of issue 102."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "evals/text-review-recall"
spec = importlib.util.spec_from_file_location("recall", ROOT / "recall.py")
recall = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recall)

REPEATED = {"type": "removable", "quote": "The nightly export now finishes within 20 minutes.", "reason": "repeats the first sentence"}
AMBIGUOUS = {"type": "ambiguous", "quote": "The cleanup step removes the old export files after it runs.", "reason": "after which run"}
MISSING = {"type": "missing", "quote": "", "reason": "the rollback is not stated"}


class RecallScoreTest(unittest.TestCase):
    def test_세_결함을_모두_보고한_실행만_결함_초안을_통과한다(self):
        """한 실행이 결함 하나만 내는 검토자를 후보 (d)가 고쳤는지 가려야 하므로 세 결함을 모두 덮어야 통과한다."""
        # given
        all_three = [REPEATED, AMBIGUOUS, MISSING]
        # when
        outcomes = (recall.passes("defects", all_three), recall.passes("defects", [REPEATED]),
                    recall.passes("defects", [REPEATED, AMBIGUOUS, {**MISSING, "type": "ambiguous"}]))
        # then
        self.assertEqual(outcomes, (True, False, False))

    def test_깨끗한_초안은_지적이_하나라도_있으면_실패한다(self):
        """모든 문제를 내라는 요청이 깨끗한 글에 지어낸 지적을 만들면 후보를 채택할 수 없다."""
        # when
        outcomes = (recall.passes("clean", []), recall.passes("clean", [REPEATED]))
        # then
        self.assertEqual(outcomes, (True, False))

    def test_점수표는_실행마다_찾은_결함_수와_통과를_세고_결과가_아닌_출력은_실패로_본다(self):
        """검토자가 죽거나 JSON이 아닌 출력은 통과로 세면 안 된다."""
        with tempfile.TemporaryDirectory() as folder:
            # given
            out = Path(folder)
            good = json.dumps({"findings": [REPEATED, AMBIGUOUS, MISSING]})
            (out / "defects-1.json").write_text(json.dumps({"exit": 1, "stdout": [good]}), encoding="utf-8")
            (out / "defects-2.json").write_text(json.dumps({"exit": 3, "stdout": ["error"]}), encoding="utf-8")
            (out / "clean-1.json").write_text(json.dumps({"exit": 0, "stdout": [json.dumps({"findings": []})]}), encoding="utf-8")
            # when
            table = recall.score(out)
            # then
            self.assertEqual(table, {"defects": [(3, 1), (0, 0)], "clean": [(0, 1)]})

    def test_사례_파일은_세_결함을_모두_담은_초안과_결함_없는_초안을_가진다(self):
        """초안이 바뀌어 결함이 사라지면 측정이 아무것도 가르지 못한다."""
        # given
        defects = (ROOT / "cases/draft-defects.txt").read_text(encoding="utf-8")
        clean = (ROOT / "cases/draft-clean.txt").read_text(encoding="utf-8")
        # then
        self.assertEqual(defects.count("The nightly export now finishes within 20 minutes."), 2)
        self.assertIn("after it runs", defects)
        self.assertNotIn("roll back", defects)
        self.assertIn("To roll back", clean)


if __name__ == "__main__":
    unittest.main()
