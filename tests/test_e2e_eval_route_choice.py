"""Tests for the choice between doing a three-to-five-file change in the main session and delegating it (#109)."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
sys.path.insert(0, str(E2E_ROOT))

from harness import cli, records, route_choice  # noqa: E402
from test_e2e_eval_record_cli import seed_run, write  # noqa: E402

HOSTS = ("claude", "codex")


def runs(*rows):
    """Runs per (case, host): each row is (case, host, passed, wall_seconds, cost_usd)."""
    found: dict = {}
    for case, host, passed, wall, cost in rows:
        found.setdefault((case, host), []).append({"passed": passed, "wall_seconds": wall, "cost_usd": cost})
    return found


def grid(case_values: dict, passed: bool = True):
    """One run per case and host from {case: (claude wall, codex wall, claude cost, codex cost)}."""
    rows = []
    for case, (claude_wall, codex_wall, claude_cost, codex_cost) in case_values.items():
        rows += [(case, "claude", passed, claude_wall, claude_cost), (case, "codex", passed, codex_wall, codex_cost)]
    return runs(*rows)


PASSING = {"main": "pass", "delegate": "pass"}


class ChooseRouteTest(unittest.TestCase):
    def test_두_경로가_모두_통과하면_비용이_확연히_낮은_경로를_고른다(self):
        """given 둘 다 통과하고 시간이 비슷하며 비용이 30퍼센트 차이 나는 경로 when 고르면 then 싼 경로가 이긴다."""
        # given
        candidates = {"main": grid({"T20": (100, 110, 1.30, 1.30)}), "delegate": grid({"T20": (100, 110, 1.00, 1.00)})}

        # when
        choice = route_choice.choose_route(candidates, PASSING)

        # then
        self.assertEqual((choice["verdict"], choice["route"]), ("winner", "delegate"))

    def test_비용이_10퍼센트나_5센트_안이면_동률로_보고_더_빠른_경로를_고른다(self):
        """given 비용 차이가 10퍼센트 이내, 또는 20퍼센트지만 5센트 이내인 두 경우 when 고르면 then 둘 다 빠른 경로가 이긴다."""
        # given
        within_ratio = {"main": grid({"T20": (100, 100, 1.00, 1.00)}), "delegate": grid({"T20": (90, 90, 1.09, 1.09)})}
        within_dollars = {"main": grid({"T20": (100, 100, 0.20, 0.20)}), "delegate": grid({"T20": (90, 90, 0.24, 0.24)})}

        # when
        by_ratio = route_choice.choose_route(within_ratio, PASSING)
        by_dollars = route_choice.choose_route(within_dollars, PASSING)

        # then
        self.assertEqual((by_ratio["route"], by_dollars["route"]), ("delegate", "delegate"))

    def test_비용_차이가_동률_범위를_넘으면_느려도_싼_경로가_이긴다(self):
        """given 비용 차이가 11퍼센트이고 5센트보다 큰 경로 when 고르면 then 싼 경로가 이긴다."""
        # given
        candidates = {"main": grid({"T20": (100, 100, 1.00, 1.00)}), "delegate": grid({"T20": (110, 110, 1.12, 1.12)})}

        # when
        choice = route_choice.choose_route(candidates, PASSING)

        # then
        self.assertEqual(choice["route"], "main")

    def test_어느_사례에서든_가장_빠른_경로보다_1점5배와_60초를_모두_넘게_느리면_싸도_탈락한다(self):
        """given 한 사례에서만 2배, 100초 느린 싼 경로 when 고르면 then 그 경로는 탈락하고 사유가 그 사례를 가리킨다."""
        # given
        candidates = {
            "main": grid({"T20": (100, 100, 1.00, 1.00), "T65": (100, 100, 1.00, 1.00)}),
            "delegate": grid({"T20": (100, 100, 0.40, 0.40), "T65": (200, 100, 0.40, 0.40)}),
        }

        # when
        choice = route_choice.choose_route(candidates, PASSING)

        # then
        self.assertEqual(choice["route"], "main")
        self.assertIn("T65 on claude", choice["table"]["delegate"]["dropped"])

    def test_느린_정도가_배수와_초_중_하나만_넘으면_탈락하지_않는다(self):
        """given 2배지만 40초 느린 경로, 1.4배지만 120초 느린 경로 when 고르면 then 둘 다 탈락하지 않고 싼 쪽이 이긴다."""
        # given
        ratio_only = {"main": grid({"T20": (40, 40, 1.00, 1.00)}), "delegate": grid({"T20": (80, 80, 0.40, 0.40)})}
        seconds_only = {"main": grid({"T20": (300, 300, 1.00, 1.00)}), "delegate": grid({"T20": (420, 420, 0.40, 0.40)})}

        # when
        first = route_choice.choose_route(ratio_only, PASSING)
        second = route_choice.choose_route(seconds_only, PASSING)

        # then
        self.assertEqual((first["route"], second["route"]), ("delegate", "delegate"))

    def test_한_사례라도_실패한_경로나_비교가_실패한_경로는_빠지고_남은_하나가_이긴다(self):
        """given 한 호스트에서 실패한 경로 when 고르면 then 그 경로는 빠지고 다른 경로가 유일한 통과로 이긴다."""
        # given
        failing = runs(("T20", "claude", True, 50, 0.1), ("T20", "codex", False, 50, 0.1))
        candidates = {"main": grid({"T20": (100, 100, 1.00, 1.00)}), "delegate": failing}

        # when
        choice = route_choice.choose_route(candidates, {"main": "pass", "delegate": "pass"})
        compare_failed = route_choice.choose_route({"main": grid({"T20": (100, 100, 1, 1)}), "delegate": grid({"T20": (50, 50, 0.1, 0.1)})},
                                                   {"main": "pass", "delegate": "fail"})

        # then
        self.assertEqual((choice["verdict"], choice["route"]), ("winner", "main"))
        self.assertEqual((compare_failed["verdict"], compare_failed["route"]), ("winner", "main"))
        self.assertIn("a case fails", choice["table"]["delegate"]["dropped"])

    def test_통과한_경로가_없으면_승자_없음이고_이유를_남긴다(self):
        """given 두 경로 모두 한 사례에서 실패 when 고르면 then no winner이고 route가 없다."""
        # given
        failing = runs(("T20", "claude", False, 50, 0.1), ("T20", "codex", True, 50, 0.1))
        candidates = {"main": failing, "delegate": failing}

        # when
        choice = route_choice.choose_route(candidates, {"main": "fail", "delegate": "fail"})

        # then
        self.assertEqual((choice["verdict"], choice["route"]), ("no winner", None))
        self.assertIn("no route passes every case", choice["steps"])

    def test_값이_없거나_비교가_끝나지_않았으면_결정하지_않고_측정되지_않음이다(self):
        """given 비용이 없는 실행, 실행이 없는 칸, 반복이 필요한 비교 when 고르면 then 모두 not measured이고 route가 없다."""
        # given
        no_cost = {"main": runs(("T20", "claude", True, 100, None)), "delegate": grid({"T20": (100, 100, 1, 1)})}
        no_run = {"main": grid({"T20": (100, 100, 1, 1)}), "delegate": runs(("T20", "claude", True, 100, 1.0))}
        complete = {"main": grid({"T20": (100, 100, 1, 1)}), "delegate": grid({"T20": (100, 100, 1, 1)})}

        # when
        first = route_choice.choose_route(no_cost, PASSING)
        second = route_choice.choose_route(no_run, PASSING)
        third = route_choice.choose_route(complete, {"main": "pass", "delegate": "repeat"})

        # then
        self.assertEqual([item["verdict"] for item in (first, second, third)], ["not measured"] * 3)
        self.assertEqual([item["route"] for item in (first, second, third)], [None] * 3)
        self.assertIn("has no run for T20 on codex", second["steps"][0])

    def test_반복_실행은_사례별_중앙값으로_견주고_비용은_통과한_실행당으로_나눈다(self):
        """given 같은 칸에 세 번 돈 경로 when 고르면 then 시간은 중앙값이고 비용 합계를 실행 수로 나눈다."""
        # given
        main = runs(*[("T20", host, True, wall, 1.0) for host in HOSTS for wall in (90, 100, 400)])
        delegate = runs(*[("T20", host, True, wall, 0.5) for host in HOSTS for wall in (100, 110, 120)])

        # when
        choice = route_choice.choose_route({"main": main, "delegate": delegate}, PASSING)

        # then
        self.assertEqual(choice["table"]["main"]["wall_seconds"], 200.0)
        self.assertEqual(choice["table"]["delegate"]["cost_per_pass"], 0.5)
        self.assertEqual(choice["route"], "delegate")


class RouteRecordTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def seed(self, after_main_codex_passes: bool = True, delegate_wall: float = 160.0) -> None:
        """before holds the host gap 1.5 in time and in cost; each route keeps it, so each passes the comparison."""
        write(self.root / "camp" / "campaign.json", {"inputs": {"variant_shas": {
            "before": "0123456789abcdef", "route-main": "0123456789abcdef", "route-delegate": "0123456789abcdef"}}})
        for task in ("T65", "T66"):
            for host, factor in (("claude", 1.0), ("codex", 1.5)):
                seed_run(self.root, task, "before", host, 1, True, 100.0 * factor, 1.0 * factor)
                passed = after_main_codex_passes or host == "claude"
                seed_run(self.root, task, "route-main", host, 1, passed, 80.0 * factor, 0.5 * factor)
                seed_run(self.root, task, "route-delegate", host, 1, True, delegate_wall * factor, 0.4 * factor)

    def record(self, *extra: str):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["route-record", "--run-root", str(self.root), "--campaign", "camp", "--issue", "109", "--before", "before",
                             "--routes", "route-main,route-delegate", "--variants-root", str(E2E_ROOT / "variants"),
                             "--records-dir", str(self.root / "records"), *extra])
        written = self.root / "records" / "109.json"
        return code, out.getvalue(), err.getvalue(), json.loads(written.read_text(encoding="utf-8")) if written.is_file() else None

    def test_경로별_전후_판정과_고른_경로를_담은_검증을_통과하는_기록을_쓴다(self):
        """given 두 경로가 두 호스트에서 끝난 캠페인 when route-record를 실행하면 then 기록이 검증을 통과하고 경로와 선택이 담긴다."""
        # given
        self.seed()

        # when
        code, out, err, record = self.record()

        # then
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(records.validate_record(record), [])
        self.assertEqual(record["routes"], {"route-main": "main", "route-delegate": "delegate"})
        self.assertEqual({(run["variant"], run["host"], run["case"]) for run in record["runs"]},
                         {(variant, host, case) for variant in ("before", "route-main", "route-delegate") for host in HOSTS for case in ("T65", "T66")})
        self.assertEqual(record["route_choice"]["route"], "main")
        self.assertIn("route choice: winner main", out)
        tagged = {(item["variant"], item["case"]): item["verdict"] for item in record["verdicts"] if "measure" not in item}
        self.assertEqual(set(tagged.values()), {"pass"})
        self.assertEqual(len(tagged), 4)

    def test_한_경로가_호스트에서_실패하면_기록의_선택은_다른_경로다(self):
        """given main 경로가 Codex에서 실패 when route-record를 실행하면 then 선택은 delegate이고 main의 판정은 fail이다."""
        # given
        self.seed(after_main_codex_passes=False)

        # when
        _, out, _, record = self.record()

        # then
        self.assertEqual(record["route_choice"], {"verdict": "winner", "route": "delegate", "steps": record["route_choice"]["steps"]})
        verdicts = {item["variant"]: item["verdict"] for item in record["verdicts"] if item["case"] == "T65" and "measure" not in item}
        self.assertEqual(verdicts, {"route-main": "fail", "route-delegate": "pass"})
        self.assertIn("route-main T65: fail", out)

    def test_경로가_너무_느리면_기록은_다른_경로를_고르고_사유를_남긴다(self):
        """given delegate가 어느 사례에서든 2배 느린 캠페인 when route-record를 실행하면 then main이 선택되고 단계에 탈락 사유가 있다."""
        # given
        self.seed(delegate_wall=200.0)

        # when
        _, _, _, record = self.record()

        # then
        self.assertEqual(record["route_choice"]["route"], "main")
        self.assertTrue(any("route delegate dropped: slower" in step for step in record["route_choice"]["steps"]))

    def test_변형이_경로를_강제하지_않으면_거절한다(self):
        """given 경로 없는 변형을 --routes에 준 명령 when 실행하면 then 오류로 끝나고 기록을 쓰지 않는다."""
        # given
        self.seed()

        # when
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["route-record", "--run-root", str(self.root), "--campaign", "camp", "--issue", "109", "--before", "before",
                             "--routes", "before,route-main", "--variants-root", str(E2E_ROOT / "variants"),
                             "--records-dir", str(self.root / "records")])

        # then
        self.assertEqual(code, 1)
        self.assertIn("each force a different route", err.getvalue())
        self.assertFalse((self.root / "records" / "109.json").exists())


class RecordValidationTest(unittest.TestCase):
    BASE = {
        "issue": 109, "cases": ["T65"], "variants": {"before": {"revision": "abc"}, "route-main": {"revision": "abc"}},
        "runs": [{"case": "T65", "variant": "before", "host": "claude", "models": {"main": {"model": "claude-opus-5-5", "effort": "high"}},
                  "checks": {"hidden-tests": True}, "wall_seconds": 10.0, "cost_usd": 1.0}],
        "verdicts": [{"case": "T65", "verdict": "pass", "step": "first run", "variant": "route-main"}],
    }

    def test_경로_구역이_잘못되면_기록_검증이_각각_잡아낸다(self):
        """given 알 수 없는 변형 이름, 경로 이름, 승자 없는 선택을 가진 기록 when 검증하면 then 각 문제를 알린다."""
        # given
        bad = {**self.BASE, "verdicts": [{**self.BASE["verdicts"][0], "variant": "ghost"}],
               "routes": {"route-main": "both"}, "route_choice": {"verdict": "winner", "route": None, "steps": ["x"]}}

        # when
        problems = records.validate_record(bad)

        # then
        self.assertTrue(any("variant that is not in variants" in item for item in problems))
        self.assertTrue(any("a route outside" in item for item in problems))
        self.assertTrue(any("exactly when its verdict is winner" in item for item in problems))

    def test_경로_구역이_없는_기록과_올바른_경로_구역은_통과한다(self):
        """given 구역이 없는 기록과 올바른 구역을 가진 기록 when 검증하면 then 문제가 없다."""
        # given
        good = {**self.BASE, "routes": {"route-main": "main"},
                "route_choice": {"verdict": "winner", "route": "main", "steps": ["route main chosen"]}}

        # when
        problems = [records.validate_record(self.BASE), records.validate_record(good)]

        # then
        self.assertEqual(problems, [[], []])


if __name__ == "__main__":
    unittest.main()
