from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "text_review.py"
SPEC = importlib.util.spec_from_file_location("text_review", SCRIPT)
text_review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(text_review)

PROCEDURE = "0 Check and build; 1 Add columns; 2 Load data; 3 Compare; 4 Enable reads; 5 Enable writes; 6 Watch; 7 Remove old path; 8 Confirm"
STAGE_HEADING = "may refer to a stage, phase, or division of a procedure or plan by its number alone"


def advisories(text: str) -> list[tuple[str, int]]:
    found, flagged = text_review.check_text(text, "other", False)
    assert not found, found
    return [(item["rule"], item["line"]) for item in flagged]


class StageNumberAloneTest(unittest.TestCase):
    def test_번호만으로_단계를_부른_문장은_권고로_보고하고_제목을_옆에_둔_문장은_보고하지_않는다(self):
        """고정 절차(%s)의 "step 0"과 "steps 3 to 8"처럼 번호만 쓴 문장을 잡고, 번호 옆에 제목을 쓴 같은 문장은 잡지 않는다.""" % PROCEDURE
        # given
        by_number = "Run step 0 first, then steps 3 to 8 in order."
        by_title = "Run 0 Check and build first, then 3 Compare through 8 Confirm in order."
        beside = "Run step 0 (Check and build) first, then steps 3: Compare through 8: Confirm in order."

        # when
        results = [advisories(text) for text in (by_number, by_title, beside)]

        # then
        self.assertEqual([[("stage-number-alone", 1)], [], []], results)

    def test_깊이와_개수를_말하는_숫자는_권고가_아니다(self):
        """"2 levels"와 "3 items" 같은 수량과 한국어의 "최대 2단계", "3단계 이내"는 단계 번호로 오인하지 않는다."""
        # given
        texts = [
            "Keep nesting at a depth of at most 2 levels and list at most 3 items.",
            "Upgrade to version 3 and keep at most 2 retries.",
            "중첩은 최대 2단계로 하고 목록은 3개 이내로 둔다.",
            "깊이 2단계, 3단계 이내만 허용한다.",
        ]

        # when
        results = [advisories(text) for text in texts]

        # then
        self.assertEqual([[], [], [], []], results)

    def test_구간을_번호로만_부른_문장은_권고이고_구간_제목과_항목_제목을_쓴_문장은_아니다(self):
        """"Phase 1"만 쓴 문장은 잡고, 구간을 Rollout으로 부르고 항목 번호 옆에 제목을 쓴 문장과 번호 목록의 제목 있는 항목은 잡지 않는다."""
        # given
        alone = "Phase 1 is in progress and 1 is merged."
        titled = "Phase 1 Rollout is in progress and 1 Schema extension is merged."
        named = "Rollout is in progress and 1 Schema extension is merged."
        listing = "1. Schema extension\n2. Backfill\n3. Reads cutover\n"

        # when
        results = [advisories(text) for text in (alone, titled, named, listing)]

        # then
        self.assertEqual([[("stage-number-alone", 1)], [], [], []], results)

    def test_한국어_단계_번호도_번호만_있으면_권고이다(self):
        """"0단계", "3단계부터 8단계까지", "단계 3"처럼 번호만 쓴 한국어 표현을 잡고, 번호 뒤에 제목을 콜론으로 붙인 표현은 잡지 않는다."""
        # given
        texts = ["0단계를 먼저 실행한 뒤 3단계부터 8단계까지 진행한다.", "단계 3을 끝낸다.", "0단계: 점검과 빌드를 먼저 한다."]

        # when
        results = [advisories(text) for text in texts]

        # then
        self.assertEqual([[("stage-number-alone", 1)], [("stage-number-alone", 1)], []], results)

    def test_코드_범위와_펜스_안의_표현은_보지_않는다(self):
        """코드 조각과 펜스 코드 블록 안의 "step 3"은 글의 표현이 아니므로 권고가 아니다."""
        # given
        text = "Run `step 3` as written.\n\n```text\nstep 4 of the log\n```\n"

        # when
        result = advisories(text)

        # then
        self.assertEqual([], result)

    def test_권고는_종료_코드를_바꾸지_않고_검토자에게_줄과_설명을_넘긴다(self):
        """번호만 쓴 단계는 check의 종료 코드 0과 findings 빈 목록으로 보고하고, 검토 배정에는 그 줄과 설명을 한 번만 싣는다."""
        # given
        draft = "Run step 0 first, then steps 3 to 8 in order.\n"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "draft.txt"
            path.write_text(draft, encoding="utf-8")

            # when
            result = subprocess.run([sys.executable, str(SCRIPT), "check", "--kind", "other", str(path)],
                                    capture_output=True, text=True, check=False)

        # then
        payload = json.loads(result.stdout)
        self.assertEqual((0, []), (result.returncode, payload["findings"]))
        self.assertEqual(["stage-number-alone"], [item["rule"] for item in payload["advisories"]])
        flagged = text_review.check_text(draft, "other", False)[1]
        assignment = text_review.build_assignment("pr-description", draft, [], [], [], None, flagged)
        self.assertEqual((1, 2), (assignment.count(STAGE_HEADING), assignment.count(draft.strip())))

    def test_번호만_쓴_줄이_없으면_검토_배정에_단계_설명을_싣지_않고_검토자_지침에는_항상_둔다(self):
        """권고가 없는 글의 배정에는 줄 목록이 없고, 번호만으로 부른 단계를 보고하라는 지침은 어느 글에나 들어 있다."""
        # given
        draft = "Run 0 Check and build first.\n"

        # when
        assignment = text_review.build_assignment("pr-description", draft, [], [], [], None, [])

        # then
        self.assertNotIn(STAGE_HEADING, assignment)
        self.assertIn("refers to by its number alone", assignment)


if __name__ == "__main__":
    unittest.main()
