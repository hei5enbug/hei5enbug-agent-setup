"""The rules for a review the user asks to repeat sit in the files that own them, and the other files point to them."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATION = REPO_ROOT / "instructions/independent-model-validation.md"
SHARED_TEXT = REPO_ROOT / "instructions/shared-text.md"
COMMON = REPO_ROOT / "instructions/session/common.md"
SECTION_NAME = '"Repeated review on request"'
SHARED_LINK = "[Repeated review on request](independent-model-validation.md#repeated-review-on-request)"


def flat(text: str) -> str:
    return " ".join(text.split())


def section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, heading
    return flat(match.group(1))


class RepeatedReviewRulesTest(unittest.TestCase):
    def test_독립_검증_문서는_세_라운드마다_멈추고_보고하는_절을_갖고_실행_경계가_그_절을_가리킨다(self):
        """사용자가 되풀이를 요청한 검토의 정지, 보고, 고정 규칙이 한 절에 있고 실행 경계가 그 절로 연결된다."""
        # Given
        text = VALIDATION.read_text(encoding="utf-8")

        # When
        repeated = section(text, "Repeated review on request")
        boundary = section(text, "Execution boundary")

        # Then
        self.assertIn("after every three rounds that still return findings", repeated)
        self.assertIn("A round that returns no findings ends the loop", repeated)
        self.assertIn("write nothing outward", repeated)
        self.assertIn("A rise or fall in the count never stops the loop by itself", repeated)
        self.assertIn("Keep the first round's reviewers and reviewed set in every round", repeated)
        self.assertIn("ask once, with one recommendation", repeated)
        self.assertIn("the last round's fixes were not reviewed", repeated)
        self.assertIn(SECTION_NAME, boundary)

    def test_독립_검증_문서의_마무리_절은_고친_문장을_결정과_증거에_견주고_작업자에게_문장_목록만_주지_않게_한다(self):
        """검토 결과를 적용한 세션은 고친 문장을 확정된 결정과 증거에 견주고, 작업자 지시는 같은 요지의 모든 문장을 고치게 한다."""
        # Given
        text = VALIDATION.read_text(encoding="utf-8")

        # When
        finalization = section(text, "Finalization")

        # Then
        self.assertIn("compares each corrected passage with the confirmed decisions and the authoritative evidence",
                      finalization)
        self.assertIn("its assignment gives the point, the reason, and the evidence of each finding", finalization)
        self.assertIn("change every passage in its allowed paths that states the same point", finalization)
        self.assertIn("never limits the worker to a list of sentences", finalization)
        self.assertIn(SECTION_NAME, finalization)

    def test_글_검토의_네_번째_실행_정지는_계속하라는_답을_반복_검토_절로_넘긴다(self):
        """네 번째 실행 정지 항목이 계속하라는 답 뒤의 반복을 새 절로 연결하고 정지 자체는 네 번째 실행에 남는다."""
        # Given
        text = flat(SHARED_TEXT.read_text(encoding="utf-8"))

        # When
        bullet = re.search(r"- Count only runs that reach the reviewer\..*?(?= - For a final report)", text)

        # Then
        self.assertTrue(bullet)
        self.assertIn("When the fourth such run for one draft still returns findings", bullet.group(0))
        self.assertIn(SHARED_LINK, bullet.group(0))
        self.assertIn("counting rounds from that answer", bullet.group(0))

    def test_공통_지침은_검토_수정을_옛_값_갱신_항목에_넣고_되풀이_검토_전에_검증_규칙을_읽게_한다(self):
        """공통 지침의 옛 값 갱신 항목이 검토 수정을 이름 붙이고, 검증 규칙 안내 줄이 사용자가 요청한 되풀이 검토를 이름 붙인다."""
        # Given
        text = flat(COMMON.read_text(encoding="utf-8"))

        # When / Then
        self.assertIn("After a rename, a changed decision, a review fix, or a rollback, update or report every earlier "
                      "output of the work still showing the old value", text)
        self.assertIn("Before finishing a substantial change or repeating a review the user asked for, read "
                      "[independent validation](../independent-model-validation.md).", text)
        self.assertEqual(text.count("independent-model-validation.md"), 1)


if __name__ == "__main__":
    unittest.main()
