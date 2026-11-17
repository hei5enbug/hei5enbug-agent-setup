"""Tests of the adoption decision for the candidate loop shapes of issue 102, applied to seeded records."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))

from harness import loop_decision, records  # noqa: E402
from harness.loop_decision import ADOPTED, DROPPED, REJECTED, UNDECIDED, WRITING_TASKS  # noqa: E402

HOST_COST = {"claude": 1.0, "codex": 1.5}
HOST_WALL = {"claude": 100.0, "codex": 150.0}
LOWER = 0.6


def run(task: str, variant: str, host: str, rep: int, *, cost: float, clean: bool = True, passed: bool = True) -> dict[str, Any]:
    return {"case": task, "variant": variant, "host": host, "rep": rep, "passed": passed and clean, "checks": {"text-review-clean": clean},
            "wall_seconds": HOST_WALL[host], "cost_usd": cost}


def variant_runs(variant: str, *, scale: float = 1.0, reps: int = 5, clean: dict[tuple[str, str], bool] | None = None,
                 cost_of: Any = None) -> list[dict[str, Any]]:
    """Every writing task once per host, and `reps` runs of the three claim tasks; cost is the host's base cost scaled by `scale`."""
    found = []
    for task in WRITING_TASKS:
        for host in HOST_COST:
            for rep in range(1, (reps if task in loop_decision.CLAIM_TASKS else 1) + 1):
                cost = cost_of(host, rep) if cost_of else HOST_COST[host] * scale * (1 + 0.01 * rep)
                found.append(run(task, variant, host, rep, cost=cost, clean=(clean or {}).get((task, host), True)))
    return found


def verdicts(runs: list[dict[str, Any]]) -> dict[str, str]:
    return {item["candidate"]: item["verdict"] for item in loop_decision.decide(runs)["decisions"]}


class SingleCandidateTest(unittest.TestCase):
    def test_기준선에서_깨끗하던_T15가_후보에서_깨끗하지_않으면_비용이_낮아도_기각한다(self):
        """T15의 text-review-clean이 기준선에서 통과하고 후보에서 실패하면, 비용이 모두 낮아도 글쓰기 규칙으로 기각하고 그 단계를 적는다."""
        # given
        runs = variant_runs("baseline") + variant_runs("a", scale=LOWER, clean={("T15", "codex"): False})

        # when
        decision = loop_decision.decide(runs)["decisions"][0]

        # then
        self.assertEqual((decision["candidate"], decision["verdict"]), ("a", REJECTED))
        self.assertIn("T15 text-review-clean passes on the baseline and fails on a on codex", decision["step"])

    def test_다섯_번의_비용_중앙값이_기준선의_가장_낮은_값보다_낮고_두_호스트_모두이고_과제를_잃지_않으면_채택한다(self):
        """중앙값이 가장 낮은 기준선 비용 밑이고 두 호스트에서 같고 호스트 간 격차가 그대로면 채택한다."""
        # given
        runs = variant_runs("baseline") + variant_runs("b", scale=LOWER)

        # when
        decision = loop_decision.decide(runs)["decisions"]

        # then
        self.assertEqual([(item["candidate"], item["verdict"]) for item in decision], [("b", ADOPTED)])

    def test_중앙값이_기준선_중앙값보다만_낮고_가장_낮은_값_밑이_아니면_기각한다(self):
        """후보 비용 중앙값이 기준선 중앙값 밑이어도 기준선의 가장 낮은 값 이상이면 개선 주장이 기각되어 후보도 기각된다."""
        # given
        spread = {1: 1.0, 2: 1.1, 3: 1.2, 4: 1.3, 5: 1.4}
        candidate = {1: 1.4, 2: 1.3, 3: 1.05, 4: 1.0, 5: 0.9}
        runs = (variant_runs("baseline", cost_of=lambda host, rep: HOST_COST[host] * spread[rep])
                + variant_runs("c", cost_of=lambda host, rep: HOST_COST[host] * candidate[rep]))

        # when
        decision = loop_decision.decide(runs)["decisions"][0]

        # then
        self.assertEqual((decision["candidate"], decision["verdict"]), ("c", REJECTED))
        self.assertEqual(decision["step"], "T13 claim on cost_usd: claude: median cost_usd after is not below the lowest before, "
                                           "codex: median cost_usd after is not below the lowest before")

    def test_한_호스트에서만_싸진_후보는_기각한다(self):
        """Claude Code에서만 비용이 내려가고 Codex에서는 그대로이면 두 호스트에서 개선 주장이 서야 하므로 기각한다."""
        # given
        runs = variant_runs("baseline") + variant_runs("a", cost_of=lambda host, rep: HOST_COST[host] * (LOWER if host == "claude" else 1.0) * (1 + 0.01 * rep))

        # when
        decision = loop_decision.decide(runs)["decisions"][0]

        # then
        self.assertEqual(decision["verdict"], REJECTED)
        self.assertEqual(decision["step"], "T13 claim on cost_usd: claude: five runs, codex: median cost_usd after is not below the lowest before")

    def test_첫_쌍만_낮고_다섯_번을_다_돌리지_않은_후보는_채택도_기각도_하지_않는다(self):
        """다섯 번 중 한 번만 돌아 개선 주장이 아직 결정되지 않으면 채택하지도 기각하지도 않고 대기 단계를 적는다."""
        # given
        runs = variant_runs("baseline", reps=1) + variant_runs("b", scale=LOWER, reps=1)

        # when
        decision = loop_decision.decide(runs)["decisions"][0]

        # then
        self.assertEqual(decision["verdict"], UNDECIDED)
        self.assertIn("continue to five", decision["step"])

    def test_글쓰기_과제의_run이_없으면_후보를_채택하지_않고_대기한다(self):
        """T13~T20 중 하나의 text-review-clean 결과가 후보에 없으면 규칙을 판정할 수 없어 채택하지 않는다."""
        # given
        runs = variant_runs("baseline") + [item for item in variant_runs("a", scale=LOWER) if item["case"] != "T17"]

        # when
        decision = loop_decision.decide(runs)["decisions"][0]

        # then
        self.assertEqual(decision["verdict"], UNDECIDED)
        self.assertIn("T17", decision["step"])


