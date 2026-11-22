"""The parallel limit's maximum follows the case P of the request-budget record: six unless P was accepted on both hosts."""

from __future__ import annotations

import json
import sys
import unittest
import unittest.mock
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import parallel_limit  # noqa: E402

RECORD = REPO_ROOT / "evals" / "e2e" / "records" / "97.json"
P_CASE = "T36"
SIX = 6


def p_accepted(record: dict[str, Any]) -> bool:
    return any(item.get("case") == P_CASE and item.get("measure") == "claim" and item.get("verdict") == "accept"
               for item in record.get("verdicts", []))


class ParallelLimitRecordTest(unittest.TestCase):
    def test_P가_통과하지_않았으면_상한은_6이고_통과했으면_상한이_없다(self):
        """기록 97이 없거나 P의 주장이 수락되지 않았으면 config 의 max 가 6이고, 수락되었으면 null 이다."""
        # given
        configured = json.loads((REPO_ROOT / "config" / "parallel-limit.json").read_text(encoding="utf-8"))["max"]
        accepted = p_accepted(json.loads(RECORD.read_text(encoding="utf-8"))) if RECORD.is_file() else False

        # when
        expected = None if accepted else SIX

        # then
        self.assertEqual(configured, expected)

    def test_수락_판정은_T36의_claim_항목_accept만_센다(self):
        """T36 의 claim 이 accept 일 때만 P 통과로 읽고, 다른 사례나 reject 는 세지 않는다."""
        # given
        accepted = {"verdicts": [{"case": "T36", "measure": "claim", "verdict": "accept"}]}
        rejected = {"verdicts": [{"case": "T36", "measure": "claim", "verdict": "reject"}]}
        other = {"verdicts": [{"case": "T05", "measure": "claim", "verdict": "accept"}]}

        # when
        results = [p_accepted(item) for item in (accepted, rejected, other, {})]

        # then
        self.assertEqual(results, [True, False, False, False])

    def test_코드는_설정_파일의_상한을_그대로_읽는다(self):
        """환경 변수가 없으면 configured_maximum 은 config 의 max 를 돌려준다."""
        # given
        configured = json.loads((REPO_ROOT / "config" / "parallel-limit.json").read_text(encoding="utf-8"))["max"]

        # when
        with unittest.mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop(parallel_limit.MAX_ENV, None)
            maximum = parallel_limit.configured_maximum()

        # then
        self.assertEqual(maximum, configured)


if __name__ == "__main__":
    unittest.main()
