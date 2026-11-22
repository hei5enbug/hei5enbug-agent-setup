"""Check that the repeated-review rules stay written where a session reads them."""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return " ".join((REPO_ROOT / relative).read_text(encoding="utf-8").split())


class RepeatedReviewRulesTest(unittest.TestCase):
    def test_검증_규칙은_세_라운드_정지를_담은_절을_두고_실행_경계가_그_절을_가리킨다(self):
        """이 절이나 가리키는 문장이 사라지면 사용자가 요청한 반복 검토가 정지도 보고도 없이 돈다."""
        # given
        text = read("instructions/independent-model-validation.md")
        # when
        section = text.split("## Repeated review on request")[1]
        boundary = text.split("## Execution boundary")[1].split("## Finalization")[0]
        # then
        self.assertIn("after every three rounds that still return findings", section)
        self.assertIn("Every round keeps the first round's reviewers and reviewed set", section)
        self.assertIn("stop before the next round and write nothing outward", section)
        self.assertIn("Repeated review on request", boundary)

    def test_마무리_규칙은_고친_대목의_결정_대조와_작업자의_같은_요점_수정을_요구한다(self):
        """수정이 같은 요점을 말하는 다른 대목에 닿지 않으면 다음 라운드가 같은 요점을 다시 지적한다."""
        # given
        text = read("instructions/independent-model-validation.md")
        # when
        finalization = text.split("## Finalization")[1].split("## Repeated review on request")[0]
        # then
        self.assertIn("compares each corrected passage with the confirmed decisions", finalization)
        self.assertIn("change every passage in its allowed paths that states the same point", finalization)
        self.assertIn("never limits the worker to a list of sentences", finalization)

    def test_공유_글_규칙의_네_번째_실행_정지는_반복_검토_절을_가리킨다(self):
        """사용자가 계속하라고 답한 뒤의 글 검토 반복에 정지가 없어지는 것을 막는다."""
        # given
        text = read("instructions/shared-text.md")
        # when
        stop = text.split("- Count only runs that reach the reviewer")[1].split("- For a final report")[0]
        # then
        self.assertIn('"Repeated review on request"', stop)

    def test_세션_공통_규칙은_검토_수정과_반복_검토_전_읽기를_적는다(self):
        """항상 불러오는 이 두 줄이 없으면 반복 검토를 시작하는 세션이 규칙 파일을 읽지 않는다."""
        # given
        text = read("instructions/session/common.md")
        # then
        self.assertIn("After a rename, a changed decision, a review fix, or a rollback", text)
        self.assertIn("Before finishing a substantial change or repeating a review, read [independent model validation]", text)


if __name__ == "__main__":
    unittest.main()