class CombinationTest(unittest.TestCase):
    def two_adopted(self, **combined: Any) -> list[dict[str, Any]]:
        return variant_runs("baseline") + variant_runs("a", scale=LOWER) + variant_runs("b", scale=LOWER) + combined.get("runs", [])

    def test_합친_개정이_실패하면_마지막에_채택한_후보를_빼고_채택_후보는_그대로_둔다(self):
        """a와 b를 각각 채택했는데 a+b가 T15에서 깨끗하지 않으면 b를 뺀다. a는 채택된 채로 남고 합친 개정은 기각으로 기록된다."""
        # given
        runs = self.two_adopted(runs=variant_runs("a+b", scale=0.4, clean={("T15", "claude"): False}))

        # when
        found = verdicts(runs)

        # then
        self.assertEqual(found, {"a": ADOPTED, "b": DROPPED, "a+b": REJECTED})

    def test_합친_개정이_조건을_모두_만족하면_둘_다_채택하고_합친_개정의_run이_없으면_대기한다(self):
        """합친 개정이 같은 규칙을 통과하면 a와 b가 함께 채택되고, 합친 개정을 아직 돌리지 않았으면 둘 다 대기 상태다."""
        # given
        both = self.two_adopted(runs=variant_runs("a+b", scale=0.4))

        # when
        held = verdicts(both)
        waiting = verdicts(self.two_adopted())

        # then
        self.assertEqual(held, {"a": ADOPTED, "b": ADOPTED, "a+b": ADOPTED})
        self.assertEqual(waiting, {"a": UNDECIDED, "b": UNDECIDED})

    def test_셋을_모두_채택하면_합친_개정이_실패할_때마다_마지막_후보를_빼고_남은_조합을_다시_본다(self):
        """a, b, c를 채택했는데 a+b+c가 실패하면 c를 빼고 a+b를 보며, a+b도 실패하면 b를 뺀다."""
        # given
        runs = (self.two_adopted(runs=variant_runs("c", scale=LOWER)) + variant_runs("a+b+c", scale=0.4, clean={("T20", "codex"): False})
                + variant_runs("a+b", scale=0.4, clean={("T13", "claude"): False}))

        # when
        found = verdicts(runs)

        # then
        self.assertEqual(found, {"a": ADOPTED, "b": DROPPED, "c": DROPPED, "a+b+c": REJECTED, "a+b": REJECTED})


class RecordValidationTest(unittest.TestCase):
    def record(self, runs: list[dict[str, Any]]) -> dict[str, Any]:
        entries = [{**item, "models": {"main": {"model": "claude-opus-5-5", "effort": "high"}}} for item in runs]
        decided = loop_decision.decide(entries)
        return {"issue": 102, "cases": list(WRITING_TASKS), "variants": {name: {"revision": "abc123"} for name in {r["variant"] for r in runs}},
                "runs": entries, "verdicts": decided["entries"], "decisions": decided["decisions"]}

    def test_기록의_결정이_실제_run과_다르면_검증이_알려_준다(self):
        """기록의 결정을 손으로 adopted로 바꾸면 run에서 다시 계산한 결정과 달라 검증이 실패하고, 계산 그대로이면 통과한다."""
        # given
        record = self.record(variant_runs("baseline") + variant_runs("a", scale=LOWER, clean={("T15", "codex"): False}))
        honest = records.validate_record(record)
        record["decisions"][0] = {**record["decisions"][0], "verdict": ADOPTED}

        # when
        tampered = records.validate_record(record)

        # then
        self.assertEqual(honest, [])
        self.assertIn("decisions differ from the ones the runs of the record give", tampered)


if __name__ == "__main__":
    unittest.main()
