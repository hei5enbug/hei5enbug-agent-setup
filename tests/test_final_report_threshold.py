"""The length under which a final report needs no independent text review is one number on both hosts."""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import final_report_hook  # noqa: E402
from test_final_report_hook import assistant, edit, prompt  # noqa: E402

SHARED_TEXT = REPO_ROOT / "instructions/shared-text.md"
SENTENCE = re.compile(
    r"A final report under (\d+) characters, after trimming, needs no review.*?"
    r"one of (\d+) characters or more needs this review"
)


class FinalReportThresholdTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hook = final_report_hook
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.transcript = Path(directory.name) / "session.jsonl"
        self.transcript.write_text("\n".join((prompt(), assistant(edit()))) + "\n", encoding="utf-8")

    def decide(self, message: str) -> dict | None:
        event = {"hook_event_name": "Stop", "transcript_path": str(self.transcript), "last_assistant_message": message}
        return self.hook.decide(event)

    def test_공유_글_규칙의_짧은_최종_보고_문장은_훅과_같은_길이를_적는다(self):
        """규칙 문장의 두 길이가 훅의 MINIMUM_REPORT_CHARACTERS와 다르면, Codex는 문장대로 한 길이에서 Claude Code는 훅의 다른 길이에서 검토를 건너뛰어 두 호스트가 갈린다."""
        # given
        text = " ".join(SHARED_TEXT.read_text(encoding="utf-8").split())

        # when
        match = SENTENCE.search(text)

        # then
        self.assertIsNotNone(match, "the exemption sentence for a short final report is missing from shared-text.md")
        self.assertEqual(
            [int(number) for number in match.groups()],
            [self.hook.MINIMUM_REPORT_CHARACTERS] * 2,
        )

    def test_훅은_기준보다_한_글자_짧은_보고는_통과시키고_기준_길이_보고는_막는다(self):
        """규칙 문장의 "미만"과 "이상"이 훅의 경계와 어긋나면 정확히 기준 길이의 보고가 한 호스트에서만 검토되므로, 경계 한 글자 아래와 위를 가른다."""
        # given
        limit = self.hook.MINIMUM_REPORT_CHARACTERS
        under = "가" * (limit - 1)
        at_limit = "가" * limit
        padded = f"\n  {under}  \n"

        # when
        results = [self.decide(message) for message in (under, padded, at_limit)]

        # then
        self.assertEqual([result is not None for result in results], [False, False, True])


if __name__ == "__main__":
    unittest.main()
