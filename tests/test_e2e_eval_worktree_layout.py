"""Tests of the one-worktree-per-worker decision (issue 98): seeded records, the committed record against the repository, and the candidate."""

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

from harness import isolated_worktrees as decision  # noqa: E402
from harness import records  # noqa: E402
from harness.isolated_worktrees import ADOPT, REJECT, UNDECIDED  # noqa: E402
from test_e2e_eval_record_cli import run_cli, seed_campaign  # noqa: E402

CANDIDATE = E2E_ROOT / "candidates" / "98-worktree-per-worker.patch"
CANDIDATE_FILES = ("instructions/implementation-delegation.md", "docs/ko/instructions/implementation-delegation.ko.md")
SCHEDULING = re.compile(r"^## Scheduling$(.*?)^## ", re.MULTILINE | re.DOTALL)
MIRROR_SCHEDULING = re.compile(r"^## 일정 관리$(.*?)^## ", re.MULTILINE | re.DOTALL)
RULE = "one worktree per worker"
MIRROR_RULE = "worker마다 worktree 하나"
HOSTS = ("claude", "codex")
SEQUENTIAL_VARIANT, ISOLATED_VARIANT = "sequential", "isolated"
MODELS = {"main": {"model": "claude-opus-5-5", "effort": "high"}}


def run(case: str, variant: str, host: str, rep: int, wall: float, cost: float = 5.0, failing: str | None = None) -> dict[str, Any]:
    checks = {name: name != failing for name in decision.required_checks(case)}
    return {"case": case, "variant": variant, "host": host, "rep": rep, "models": MODELS, "checks": checks,
            "wall_seconds": wall, "cost_usd": cost}


def seeded(before: dict[str, list[tuple]], after: dict[str, list[tuple]], d_failing: str | None = None,
           t05_failing: str | None = None, with_t05: bool = True) -> dict[str, Any]:
    """A record with case S runs given per host as (wall, cost[, failing check]) in repetition order, and one passing run of
    D and T05 per variant and host, unless a failing check is named for the isolated variant."""
    runs = []
    for variant, side in ((SEQUENTIAL_VARIANT, before), (ISOLATED_VARIANT, after)):
        isolated = variant == ISOLATED_VARIANT
        for host in HOSTS:
            for rep, values in enumerate(side[host], start=1):
                runs.append(run("T55", variant, host, rep, *values[:2], failing=values[2] if len(values) > 2 else None))
            runs.append(run("T56", variant, host, 1, 60.0, failing=d_failing if isolated else None))
            if with_t05:
                runs.append(run("T05", variant, host, 1, 90.0, failing=t05_failing if isolated else None))
    return {"issue": 98, "cases": ["T55", "T56", "T05"], "runs": runs,
            "verdicts": [{"case": "T55", "verdict": "pass", "step": "seeded"}],
            "variants": {SEQUENTIAL_VARIANT: {"revision": "aaaaaaaaaaaa", "workspace": "sequential"},
                         ISOLATED_VARIANT: {"revision": "bbbbbbbbbbbb", "workspace": "one worktree per worker"}}}


def both(*values: tuple) -> dict[str, list[tuple]]:
    return {host: list(values) for host in HOSTS}


FIVE_SEQUENTIAL = [(100.0, 5.0), (110.0, 5.5), (120.0, 6.0), (130.0, 6.5), (140.0, 7.0)]
FIVE_FASTER = [(60.0, 5.0), (70.0, 5.5), (80.0, 6.0), (90.0, 6.5), (95.0, 7.0)]


