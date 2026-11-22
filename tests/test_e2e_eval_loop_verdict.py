"""Unit tests for adopting or rejecting a loop-shape candidate from the runs of a record."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals/e2e"))

from harness import loop_verdict, records  # noqa: E402

BASE_COSTS = [1.0, 1.2, 1.1, 1.3, 1.4]
LOW_COSTS = [0.7, 0.8, 0.75, 0.7, 0.9]


def runs_of(variant, costs, claude_costs=None, lost=(), fails=(), reps=None):
    """Runs of one variant: five repetitions of each cost case and one of each other writing task on both hosts. Both hosts
    cost the same unless `claude_costs` is given, and the tasks in `lost` fail `text-review-clean`."""
    found = []
    for case in loop_verdict.WRITING_CASES:
        count = (reps or 5) if case in loop_verdict.CLAIM_CASES else 1
        for host in ("claude", "codex"):
            for rep in range(1, count + 1):
                cost = (claude_costs if host == "claude" and claude_costs else costs)[rep - 1]
                clean = case not in lost
                found.append({"case": case, "variant": variant, "host": host, "rep": rep, "wall_seconds": 100.0, "cost_usd": cost,
                              "checks": {"text-review-clean": clean, "ran-text-review": True},
                              "passed": clean and case not in fails})
    return found


def both(*variants):
    return [run for variant in variants for run in variant]


class WritingRuleTest(unittest.TestCase):
    def test_기준선에서_T15의_text_review_clean이_통과하고_후보에서_실패하면_후보는_거부된다(self):
        """given 비용은 크게 줄었지만 T15의 text-review-clean만 후보에서 실패할 때 when 판정하면 then 글쓰기 규칙 단계에서 거부한다."""
        # given
        runs = both(runs_of("base", BASE_COSTS), runs_of("cand", LOW_COSTS, lost=("T15",)))

        # when
        outcome = loop_verdict.decide(runs, "base", "cand")

        # then
        self.assertEqual(outcome["verdict"], "reject")
        self.assertTrue(outcome["step"].startswith("writing rule"), outcome["step"])
        self.assertIn("T15", outcome["step"])

    def test_통과하는_작업_수가_줄면_text_review_clean을_잃지_않아도_거부된다(self):
        """given 후보에서 T16의 다른 필수 검사가 실패해 통과 작업이 하나 줄었을 때 when 판정하면 then 거부한다."""
        # given
        runs = both(runs_of("base", BASE_COSTS), runs_of("cand", LOW_COSTS, fails=("T16",)))

        # when
        outcome = loop_verdict.decide(runs, "base", "cand")

        # then
        self.assertEqual(outcome["verdict"], "reject")
        self.assertIn("passing tasks fell", outcome["step"])

    def test_기준선에서도_실패한_작업은_후보의_text_review_clean_실패로_세지_않는다(self):
        """given 기준선과 후보가 모두 T14에서 clean을 잃고 통과 수는 같을 때 when 판정하면 then 글쓰기 규칙은 통과한다."""
        # given
        runs = both(runs_of("base", BASE_COSTS, lost=("T14",)), runs_of("cand", LOW_COSTS, lost=("T14",)))

        # when
        state, _ = loop_verdict.writing_rule(runs, "base", "cand")

        # then
        self.assertEqual(state, "pass")


class CostClaimTest(unittest.TestCase):
    def test_다섯_번_비용_중앙값이_기준선_최저값_아래이고_두_호스트가_같으면_채택한다(self):
        """given 두 호스트 모두 후보 중앙값 0.75가 기준선 최저 1.0 아래이고 작업과 호스트 격차가 그대로일 때 when 판정하면 then 채택한다."""
        # given
        runs = both(runs_of("base", BASE_COSTS), runs_of("cand", LOW_COSTS))

        # when
        outcome = loop_verdict.decide(runs, "base", "cand")

        # then
        self.assertEqual(outcome["verdict"], "adopt", outcome["step"])

    def test_중앙값이_기준선_중앙값보다_낮아도_최저값_아래가_아니면_거부한다(self):
        """given 후보 중앙값 1.05가 기준선 중앙값 1.2보다 낮고 최저값 1.0보다는 높을 때 when 판정하면 then 청구 단계에서 거부한다."""
        # given
        runs = both(runs_of("base", BASE_COSTS), runs_of("cand", [0.9, 1.05, 1.1, 1.0, 1.15]))

        # when
        outcome = loop_verdict.decide(runs, "base", "cand")

        # then
        self.assertEqual(outcome["verdict"], "reject")
        self.assertTrue(outcome["step"].startswith("improvement claim"), outcome["step"])

    def test_한_호스트에서만_더_싸면_거부한다(self):
        """given Claude Code에서만 비용이 내리고 Codex는 그대로일 때 when 판정하면 then 청구 단계에서 거부한다."""
        # given
        runs = both(runs_of("base", BASE_COSTS), runs_of("cand", BASE_COSTS, claude_costs=LOW_COSTS))

        # when
        outcome = loop_verdict.decide(runs, "base", "cand")

        # then
        self.assertEqual(outcome["verdict"], "reject")
        self.assertIn("codex", outcome["step"])

    def test_호스트_격차가_넓어지면_비용이_내려도_거부한다(self):
        """given 두 호스트 비용이 모두 내렸지만 Claude Code만 훨씬 내려 호스트 격차가 첫 실행에서 커지고 다섯 번에서도 이전 최댓값을 넘을 때 when 판정하면 then 호스트 비교에서 거부한다."""
        # given
        runs = both(runs_of("base", BASE_COSTS), runs_of("cand", [0.9] * 5, claude_costs=[0.2] * 5))

        # when
        outcome = loop_verdict.decide(runs, "base", "cand")

        # then
        self.assertEqual(outcome["verdict"], "reject")
        self.assertTrue(outcome["step"].startswith("host comparison"), outcome["step"])

    def test_첫_실행_한_쌍만_있으면_다섯_번까지_이어_간다는_이유로_결정을_미룬다(self):
        """given 후보의 첫 쌍이 모든 작업에서 더 낮고 반복이 하나뿐일 때 when 판정하면 then 결정하지 않고 다섯 번까지 이어 간다고 적는다."""
        # given
        runs = both(runs_of("base", BASE_COSTS, reps=1), runs_of("cand", LOW_COSTS, reps=1))

        # when
        outcome = loop_verdict.decide(runs, "base", "cand")

        # then
        self.assertEqual(outcome["verdict"], "undecided")
        self.assertIn("continue to five", outcome["step"])

    def test_실행이_빠진_후보는_통과가_아니라_결정하지_않은_것이다(self):
        """given 후보에 T19 실행이 없을 때 when 판정하면 then 거부도 채택도 아닌 undecided다."""
        # given
        candidate = [run for run in runs_of("cand", LOW_COSTS) if run["case"] != "T19"]
        runs = both(runs_of("base", BASE_COSTS), candidate)

        # when
        outcome = loop_verdict.decide(runs, "base", "cand")

        # then
        self.assertEqual(outcome["verdict"], "undecided")
        self.assertIn("T19", outcome["step"])


class CombinedTest(unittest.TestCase):
    def adopted(self):
        return both(runs_of("base", BASE_COSTS), runs_of("a", LOW_COSTS), runs_of("b", LOW_COSTS))

    def test_채택한_후보가_둘_이상인데_합친_개정이_없으면_합친_개정은_결정하지_않은_상태다(self):
        """given 후보 a와 b가 채택되고 합친 개정 실행이 없을 때 when 모두 판정하면 then combined는 undecided이고 최종 채택은 비어 있다."""
        # given
        runs = self.adopted()

        # when
        entries = loop_verdict.decide_all(runs, "base", {"a": "a", "b": "b"})

        # then
        self.assertEqual([item["verdict"] for item in entries], ["adopt", "adopt", "undecided"])
        self.assertEqual(loop_verdict.final_adopted(entries), [])

    def test_합친_개정이_실패하면_마지막에_채택한_후보를_뺀다(self):
        """given 합친 개정이 T15의 text-review-clean을 잃을 때 when 판정하면 then combined는 거부되고 b를 빼며 최종 채택은 a 하나다."""
        # given
        runs = both(self.adopted(), runs_of("ab", LOW_COSTS, lost=("T15",)))

        # when
        entries = loop_verdict.decide_all(runs, "base", {"a": "a", "b": "b"}, "ab")

        # then
        combined = entries[-1]
        self.assertEqual((combined["candidate"], combined["verdict"], combined["dropped"]), ("combined", "reject", ["b"]))
        self.assertEqual(loop_verdict.final_adopted(entries), ["a"])

    def test_합친_개정이_세_조건을_지키면_채택한_후보_모두가_최종_채택이다(self):
        """given 합친 개정이 기준선보다 싸고 글쓰기 규칙과 호스트 격차를 지킬 때 when 판정하면 then 둘 다 최종 채택이다."""
        # given
        runs = both(self.adopted(), runs_of("ab", [0.6, 0.65, 0.7, 0.6, 0.7]))

        # when
        entries = loop_verdict.decide_all(runs, "base", {"a": "a", "b": "b"}, "ab")

        # then
        self.assertEqual(loop_verdict.final_adopted(entries), ["a", "b"])

    def test_채택한_후보가_하나이면_합친_개정_없이_그_후보가_최종_채택이다(self):
        """given a만 채택되고 b는 글쓰기 규칙에서 거부될 때 when 판정하면 then 최종 채택은 a다."""
        # given
        runs = both(runs_of("base", BASE_COSTS), runs_of("a", LOW_COSTS), runs_of("b", LOW_COSTS, lost=("T13",)))

        # when
        entries = loop_verdict.decide_all(runs, "base", {"a": "a", "b": "b"})

        # then
        self.assertEqual([item["verdict"] for item in entries], ["adopt", "reject"])
        self.assertEqual(loop_verdict.final_adopted(entries), ["a"])


class RecordFieldsTest(unittest.TestCase):
    def record(self):
        entries = [{"case": "T13", "variant": variant, "host": host, "rep": 1, "models": {"main": {"model": "claude-opus-5-5", "effort": "high"}},
                    "checks": {"text-review-clean": True}, "wall_seconds": 10.0, "cost_usd": 1.0, "passed": True,
                    "loop": {"reviewer_runs": 2, "check_stops": 0, "main_turns": 3,
                             "main_tokens": {"input": 1, "output": 2, "cache_read": 3, "cache_write": 4}}}
                   for variant in ("base", "a") for host in ("claude", "codex")]
        candidates = [{"candidate": "a", "variant": "a", "verdict": "undecided", "step": "writing rule: no run for T14"}]
        return records.build_record(102, ["T13"], {"base": "0123abc", "a": "4567def"}, entries,
                                    [{"case": "T13", "measure": "quality", "verdict": "pass", "step": "a: first run"}], candidates)

    def test_loop_수치와_후보_판정을_담은_기록은_검증을_통과한다(self):
        """given 실행마다 loop 수치와 candidates 항목이 있는 기록 when 검증하면 then 문제가 없다."""
        # given
        record = self.record()

        # when
        problems = records.validate_record(record)

        # then
        self.assertEqual(problems, [])

    def test_loop_수치나_후보_판정이_잘못된_기록은_이름을_들어_거부한다(self):
        """given 횟수가 음수이거나 후보 변형이 variants에 없거나 판정이 낯선 기록 when 검증하면 then 각각 이유를 든다."""
        for mutate, expected in (
            (lambda r: r["runs"][0]["loop"].update(main_turns=-1), "runs[0] loop main_turns is not a count"),
            (lambda r: r["runs"][0]["loop"].pop("reviewer_runs"), "runs[0] loop lacks reviewer_runs"),
            (lambda r: r["runs"][0].update(passed="yes"), "runs[0] passed is not true or false"),
            (lambda r: r["candidates"][0].update(variant="zzz"), "candidates[0] names a variant that is not in variants"),
            (lambda r: r["candidates"][0].update(verdict="maybe"), "candidates[0] verdict is not adopt, reject, or undecided"),
        ):
            with self.subTest(expected=expected):
                # given
                record = copy.deepcopy(self.record())
                mutate(record)

                # when
                problems = records.validate_record(record)

                # then
                self.assertIn(expected, problems)


if __name__ == "__main__":
    unittest.main()
