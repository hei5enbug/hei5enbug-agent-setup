"""Tests of the area coordinator decision (issue 99): seeded records, the committed record against the repository, and the candidate."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
sys.path.insert(0, str(E2E_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from harness import area_coordinator as decision  # noqa: E402
from harness import records  # noqa: E402
from test_e2e_eval_record_cli import run_cli, seed_campaign  # noqa: E402
from harness.area_coordinator import ADOPT, REJECT, UNDECIDED  # noqa: E402

CANDIDATE = E2E_ROOT / "candidates" / "99-area-coordinators.patch"
CANDIDATE_FILES = (
    "instructions/implementation-delegation.md", "docs/ko/instructions/implementation-delegation.ko.md", "config/model-registry.json",
)
SECTION = re.compile(r"^## Area coordinators$", re.MULTILINE)
MIRROR_SECTION = re.compile(r"^## 영역 코디네이터$", re.MULTILINE)
HOSTS = ("claude", "codex")
TWO_VARIANT, THREE_VARIANT = "two-layer", "three-layer"
L_CHECKS = ("hidden-tests-catalog", "hidden-tests-storage", "hidden-tests-cli", "hidden-tests-across-areas", "regressions", "agent-tests")
M_CHECKS = ("hidden-tests", "regressions", "agent-tests", "only-storage-area-changed", "no-area-coordinator-started")
MODELS = {"main": {"model": "claude-opus-5-5", "effort": "high"}}


def run(case: str, variant: str, host: str, rep: int, wall: float, cost: float = 5.0, failing: str | None = None) -> dict[str, Any]:
    names = L_CHECKS if case == "T57" else M_CHECKS
    checks = {name: name != failing for name in names}
    checks["readme-tags" if case == "T57" else "readme-backup"] = False
    return {"case": case, "variant": variant, "host": host, "rep": rep, "models": MODELS, "checks": checks,
            "wall_seconds": wall, "cost_usd": cost}


def seeded(before: dict[str, list[tuple]], after: dict[str, list[tuple]], m_failing: str | None = None, m: bool = True) -> dict[str, Any]:
    """A record with case L runs given per host as (wall, cost[, failing check]) in repetition order, and passing case M runs."""
    runs = []
    for variant, side in ((TWO_VARIANT, before), (THREE_VARIANT, after)):
        for host in HOSTS:
            for rep, values in enumerate(side[host], start=1):
                runs.append(run("T57", variant, host, rep, *values[:2], failing=values[2] if len(values) > 2 else None))
            if m:
                runs.append(run("T58", variant, host, 1, 60.0, failing=m_failing if variant == THREE_VARIANT else None))
    return {"issue": 99, "cases": ["T57", "T58"], "runs": runs, "verdicts": [{"case": "T57", "verdict": "pass", "step": "seeded"}],
            "variants": {TWO_VARIANT: {"revision": "aaaaaaaaaaaa", "layout": "two layers"},
                         THREE_VARIANT: {"revision": "bbbbbbbbbbbb", "layout": "three layers"}}}


def both(*values: tuple) -> dict[str, list[tuple]]:
    return {host: list(values) for host in HOSTS}


FIVE_TWO = [(100.0, 5.0), (110.0, 5.5), (120.0, 6.0), (130.0, 6.5), (140.0, 7.0)]
FIVE_FASTER = [(60.0, 5.0), (70.0, 5.5), (80.0, 6.0), (90.0, 6.5), (95.0, 7.0)]


class SeededRecordTest(unittest.TestCase):
    def decide(self, record: dict[str, Any]) -> dict[str, Any]:
        return decision.decide(record)

    def test_세_층이_첫_쌍과_둘째_쌍에서_더_빠르지_않으면_한_호스트만으로도_기각한다(self):
        """claude는 두 쌍 모두 느리고 codex는 아직 한 쌍뿐이어도 결정은 reject이고, 쌍이 하나뿐인 호스트는 둘째 쌍을 기다린다."""
        # Given
        slow = [(100.0, 5.0), (100.0, 5.0)]
        slower = [(120.0, 5.0), (110.0, 5.0)]
        one_pair = seeded(both((100.0, 5.0)), both((120.0, 5.0)))
        two_pairs = seeded({"claude": slow, "codex": slow[:1]}, {"claude": slower, "codex": [(80.0, 5.0)]})

        # When
        first, second = self.decide(one_pair), self.decide(two_pairs)

        # Then
        self.assertEqual(first["decision"], UNDECIDED)
        self.assertEqual(first["claim"]["hosts"]["claude"]["step"], "first pair is not lower")
        self.assertEqual(second["decision"], REJECT)
        self.assertEqual(second["claim"]["hosts"]["claude"]["step"], "two pairs are not lower")

    def test_세_층이_첫_쌍에서_빠르면_다섯_번까지_이어_가고_결정은_미정이다(self):
        """두 호스트 모두 첫 쌍이 더 빠르면 claim은 continue to five이고 결정은 undecided이다."""
        # Given
        record = seeded(both((100.0, 5.0)), both((60.0, 5.0)))

        # When
        outcome = self.decide(record)

        # Then
        self.assertEqual((outcome["decision"], outcome["claim"]["verdict"]), (UNDECIDED, "continue to five"))

    def test_다섯_번의_중앙값이_가장_빠른_두_층_실행보다_낮고_비용이_높지_않으며_M이_통과하면_두_호스트에서_채택한다(self):
        """두 호스트 다섯 쌍의 중앙값 시간이 가장 낮은 두 층 값 아래이고 중앙값 비용이 가장 높은 두 층 값 이하이며 M이 통과하면 adopt이다."""
        # Given
        record = seeded(both(*FIVE_TWO), both(*FIVE_FASTER))

        # When
        outcome = self.decide(record)

        # Then
        self.assertEqual(outcome["decision"], ADOPT)
        self.assertEqual(outcome["claim"]["verdict"], "accept")
        self.assertEqual(outcome["case_m"]["verdict"], "pass")

    def test_중앙값이_가장_빠른_두_층_실행보다_낮은_호스트가_하나뿐이면_기각한다(self):
        """claude는 중앙값이 낮고 codex는 가장 낮은 두 층 값 이상이면 결정은 reject이다."""
        # Given
        not_faster = [(100.0, 5.0), (105.0, 5.5), (110.0, 6.0), (115.0, 6.5), (120.0, 7.0)]
        record = seeded(both(*FIVE_TWO), {"claude": FIVE_FASTER, "codex": not_faster})

        # When
        outcome = self.decide(record)

        # Then
        self.assertEqual(outcome["decision"], REJECT)
        self.assertEqual(outcome["claim"]["hosts"]["claude"]["verdict"], "accept")
        self.assertEqual(outcome["claim"]["hosts"]["codex"]["step"], "median wall_seconds after is not below the lowest before")

    def test_중앙값_비용이_가장_높은_두_층_비용보다_높으면_시간이_빨라도_기각한다(self):
        """시간 중앙값은 낮지만 비용 중앙값이 두 층의 가장 높은 비용을 넘으면 reject이다."""
        # Given
        costly = [(60.0, 9.0), (70.0, 9.5), (80.0, 10.0), (90.0, 10.5), (95.0, 11.0)]
        record = seeded(both(*FIVE_TWO), both(*costly))

        # When
        outcome = self.decide(record)

        # Then
        self.assertEqual(outcome["decision"], REJECT)
        self.assertIn("median cost_usd after is above the highest before", outcome["claim"]["hosts"]["claude"]["step"])

    def test_세_층_실행이_필수_검사에서_하나라도_실패하면_기각하고_선택_검사의_실패는_세지_않는다(self):
        """다섯 쌍 중 한 세 층 실행이 영역 사이 검사에서 실패하면 reject이고, README 선택 검사만 실패한 기록은 통과로 읽는다."""
        # Given
        failing = [(60.0, 5.0, "hidden-tests-across-areas"), *FIVE_FASTER[1:]]
        failed = seeded(both(*FIVE_TWO), {"claude": failing, "codex": FIVE_FASTER})

        # When
        outcome = self.decide(failed)

        # Then
        self.assertEqual(outcome["decision"], REJECT)
        self.assertEqual(outcome["claim"]["hosts"]["claude"]["step"], "an after run failed a required check")
        self.assertEqual(self.decide(seeded(both(*FIVE_TWO), both(*FIVE_FASTER)))["decision"], ADOPT)

    def test_M이_실패하면_L의_claim이_받아들여져도_기각하고_M_실행이_없으면_미정이다(self):
        """세 층 M 실행에서 코디네이터가 시작되어 검사가 실패하면 reject이고, M 실행이 아예 없으면 undecided이다."""
        # Given
        started = seeded(both(*FIVE_TWO), both(*FIVE_FASTER), m_failing="no-area-coordinator-started")
        missing = seeded(both(*FIVE_TWO), both(*FIVE_FASTER), m=False)

        # When
        failed, absent = self.decide(started), self.decide(missing)

        # Then
        self.assertEqual((failed["claim"]["verdict"], failed["decision"]), ("accept", REJECT))
        self.assertEqual(absent["decision"], UNDECIDED)

    def test_레이아웃을_적지_않은_기록은_두_층과_세_층을_구분할_수_없어_오류이다(self):
        """variants에 layout이 없으면 어느 쪽이 세 층인지 알 수 없으므로 조용히 판정하지 않고 ValueError를 낸다."""
        # Given
        record = seeded(both(*FIVE_TWO), both(*FIVE_FASTER))
        record["variants"] = {name: {"revision": entry["revision"]} for name, entry in record["variants"].items()}

        # When / Then
        with self.assertRaises(ValueError):
            self.decide(record)


class RecordFormatTest(unittest.TestCase):
    def test_변형의_레이아웃은_두_이름_중_하나만_허용하고_빌더가_기록에_남긴다(self):
        """build_record는 layouts를 variants에 남기고, 알 수 없는 레이아웃 이름은 검증이 거부한다."""
        # Given
        runs = [run("T57", "a", "claude", 1, 100.0)]
        verdicts = [{"case": "T57", "verdict": "pass", "step": "seeded"}]

        # When
        built = records.build_record(99, ["T57"], {"a": "aaaaaaaaaaaa"}, runs, verdicts, {"a": records.LAYOUTS["three"]})
        bad = {**built, "variants": {"a": {"revision": "aaaaaaaaaaaa", "layout": "four layers"}}}

        # Then
        self.assertEqual(built["variants"]["a"]["layout"], "three layers")
        self.assertIn("variant a layout is not one of two layers, three layers", records.validate_record(bad))

    def test_코디네이터의_워커_모델은_실행기_상태_줄의_증거에서_기록의_층으로_읽는다(self):
        """area-coordinator 상태 줄의 worker_models는 role_runner:area-coordinator/worker 역할로 기록되고 effort는 not measured이다."""
        # Given
        status = {"role": "area-coordinator", "runner": "claude", "model": "claude-opus-5-5", "effort": "high",
                  "evidence": {"worker_models": ["claude-sonnet-5-5"]}}
        view = {"tool_calls": [{"id": "c", "name": "Bash", "input": {"command": "x"}, "result_text": json.dumps(status)}]}
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "view.json").write_text(json.dumps(view), encoding="utf-8")

            # When
            roles = records.run_models(folder, "claude", {})

        # Then
        self.assertEqual(roles["role_runner:area-coordinator"], {"model": "claude-opus-5-5", "effort": "high"})
        self.assertEqual(roles["role_runner:area-coordinator/worker"], {"model": "claude-sonnet-5-5", "effort": "not measured"})


class LayoutsOptionTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        seed_campaign(self.root)

    def test_record_명령의_layouts_옵션은_변경_전후_변형의_층_구성을_기록에_남긴다(self):
        """`--layouts two,three`는 before 변형에 two layers를, after 변형에 three layers를 쓴다."""
        # Given
        arguments = ("--layouts", "two,three")

        # When
        code, _, error = run_cli(self.root, *arguments)

        # Then
        written = json.loads((self.root / "records" / "92.json").read_text(encoding="utf-8"))
        self.assertEqual((code, error), (0, ""))
        self.assertEqual({name: entry["layout"] for name, entry in written["variants"].items()},
                         {"base": "two layers", "changed": "three layers"})

    def test_알_수_없거나_개수가_틀린_layouts는_기록을_쓰기_전에_거부한다(self):
        """`four,three`나 `two`는 오류로 끝나고 기록 파일이 만들어지지 않는다."""
        # Given
        bad = ("four,three", "two")

        # When
        results = [run_cli(self.root, "--layouts", value) for value in bad]

        # Then
        self.assertTrue(all(code != 0 and "--layouts takes the layout" in error for code, _, error in results), results)
        self.assertFalse((self.root / "records" / "92.json").exists())


def observed_state(root: Path) -> dict[str, bool]:
    """The three things the adoption adds or the rejection removes: the instruction section, the registered role, and the measurement role."""
    delegation = (root / "instructions/implementation-delegation.md").read_text(encoding="utf-8")
    registry = json.loads((root / "config/model-registry.json").read_text(encoding="utf-8"))
    mirror = (root / "docs/ko/instructions/implementation-delegation.ko.md").read_text(encoding="utf-8")
    config = (root / "scripts/role_runner_config.py").read_text(encoding="utf-8")
    return {
        "section": bool(SECTION.search(delegation)), "mirror_section": bool(MIRROR_SECTION.search(mirror)),
        "registered": "area_coordinator" in registry["runner"], "role": "COORDINATOR_ROLE" in config,
    }


def expected_state(outcome: str | None) -> dict[str, bool]:
    adopted = outcome == ADOPT
    return {"section": adopted, "mirror_section": adopted, "registered": adopted, "role": outcome != REJECT}


class RepositoryStateTest(unittest.TestCase):
    def test_절과_등록한_역할은_기록이_채택할_때만_있고_기각하면_측정용_역할도_없다(self):
        """기록이 없으면 측정용 역할만, 채택하면 절과 미러 절과 등록 항목까지, 기각하면 어느 것도 저장소에 없다."""
        # Given
        outcome = decision.record_decision(records.RECORDS_DIR)

        # When
        state = observed_state(REPO_ROOT)

        # Then
        self.assertEqual(state, expected_state(outcome))

    def test_채택한_기록은_두_사례의_호스트_비교가_통과한다(self):
        """커밋한 기록이 채택이면 T57과 T58에서 #92의 호스트 비교가 통과여야 한다. 기록이 없거나 채택이 아니면 확인할 것이 없다."""
        # Given
        path = records.RECORDS_DIR / "99.json"
        result = decision.decide(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else None

        # When
        comparison = result["host_comparison"] if result and result["decision"] == ADOPT else "pass"

        # Then
        self.assertEqual(comparison, "pass")

    def test_호스트_비교는_채택_결정과_별개로_계산되어_호스트_격차가_커지면_통과가_아니다(self):
        """codex 시간이 claude의 0.3배로 벌어진 채택 기록은 decision이 adopt여도 host_comparison은 pass가 아니다."""
        # Given
        even = seeded(both(*FIVE_TWO), both(*FIVE_FASTER))
        skewed = seeded(both(*FIVE_TWO), {"claude": FIVE_FASTER, "codex": [(wall * 0.3, cost) for wall, cost in FIVE_FASTER]})

        # When
        outcomes = [decision.decide(record) for record in (even, skewed)]

        # Then
        self.assertEqual([item["decision"] for item in outcomes], [ADOPT, ADOPT])
        self.assertEqual(outcomes[0]["host_comparison"], "pass")
        self.assertNotEqual(outcomes[1]["host_comparison"], "pass")

    def test_기대_상태_표는_기록_없음_기각_채택을_서로_다르게_가리킨다(self):
        """상태 판별이 세 경우를 구분한다: 기록 없음은 역할만, 기각은 아무것도 없음, 채택은 모두 있음."""
        # Given
        outcomes = (None, REJECT, ADOPT, UNDECIDED)

        # When
        states = [expected_state(outcome) for outcome in outcomes]

        # Then
        self.assertEqual(states[0], {"section": False, "mirror_section": False, "registered": False, "role": True})
        self.assertEqual(states[1], {"section": False, "mirror_section": False, "registered": False, "role": False})
        self.assertEqual(states[2], {"section": True, "mirror_section": True, "registered": True, "role": True})
        self.assertEqual(states[3], states[0])


class CandidateTest(unittest.TestCase):
    def copy_files(self, destination: Path) -> None:
        for name in (*CANDIDATE_FILES, "scripts/role_runner_config.py"):
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / name, target)

    def test_후보_패치는_채택_상태를_정확히_만들고_세션_지침과_다른_파일은_건드리지_않는다(self):
        """패치를 적용한 사본은 절, 미러 절, 등록 항목이 모두 있는 채택 상태이고 패치가 바꾸는 파일은 세 파일뿐이다."""
        # Given
        if not CANDIDATE.is_file():
            self.skipTest("the candidate is applied or dropped")
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory)
            self.copy_files(copy)
            before = observed_state(copy)

            # When
            applied = subprocess.run(["git", "apply", "-p1", str(CANDIDATE)],
                                     cwd=copy, capture_output=True, text=True)
            after = observed_state(copy)
            touched = re.findall(r"^diff --git a/(\S+) b/", CANDIDATE.read_text(encoding="utf-8"), re.MULTILINE)

        # Then
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(before, expected_state(None))
        self.assertEqual(after, expected_state(ADOPT))
        self.assertEqual(sorted(touched), sorted(CANDIDATE_FILES))

    def test_후보에_더해진_절은_세_층의_규칙을_모두_말한다(self):
        """절은 시작 조건(영역 셋, 영역당 작업 둘), 코디네이터의 역할과 반환, 코디네이터 없는 영역, 네 번째 층 금지를 담는다."""
        # Given
        text = CANDIDATE.read_text(encoding="utf-8") if CANDIDATE.is_file() else ""
        if not text:
            self.skipTest("the candidate is applied or dropped")

        # When
        added = " ".join(line[1:] for line in text.splitlines() if line.startswith("+") and not line.startswith("+++"))

        # Then
        for phrase in ("at least three areas", "at least two tasks", "role_runner.py area-coordinator", "its branch, the check evidence, and the open items",
                       "An area with one task gets no coordinator", "no fourth layer", "its workers start nothing"):
            self.assertIn(phrase, " ".join(added.split()))


if __name__ == "__main__":
    unittest.main()