class SeededRecordTest(unittest.TestCase):
    def test_격리가_첫_쌍과_둘째_쌍에서_더_빠르지_않으면_한_호스트만으로도_추가_실행_없이_기각한다(self):
        """claude는 두 쌍 모두 느리고 codex는 아직 한 쌍뿐이어도 결정은 reject이고, 한 쌍만 느린 호스트는 둘째 쌍을 기다린다."""
        # given
        slow = [(100.0, 5.0), (100.0, 5.0)]
        slower = [(120.0, 5.0), (110.0, 5.0)]
        one_pair = seeded(both((100.0, 5.0)), both((120.0, 5.0)))
        two_pairs = seeded({"claude": slow, "codex": slow[:1]}, {"claude": slower, "codex": [(80.0, 5.0)]})

        # when
        first, second = decision.decide(one_pair), decision.decide(two_pairs)

        # then
        self.assertEqual(first["decision"], UNDECIDED)
        self.assertEqual(first["claim"]["hosts"]["claude"]["step"], "first pair is not lower")
        self.assertEqual(second["decision"], REJECT)
        self.assertEqual(second["claim"]["hosts"]["claude"]["step"], "two pairs are not lower")

    def test_다섯_번의_중앙값이_가장_빠른_순차_실행보다_낮고_비용이_높지_않으면_두_호스트에서_채택한다(self):
        """두 호스트 다섯 쌍의 중앙값 시간이 가장 낮은 순차 값 아래이고 중앙값 비용이 가장 높은 순차 값 이하이며 D와 T05가 통과하면 adopt이다."""
        # given
        record = seeded(both(*FIVE_SEQUENTIAL), both(*FIVE_FASTER))

        # when
        outcome = decision.decide(record)

        # then
        self.assertEqual(outcome["decision"], ADOPT)
        self.assertEqual(outcome["claim"]["verdict"], "accept")
        self.assertEqual(outcome["quality"], {"T56": "pass", "T05": "pass"})

    def test_격리_실행_다섯_번_중_하나가_필수_검사에서_실패하면_기각하고_선택_검사_실패는_세지_않는다(self):
        """통합 숨은 테스트에서 실패한 격리 실행이 하나라도 있으면 reject이고, 선택 검사만 실패한 기록은 통과로 읽는다."""
        # given
        failing = [(60.0, 5.0, "hidden-tests-integration"), *FIVE_FASTER[1:]]
        failed = seeded(both(*FIVE_SEQUENTIAL), {"claude": failing, "codex": FIVE_FASTER})
        optional_only = seeded(both(*FIVE_SEQUENTIAL), both(*FIVE_FASTER))
        optional_only["runs"][0]["checks"]["readme-lastmod"] = False

        # when
        rejected, adopted = decision.decide(failed), decision.decide(optional_only)

        # then
        self.assertEqual(rejected["decision"], REJECT)
        self.assertEqual(rejected["claim"]["hosts"]["claude"]["step"], "an after run failed a required check")
        self.assertEqual(adopted["decision"], ADOPT)

    def test_중앙값이_가장_빠른_순차_실행보다_낮은_호스트가_하나뿐이면_기각한다(self):
        """claude는 중앙값이 낮고 codex는 가장 낮은 순차 값 이상이면 결정은 reject이다."""
        # given
        not_faster = [(100.0, 5.0), (105.0, 5.5), (110.0, 6.0), (115.0, 6.5), (120.0, 7.0)]
        record = seeded(both(*FIVE_SEQUENTIAL), {"claude": FIVE_FASTER, "codex": not_faster})

        # when
        outcome = decision.decide(record)

        # then
        self.assertEqual(outcome["decision"], REJECT)
        self.assertEqual(outcome["claim"]["hosts"]["claude"]["verdict"], "accept")
        self.assertEqual(outcome["claim"]["hosts"]["codex"]["step"], "median wall_seconds after is not below the lowest before")

    def test_중앙값_비용이_가장_높은_순차_비용보다_높으면_시간이_빨라도_기각한다(self):
        """시간 중앙값은 낮지만 비용 중앙값이 순차의 가장 높은 비용을 넘으면 reject이다."""
        # given
        costly = [(60.0, 9.0), (70.0, 9.5), (80.0, 10.0), (90.0, 10.5), (95.0, 11.0)]
        record = seeded(both(*FIVE_SEQUENTIAL), both(*costly))

        # when
        outcome = decision.decide(record)

        # then
        self.assertEqual(outcome["decision"], REJECT)
        self.assertIn("median cost_usd after is above the highest before", outcome["claim"]["hosts"]["claude"]["step"])

    def test_D나_T05가_실패하면_claim이_받아들여져도_기각하고_T05_실행이_없으면_미정이다(self):
        """D의 동시 실행 검사가 실패하거나 T05의 필수 검사가 실패하면 reject이고, T05 실행이 아예 없으면 undecided이다."""
        # given
        overlapped = seeded(both(*FIVE_SEQUENTIAL), both(*FIVE_FASTER), d_failing="workers-not-at-once")
        broken = seeded(both(*FIVE_SEQUENTIAL), both(*FIVE_FASTER), t05_failing="hidden-low-stock")
        missing = seeded(both(*FIVE_SEQUENTIAL), both(*FIVE_FASTER), with_t05=False)

        # when
        d_result, t05_result, absent = (decision.decide(record) for record in (overlapped, broken, missing))

        # then
        self.assertEqual((d_result["claim"]["verdict"], d_result["decision"]), ("accept", REJECT))
        self.assertEqual(d_result["quality"]["T56"], "fail")
        self.assertEqual((t05_result["claim"]["verdict"], t05_result["decision"]), ("accept", REJECT))
        self.assertEqual(absent["decision"], UNDECIDED)

    def test_작업_공간_배치를_적지_않은_기록은_순차와_격리를_구분할_수_없어_오류이다(self):
        """variants에 workspace가 없으면 어느 쪽이 격리인지 알 수 없으므로 조용히 판정하지 않고 ValueError를 낸다."""
        # given
        record = seeded(both(*FIVE_SEQUENTIAL), both(*FIVE_FASTER))
        record["variants"] = {name: {"revision": entry["revision"]} for name, entry in record["variants"].items()}

        # when / then
        with self.assertRaises(ValueError):
            decision.decide(record)

    def test_호스트_비교는_채택_결정과_별개로_계산되어_호스트_격차가_커지면_통과가_아니다(self):
        """codex 시간이 claude의 0.3배로 벌어진 채택 기록은 decision이 adopt여도 host_comparison은 pass가 아니다."""
        # given
        even = seeded(both(*FIVE_SEQUENTIAL), both(*FIVE_FASTER))
        skewed = seeded(both(*FIVE_SEQUENTIAL), {"claude": FIVE_FASTER, "codex": [(wall * 0.3, cost) for wall, cost in FIVE_FASTER]})

        # when
        outcomes = [decision.decide(record) for record in (even, skewed)]

        # then
        self.assertEqual([item["decision"] for item in outcomes], [ADOPT, ADOPT])
        self.assertEqual(outcomes[0]["host_comparison"], "pass")
        self.assertNotEqual(outcomes[1]["host_comparison"], "pass")


