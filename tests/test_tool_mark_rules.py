from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATION = REPO_ROOT / "instructions/independent-model-validation.md"
SHARED_TEXT = REPO_ROOT / "instructions/shared-text.md"
TEXT_REVIEW = REPO_ROOT / "scripts/text_review.py"


def flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def finalization() -> str:
    return flat(VALIDATION).split("## Finalization", 1)[1]


def load_text_review():
    spec = importlib.util.spec_from_file_location("text_review", TEXT_REVIEW)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ToolMarkRulesTest(unittest.TestCase):
    def test_확정_절은_검토_결과를_한_줄로_알리라고_하고_검토자_모델과_증명_수준_나열은_더_하지_않는다(self):
        """최종 보고에 검토 모델과 effort가 다시 들어가면 받는 사람 글에 도구 이름이 새므로, 확정 절이 링크 한 줄만 요구하고 나열 문장이 없어야 한다."""
        # given
        text = finalization()

        # when
        rule = re.search(r"one line with the link or path of the review result.+?finding left unresolved", text)

        # then
        self.assertIsNotNone(rule)
        self.assertIn("It gives no reviewer model, effort, pass count, finding categories, or safety proof.", text)
        self.assertNotIn("Report the resolved reviewer model", text)
        self.assertNotIn("the safety fact and its proof level for an implementation review", text)

    def test_검토를_못_했거나_거절했을_때는_그_사실과_이유를_한_줄로_적으라고_한다(self):
        """검토를 못 한 이유가 보고에서 사라지면 사용자가 검증 상태를 모르게 되므로, 확정 절에 한 줄 규칙이 있다."""
        # given
        text = finalization()

        # when
        stated = "could not run or the user declined it, the report states that, and why, in one line" in text

        # then
        self.assertTrue(stated)

    def test_공유_글_규칙과_최종_보고_독자_문장은_검토_결과_한_줄과_미해결_지적을_독자에게_필요한_사실로_적는다(self):
        """검토자가 결과 링크 한 줄을 지울 거리로 보고하면 작성자가 그 줄을 지우게 되므로, 규칙과 독자 문장 둘 다 그 줄과 미해결 지적을 필요하다고 적는다."""
        # given
        rule = flat(SHARED_TEXT)
        reader = " ".join(load_text_review().READERS["final-report"].split())

        # when
        in_rule = "one line with the link or path of its review result, and each finding left unresolved, are facts the user needs" in rule
        in_reader = "one line with the link or path of its review result, and each finding left unresolved, are facts they need" in reader

        # then
        self.assertEqual((True, True), (in_rule, in_reader))

    def test_공유_글_규칙은_도구_표시_정의와_예외를_모두_적는다(self):
        """예외 하나가 빠지면 작성자가 바뀌는 모델 설정이나 서명 줄까지 지우거나 요청이 이름 붙인 도구를 지우므로, 규칙에 표시 정의와 예외가 모두 있다."""
        # given
        rule = flat(SHARED_TEXT)

        # when
        missing = [fragment for fragment in (
            "A tool mark is a model name, version, or reasoning effort",
            "or wording that says an AI or an agent did it",
            "A tool that is the subject of the work",
            "The last-line agent signature that the destination's own rules require",
            "no other signature, credit, or provenance line is excepted, even when the destination's rules ask for it",
            "remove the tool mark as a phrase and keep the element and the rest of its content",
            "write in that text only what the request names",
        ) if fragment not in rule]

        # then
        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
