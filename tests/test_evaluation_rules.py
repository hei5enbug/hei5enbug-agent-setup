"""Tests that the written evaluation rules are present in their files."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

ADOPTION_RULE = (
    "is adopted or rejected only on a record under `evals/e2e/records/`",
    "`evals/e2e/harness/cli.py record`",
    "run on both Claude Code and Codex",
    "a candidate with no record stays open as undecided",
    "never call an existing rule sufficient, on a judgment alone",
)
MODEL_EVALUATION_RULES = {
    "시간": "time is the wall time until the accepted, integrated result, never the time to produce a draft",
    "비용": "cost is the spend of every attempt, including failed attempts, rework, and review, divided by the solved cases",
    "한 가지 차이": "the compared sides differ in one thing only",
    "호스트 격차": "one run per side and host first and five alternating runs only for a case whose host gap grew",
    "다섯 번 규칙 유지": "the five-run rule stays for a claim that a change is faster or cheaper",
    "실패 사례 보존": "keep a confirmed, reproducible harness failure as a deterministic test where a script can decide it, "
                  "and otherwise as a retained evaluation case",
    "부분 집합 비교": "a later comparison runs the smallest subset of retained cases that its change can affect, "
                  "never the whole set by default",
}


def flat(path: str) -> str:
    return re.sub(r"\s+", " ", (REPO_ROOT / path).read_text(encoding="utf-8")).lower()


class EvaluationRulesTest(unittest.TestCase):
    def test_AGENTS는_기록이_있어야_변경을_채택하거나_기각한다는_규칙을_담는다(self):
        """given AGENTS.md when 채택 규칙의 고유 문구를 찾으면 then 모두 있고 보호 절 앞에 있다."""
        # given
        text = flat("AGENTS.md")

        # when
        missing = [phrase for phrase in ADOPTION_RULE if phrase.lower() not in text]

        # then
        self.assertEqual(missing, [])
        self.assertLess(text.index(ADOPTION_RULE[0].lower()), text.index("## public boundary (protected)"))

    def test_모델_평가_지침은_다섯_규칙을_모두_담는다(self):
        """given instructions/model-evaluation.md when 시간·비용·한 가지 차이·호스트 격차·실패 사례 규칙을 찾으면 then 모두 있다."""
        # given
        text = flat("instructions/model-evaluation.md")

        # when
        missing = [name for name, phrase in MODEL_EVALUATION_RULES.items() if phrase.lower() not in text]

        # then
        self.assertEqual(missing, [])

    def test_다섯_번_실행_규칙은_변경이_더_빠르거나_싸다는_주장에만_걸린다(self):
        """given 모델 평가 지침 when 다섯 번 번갈아 실행하는 조건을 읽으면 then 그 주장에 걸려 있고 분산 일반 조건이 아니다."""
        # given
        text = flat("instructions/model-evaluation.md")

        # when
        scoped = "for a claim that a change is faster or cheaper, alternate the compared sides over at least five runs"

        # then
        self.assertIn(scoped, text)
        self.assertNotIn("when variance matters, alternate", text)


    def test_한국어_사본은_격차가_커진_사례에_네_번을_더해_모두_다섯_번이라고_쓴다(self):
        """given 모델 평가 지침의 한국어 사본 when 호스트 격차가 커진 사례의 반복 횟수를 읽으면 then 4회를 더해 모두 5회이고 5회를 더한다고 쓰지 않는다."""
        # given
        text = flat("docs/ko/instructions/model-evaluation.ko.md")

        # when / then
        self.assertIn("호스트 격차가 커진 사례에만 번갈아 4회를 더 실행해 모두 5회로 만든다", text)
        self.assertNotIn("5회 실행을 더한다", text)


if __name__ == "__main__":
    unittest.main()