class RecordFormatTest(unittest.TestCase):
    def test_변형의_작업_공간_배치는_두_이름_중_하나만_허용하고_빌더가_기록에_남긴다(self):
        """build_record는 workspaces를 variants에 남기고, 알 수 없는 배치 이름은 검증이 거부하며 layout 필드는 그대로 검증한다."""
        # given
        runs = [run("T55", "a", "claude", 1, 100.0)]
        verdicts = [{"case": "T55", "verdict": "pass", "step": "seeded"}]

        # when
        built = records.build_record(98, ["T55"], {"a": "aaaaaaaaaaaa"}, runs, verdicts, None, {"a": records.WORKSPACES["isolated"]})
        bad = {**built, "variants": {"a": {"revision": "aaaaaaaaaaaa", "workspace": "shared"}}}

        # then
        self.assertEqual(built["variants"]["a"]["workspace"], "one worktree per worker")
        self.assertIn("variant a workspace is not one of sequential, one worktree per worker", records.validate_record(bad))


class WorkspacesOptionTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        seed_campaign(self.root)

    def test_record_명령의_workspaces_옵션은_변경_전후_변형의_배치를_기록에_남긴다(self):
        """`--workspaces sequential,isolated`는 before 변형에 sequential을, after 변형에 one worktree per worker를 쓴다."""
        # given
        arguments = ("--workspaces", "sequential,isolated")

        # when
        code, _, error = run_cli(self.root, *arguments)

        # then
        written = json.loads((self.root / "records" / "92.json").read_text(encoding="utf-8"))
        self.assertEqual((code, error), (0, ""))
        self.assertEqual({name: entry["workspace"] for name, entry in written["variants"].items()},
                         {"base": "sequential", "changed": "one worktree per worker"})

    def test_알_수_없거나_개수가_틀린_workspaces는_기록을_쓰기_전에_거부한다(self):
        """`shared,isolated`나 `isolated`는 오류로 끝나고 기록 파일이 만들어지지 않는다."""
        # given
        bad = ("shared,isolated", "isolated")

        # when
        results = [run_cli(self.root, "--workspaces", value) for value in bad]

        # then
        self.assertTrue(all(code != 0 and "--workspaces takes the workspace layout" in error for code, _, error in results), results)
        self.assertFalse((self.root / "records" / "92.json").exists())


def observed_rules(root: Path) -> dict[str, bool]:
    """Whether "Scheduling" and its mirror hold the rule of item 3."""
    delegation = (root / "instructions/implementation-delegation.md").read_text(encoding="utf-8")
    mirror = (root / "docs/ko/instructions/implementation-delegation.ko.md").read_text(encoding="utf-8")
    scheduling, mirrored = SCHEDULING.search(delegation), MIRROR_SCHEDULING.search(mirror)
    return {"scheduling": bool(scheduling and RULE in " ".join(scheduling.group(1).split())),
            "mirror": bool(mirrored and MIRROR_RULE in " ".join(mirrored.group(1).split()))}


