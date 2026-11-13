"""Unit tests for the two-host comparison verdict that decides every harness change by measured gaps."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

E2E_ROOT = Path(__file__).resolve().parents[1] / "evals/e2e"
sys.path.insert(0, str(E2E_ROOT))

from harness import verdict  # noqa: E402


def sided(wall_gaps, cost_gaps, passed=True):
    """Runs per host whose claude value is 100 and whose codex value is 100 times the seeded gap of that repetition."""
    runs = {"claude": [], "codex": []}
    for wall, cost in zip(wall_gaps, cost_gaps):
        runs["claude"].append({"passed": passed, "wall_seconds": 100.0, "cost_usd": 1.0})
        runs["codex"].append({"passed": passed, "wall_seconds": 100.0 * wall if wall else None,
                              "cost_usd": 1.0 * cost if cost else None})
    return runs


def case_of(before, after, case_id="T08"):
    return {"id": case_id, "before": before, "after": after}


def measure(result, name):
    return next(item for item in result["measures"] if item["measure"] == name)


class GapVerdictTest(unittest.TestCase):
    def test_이전과_이후의_격차가_같으면_통과한다(self):
        """given 시간과 비용 격차가 이전과 이후에 같을 때 when 판정하면 then 두 측정과 사례 모두 pass다."""
        # given
        case = case_of(sided([1.3], [1.3]), sided([1.3], [1.3]))

        # when
        result = verdict.case_verdict(case)

        # then
        self.assertEqual([item["verdict"] for item in result["measures"]], ["pass", "pass"])
        self.assertEqual(result["verdict"], "pass")

    def test_비용_격차가_1_3에서_1_6으로_커지면_그_사례의_비용만_repeat이다(self):
        """given 비용 격차 1.3에서 1.6, 시간 격차는 그대로일 때 when 판정하면 then 비용만 repeat이고 시간은 pass다."""
        # given
        case = case_of(sided([1.3], [1.3]), sided([1.3], [1.6]))

        # when
        result = verdict.case_verdict(case)

        # then
        self.assertEqual(measure(result, "cost_usd")["verdict"], "repeat")
        self.assertEqual(measure(result, "wall_seconds")["verdict"], "pass")
        self.assertEqual(result["verdict"], "repeat")

    def test_이후_다섯_격차의_중앙값_1_4가_이전_최댓값_1_5_이하면_통과한다(self):
        """given 이후 격차 중앙값 1.4와 이전 격차 최댓값 1.5일 때 when 다섯 번 판정하면 then 비용은 pass다."""
        # given
        before = sided([1.2] * 5, [1.1, 1.2, 1.5, 1.3, 1.0])
        after = sided([1.2] * 5, [1.4, 1.9, 1.0, 1.4, 1.5])

        # when
        result = verdict.case_verdict(case_of(before, after))

        # then
        self.assertEqual((measure(result, "cost_usd")["verdict"], measure(result, "cost_usd")["median_after"]),
                         ("pass", 1.4))
        self.assertEqual(result["verdict"], "pass")

    def test_이후_다섯_격차의_중앙값_1_6이_이전_최댓값_1_5를_넘으면_실패한다(self):
        """given 이후 격차 중앙값 1.6과 이전 격차 최댓값 1.5일 때 when 다섯 번 판정하면 then 비용은 fail이고 사례도 fail이다."""
        # given
        before = sided([1.2] * 5, [1.1, 1.2, 1.5, 1.3, 1.0])
        after = sided([1.2] * 5, [1.6, 1.9, 1.0, 1.6, 1.7])

        # when
        result = verdict.case_verdict(case_of(before, after))

        # then
        self.assertEqual(measure(result, "cost_usd")["verdict"], "fail")
        self.assertEqual(result["verdict"], "fail")

    def test_이전_첫_시간_격차가_2_4면_investigate_줄을_내고_그_측정은_실패시키지_않는다(self):
        """given 이전 첫 시간 격차 2.4일 때 when 판정하면 then 사건과 측정을 적은 investigate 줄이 나오고 사례는 fail이 아니다."""
        # given
        case = case_of(sided([2.4], [1.3]), sided([3.0], [1.3]), case_id="T02")

        # when
        result = verdict.case_verdict(case)

        # then
        self.assertEqual(measure(result, "wall_seconds")["verdict"], "investigate")
        self.assertEqual(len(result["lines"]), 1)
        self.assertTrue(result["lines"][0].startswith("investigate: T02 wall_seconds"))
        self.assertNotEqual(result["verdict"], "fail")

    def test_비용_값이_없는_실행은_not_measured이고_통과가_아니다(self):
        """given 이후 한 호스트의 비용 값이 없을 때 when 판정하면 then 비용은 not measured이고 사례는 pass가 아니다."""
        # given
        case = case_of(sided([1.3], [1.3]), sided([1.3], [None]))

        # when
        result = verdict.case_verdict(case)

        # then
        self.assertEqual(measure(result, "cost_usd")["verdict"], "not measured")
        self.assertEqual(result["verdict"], "not measured")

    def test_한_호스트에서_이전에_통과하고_이후에_실패한_사례는_격차와_상관없이_실패한다(self):
        """given 격차는 줄었지만 codex에서 이전에 통과한 사례가 이후에 실패할 때 when 판정하면 then 사례는 fail이다."""
        # given
        after = sided([1.1], [1.1])
        after["codex"][0]["passed"] = False
        case = case_of(sided([1.5], [1.5]), after)

        # when
        result = verdict.case_verdict(case)

        # then
        self.assertEqual(result["quality"]["verdict"], "fail")
        self.assertIn("codex", result["quality"]["reason"])
        self.assertEqual(result["verdict"], "fail")

    def test_이전_실행이_없는_사례는_이후_실행의_품질만으로_판정한다(self):
        """given 이전 실행이 없는 사례일 때 when 판정하면 then 격차는 baseline이고 필수 검사 통과만으로 pass다."""
        # given
        case = case_of({}, sided([2.9], [2.9]))

        # when
        result = verdict.case_verdict(case)

        # then
        self.assertEqual([item["verdict"] for item in result["measures"]], ["baseline", "baseline"])
        self.assertEqual(result["verdict"], "pass")

    def test_여러_사례는_하나라도_실패하면_전체가_실패한다(self):
        """given 통과한 사례와 실패한 사례가 섞였을 때 when 비교하면 then 전체 판정은 fail이고 사례별 판정이 남는다."""
        # given
        failing = sided([1.2], [1.2])
        failing["claude"][0]["passed"] = False
        cases = [case_of(sided([1.2], [1.2]), sided([1.2], [1.2]), "T02"), case_of(sided([1.2], [1.2]), failing, "T05")]

        # when
        result = verdict.compare(cases)

        # then
        self.assertEqual((result["verdict"], [item["verdict"] for item in result["cases"]]), ("fail", ["pass", "fail"]))


def keyed(runs, reps):
    return [{**run, "rep": rep} for run, rep in zip(runs, reps)]


class RepetitionPairingTest(unittest.TestCase):
    def test_이후_codex의_첫_반복이_없으면_다른_반복과_짝짓지_않고_측정되지_않음이다(self):
        """given 이후 claude는 반복 1과 2가 있고 codex는 반복 2만 있을 때 when 시간을 판정하면 then 반복 1의 짝이 없어 not measured이고 pass가 아니다."""
        # given
        before = {"claude": keyed(runs_of([100.0]), [1]), "codex": keyed(runs_of([100.0]), [1])}
        after = {"claude": keyed(runs_of([100.0, 1000.0]), [1, 2]), "codex": keyed(runs_of([100.0]), [2])}

        # when
        result = verdict.measure_verdict(case_of(before, after), "wall_seconds")

        # then
        self.assertEqual(result["verdict"], "not measured")
        self.assertIn("repetition 1", result["step"])

    def test_다섯_번_판정은_목록_위치가_아니라_반복_번호로_짝을_짓는다(self):
        """given codex 이후 목록이 반복 5부터 거꾸로 적혀 있고 반복 1의 격차만 컸을 때 when 시간을 판정하면 then 첫 격차가 커진 것으로 읽어 다섯 번 판정을 한다."""
        # given
        before = {"claude": runs_of([100.0] * 5), "codex": runs_of([100.0] * 5)}
        codex_after = keyed(runs_of([100.0, 100.0, 100.0, 100.0, 150.0]), [5, 4, 3, 2, 1])
        after = {"claude": keyed(runs_of([100.0] * 5), [1, 2, 3, 4, 5]), "codex": codex_after}

        # when
        result = verdict.measure_verdict(case_of(before, after), "wall_seconds")

        # then
        self.assertEqual((result["step"], result["verdict"]), ("five runs", "pass"))
        self.assertEqual(result["gap_after"], [1.5, 1.0, 1.0, 1.0, 1.0])

    def test_개선_주장은_이전과_이후의_반복_번호가_어긋나면_측정되지_않음이다(self):
        """given 이전은 반복 1만 있고 이후는 반복 2만 있을 때 when 주장을 판정하면 then 한 호스트에서 짝이 없어 not measured다."""
        # given
        before = {"claude": keyed(runs_of([100.0]), [1]), "codex": keyed(runs_of([100.0]), [1])}
        after = {"claude": keyed(runs_of([80.0]), [2]), "codex": keyed(runs_of([80.0]), [2])}

        # when
        result = verdict.claim_verdict(case_of(before, after), ["wall_seconds"])

        # then
        self.assertEqual(result["verdict"], "not measured")


class MissingValueExemptionTest(unittest.TestCase):
    def test_이전_실행이_없어_기준선을_세우는_사례도_이후_비용이_없으면_측정되지_않음이다(self):
        """given 이전 실행이 없고 이후 codex의 비용이 없을 때 when 사례를 판정하면 then 비용은 not measured이고 사례는 pass가 아니다."""
        # given
        case = case_of({}, sided([1.3], [None]))

        # when
        result = verdict.case_verdict(case)

        # then
        self.assertEqual(measure(result, "cost_usd")["verdict"], "not measured")
        self.assertEqual(measure(result, "wall_seconds")["verdict"], "baseline")
        self.assertNotEqual(result["verdict"], "pass")

    def test_이전_첫_비용_격차가_2를_넘어도_이후_비용이_없으면_측정되지_않음이다(self):
        """given 이전 첫 비용 격차가 2.4이고 이후 codex의 비용이 없을 때 when 사례를 판정하면 then 비용은 investigate가 아니라 not measured다."""
        # given
        case = case_of(sided([1.3], [2.4]), sided([1.3], [None]))

        # when
        result = verdict.case_verdict(case)

        # then
        self.assertEqual(measure(result, "cost_usd")["verdict"], "not measured")
        self.assertEqual(result["lines"], [])
        self.assertNotEqual(result["verdict"], "pass")


class PerMeasureBranchTest(unittest.TestCase):
    def test_첫_쌍에서_통과한_측정은_다른_측정을_위한_반복에도_통과로_남는다(self):
        """given 시간은 첫 쌍에서 1.3에서 1.2로 줄고 비용은 1.3에서 1.6으로 커져 다섯 번을 돌렸고 이후 시간 격차가 1.6으로 늘었을 때 when 판정하면 then 시간은 첫 쌍으로 pass이고 사례는 pass다."""
        # given
        before = sided([1.3] * 5, [1.3] * 5)
        after = sided([1.2, 1.6, 1.6, 1.6, 1.6], [1.6, 1.0, 1.0, 1.0, 1.0])

        # when
        result = verdict.case_verdict(case_of(before, after))

        # then
        self.assertEqual((measure(result, "wall_seconds")["verdict"], measure(result, "wall_seconds")["step"]), ("pass", "first run"))
        self.assertEqual((measure(result, "cost_usd")["verdict"], measure(result, "cost_usd")["step"]), ("pass", "five runs"))
        self.assertEqual(result["verdict"], "pass")


def runs_of(wall, cost=None, passed=True):
    cost = cost or [1.0] * len(wall)
    return [{"passed": passed, "wall_seconds": w, "cost_usd": c} for w, c in zip(wall, cost)]


def hosts_of(before_wall, after_wall, after_cost=None, codex_after_wall=None, passed_after=None):
    before = {"claude": runs_of(before_wall), "codex": runs_of(before_wall)}
    claude_after = runs_of(after_wall, after_cost)
    codex_after = runs_of(codex_after_wall or after_wall, after_cost)
    for index in passed_after or []:
        claude_after[index]["passed"] = False
    return {"id": "T08", "before": before, "after": {"claude": claude_after, "codex": codex_after}}


class ImprovementClaimTest(unittest.TestCase):
    CLAIM = ["wall_seconds"]

    def test_첫_쌍이_주장한_측정에서_낮으면_다섯_번까지_계속한다(self):
        """given 첫 쌍의 시간이 두 호스트에서 낮을 때 when 주장을 판정하면 then continue to five다."""
        # given
        case = hosts_of([100.0], [80.0])

        # when
        result = verdict.claim_verdict(case, self.CLAIM)

        # then
        self.assertEqual(result["verdict"], "continue to five")

    def test_첫_쌍이_낮지_않으면_두_번째_쌍을_돌린다(self):
        """given 첫 쌍의 시간이 낮지 않을 때 when 판정하면 then 기각하지 않고 second pair를 요구한다."""
        # given
        case = hosts_of([100.0], [100.0])

        # when
        result = verdict.claim_verdict(case, self.CLAIM)

        # then
        self.assertEqual(result["verdict"], "second pair")

    def test_두_쌍이_모두_낮지_않으면_기각한다(self):
        """given 두 쌍 모두 시간이 낮지 않을 때 when 판정하면 then reject다."""
        # given
        case = hosts_of([100.0, 100.0], [100.0, 120.0])

        # when
        result = verdict.claim_verdict(case, self.CLAIM)

        # then
        self.assertEqual(result["verdict"], "reject")

    def test_다섯_번_모두_통과하고_양쪽_호스트에서_중앙값_조건을_만족하면_수락한다(self):
        """given 이후 시간 중앙값이 이전 최솟값보다 낮고 비용 중앙값이 이전 최댓값 이하일 때 when 판정하면 then 두 호스트 모두 accept다."""
        # given
        case = hosts_of([100.0, 110.0, 105.0, 120.0, 115.0], [90.0, 80.0, 70.0, 95.0, 60.0],
                        after_cost=[1.0, 0.9, 1.0, 1.1, 1.0])

        # when
        result = verdict.claim_verdict(case, self.CLAIM)

        # then
        self.assertEqual(result["verdict"], "accept")
        self.assertEqual({item["verdict"] for item in result["hosts"].values()}, {"accept"})

    def test_한_호스트에서만_만족하면_기각한다(self):
        """given codex에서는 이후 시간 중앙값이 이전 최솟값 이상일 때 when 판정하면 then 전체가 reject이고 codex만 reject다."""
        # given
        case = hosts_of([100.0, 110.0, 105.0, 120.0, 115.0], [90.0, 80.0, 70.0, 95.0, 60.0],
                        codex_after_wall=[100.0, 105.0, 101.0, 130.0, 99.0])

        # when
        result = verdict.claim_verdict(case, self.CLAIM)

        # then
        self.assertEqual((result["verdict"], result["hosts"]["claude"]["verdict"], result["hosts"]["codex"]["verdict"]),
                         ("reject", "accept", "reject"))

    def test_다섯_번_중_이후_실행_하나가_필수_검사를_실패하면_기각한다(self):
        """given 이후 다섯 실행 중 하나가 실패했지만 시간은 모두 낮을 때 when 판정하면 then reject다."""
        # given
        case = hosts_of([100.0, 110.0, 105.0, 120.0, 115.0], [90.0, 80.0, 70.0, 95.0, 60.0], passed_after=[3])

        # when
        result = verdict.claim_verdict(case, self.CLAIM)

        # then
        self.assertEqual((result["verdict"], result["hosts"]["claude"]["step"]),
                         ("reject", "an after run failed a required check"))

    def test_주장하지_않은_측정의_중앙값이_이전_최댓값을_넘으면_기각한다(self):
        """given 시간만 주장했는데 이후 비용 중앙값이 이전 비용 최댓값을 넘을 때 when 판정하면 then reject다."""
        # given
        case = hosts_of([100.0, 110.0, 105.0, 120.0, 115.0], [90.0, 80.0, 70.0, 95.0, 60.0],
                        after_cost=[1.4, 1.5, 1.6, 1.4, 1.5])

        # when
        result = verdict.claim_verdict(case, self.CLAIM)

        # then
        self.assertEqual(result["verdict"], "reject")


if __name__ == "__main__":
    unittest.main()