def expected_rules(outcome: str | None) -> dict[str, bool]:
    adopted = outcome == ADOPT
    return {"scheduling": adopted, "mirror": adopted}


class RepositoryStateTest(unittest.TestCase):
    def test_일정_관리_절은_기록이_채택할_때만_규칙을_담는다(self):
        """기록이 없거나 기각이거나 미정이면 "Scheduling"과 미러에 규칙이 없고, 채택이면 둘 다 규칙을 담는다."""
        # given
        outcome = decision.record_decision(records.RECORDS_DIR)

        # when
        state = observed_rules(REPO_ROOT)

        # then
        self.assertEqual(state, expected_rules(outcome))

    def test_채택한_기록은_세_사례의_호스트_비교가_통과한다(self):
        """커밋한 기록이 채택이면 T55, T56, T05에서 #92의 호스트 비교가 통과여야 한다. 기록이 없거나 채택이 아니면 확인할 것이 없다."""
        # given
        path = records.RECORDS_DIR / "98.json"
        result = decision.decide(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else None

        # when
        comparison = result["host_comparison"] if result and result["decision"] == ADOPT else "pass"

        # then
        self.assertEqual(comparison, "pass")

    def test_기대_상태_표는_기록_없음_기각_채택_미정을_구분한다(self):
        """채택만 규칙이 있고 기록 없음, 기각, 미정은 모두 규칙이 없다."""
        # given
        outcomes = (None, REJECT, ADOPT, UNDECIDED)

        # when
        states = [expected_rules(outcome) for outcome in outcomes]

        # then
        self.assertEqual(states, [{"scheduling": False, "mirror": False}] * 2 + [{"scheduling": True, "mirror": True}]
                         + [{"scheduling": False, "mirror": False}])


class CandidateTest(unittest.TestCase):
    def test_후보_패치는_채택_상태를_정확히_만들고_두_파일만_건드린다(self):
        """패치를 적용한 사본은 "Scheduling"과 미러 절에 규칙이 있고, 적용 전에는 없으며, 바뀌는 파일은 두 파일뿐이다."""
        # given
        if not CANDIDATE.is_file():
            self.skipTest("the candidate is applied or dropped")
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory)
            for name in CANDIDATE_FILES:
                target = copy / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(REPO_ROOT / name, target)
            before = observed_rules(copy)

            # when
            applied = subprocess.run(["git", "apply", "-p1", str(CANDIDATE)], cwd=copy, capture_output=True, text=True)
            after = observed_rules(copy)
            touched = re.findall(r"^diff --git a/(\S+) b/", CANDIDATE.read_text(encoding="utf-8"), re.MULTILINE)

        # then
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(before, expected_rules(None))
        self.assertEqual(after, expected_rules(ADOPT))
        self.assertEqual(sorted(touched), sorted(CANDIDATE_FILES))

    def test_후보에_더해진_규칙은_조건과_경로와_통합과_순차_예외를_모두_말한다(self):
        """규칙은 격리 대상(작업 트리 안 파일만 공유), worktree 생성 경로(Orca와 호스트 격리 또는 Git), 통합 확인, 밖의 자원을 공유하면 순차를 담는다."""
        # given
        text = CANDIDATE.read_text(encoding="utf-8") if CANDIDATE.is_file() else ""
        if not text:
            self.skipTest("the candidate is applied or dropped")

        # when
        added = " ".join(" ".join(line[1:] for line in text.splitlines() if line.startswith("+") and not line.startswith("+++")).split())

        # then
        for phrase in ("built and verified on their own", "only files inside the working tree", "one worktree per worker",
                       "Orca route", "plain Git worktree", "integration checks", "database, a port, or another resource outside the working tree",
                       "stay sequential"):
            self.assertIn(phrase, added)


def use(call_id: str, name: str, tool_input: dict[str, Any], parent: str | None = None) -> dict[str, Any]:
    return {"type": "assistant", "parent_tool_use_id": parent,
            "message": {"id": call_id, "content": [{"type": "tool_use", "id": call_id, "name": name, "input": tool_input}]}}


def result(call_id: str) -> dict[str, Any]:
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": call_id, "content": "ok"}]}}


def item(payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": "response_item", "payload": payload}


def shell_call(call_id: str, command: str) -> dict[str, Any]:
    return item({"type": "function_call", "name": "exec_command", "call_id": call_id, "arguments": json.dumps({"cmd": command})})


def shell_output(call_id: str, chunk: dict[str, Any]) -> dict[str, Any]:
    return item({"type": "function_call_output", "call_id": call_id, "output": json.dumps(chunk)})


def worker_concurrency():
    import types

    path = E2E_ROOT / "tasks" / "custom" / "worker_concurrency.py"
    module = types.ModuleType("worker_concurrency")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
    return module


class CallSpanTest(unittest.TestCase):
    def test_Claude_스트림의_호출_구간은_같은_메시지의_병렬_호출만_겹치고_하위_에이전트_호출은_세지_않는다(self):
        """연달아 시작한 두 호출은 구간이 겹치고, 결과를 받은 뒤 시작한 호출은 겹치지 않으며, 하위 에이전트의 호출은 구간이 없다."""
        # given
        from harness import transcript
        events = [use("a", "Agent", {}), use("b", "Agent", {}), result("a"), result("b"), use("c", "Agent", {}), result("c"),
                  use("x", "Bash", {}, parent="a")]
        module = worker_concurrency()

        # when
        spans = transcript.call_spans(events)

        # then
        self.assertTrue(module.overlap(spans["a"], spans["b"]))
        self.assertFalse(module.overlap(spans["b"], spans["c"]))
        self.assertNotIn("x", spans)

    def test_Claude_백그라운드_호출은_반환이_없어_뒤따르는_호출과_겹친다(self):
        """백그라운드 플래그나 명령 끝의 `&`는 반환 위치를 비우고, `2>&1`이나 `&&`와 본문 속 `R&D`는 백그라운드로 읽지 않는다."""
        # given
        from harness import transcript
        events = [use("a", "Agent", {"run_in_background": True}), result("a"), use("b", "Bash", {"command": "run a &"}), result("b"),
                  use("c", "Bash", {"command": "make 2>&1 && echo R&D"}), result("c")]

        # when
        spans = transcript.call_spans(events)

        # then
        self.assertEqual([spans[name]["returned"] is None for name in "abc"], [True, True, False])

    def test_Codex_명령은_세션_종료_출력에서_끝나고_끝나지_않은_세션은_반환이_없다(self):
        """대기 세션을 남긴 명령은 같은 세션의 종료 코드가 나온 위치에서 끝나고, 종료가 없으면 이어지는 호출과 겹친다."""
        # given
        from harness import codex_calls
        events = [shell_call("a", "run one"), shell_output("a", {"session_id": 7, "output": ""}),
                  item({"type": "function_call", "name": "write_stdin", "call_id": "p", "arguments": json.dumps({"session_id": 7})}),
                  shell_output("p", {"session_id": 7, "exit_code": 0, "output": "done"}),
                  shell_call("b", "run two"), shell_output("b", {"session_id": 9, "output": ""}),
                  shell_call("c", "run three"), shell_output("c", {"exit_code": 0, "output": "ok"})]

        # when
        spans = codex_calls.call_spans(events)
        module = worker_concurrency()

        # then
        self.assertEqual((spans["codex:a"]["began"], spans["codex:a"]["returned"]), (0, 3))
        self.assertIsNone(spans["codex:b"]["returned"])
        self.assertFalse(module.overlap(spans["codex:a"], spans["codex:b"]))
        self.assertTrue(module.overlap(spans["codex:b"], spans["codex:c"]))

    def test_구간이_없는_기록은_한_명령의_병렬_시작만_동시_실행으로_읽는다(self):
        """spans가 없는 이전 기록에서도 한 명령이 `&`로 runner 둘을 시작하면 동시 실행이고, 차례로 실행한 두 명령은 아니다."""
        # given
        runner = "python3 /plugin/scripts/role_runner.py worker --assignment /w/a{n}.md"
        together = {"tool_calls": [{"id": "t", "name": "Bash", "source": "main",
                                    "input": {"command": runner.format(n=1) + " &\n" + runner.format(n=2) + " &\nwait"}}]}
        apart = {"tool_calls": [{"id": f"t{n}", "name": "Bash", "source": "main", "input": {"command": runner.format(n=n)}}
                                for n in (1, 2)]}
        module = worker_concurrency()

        # when
        found, quiet = module.concurrent_launches(together), module.concurrent_launches(apart)

        # then
        self.assertEqual(len(found), 1)
        self.assertEqual(quiet, [])


if __name__ == "__main__":
    unittest.main()
