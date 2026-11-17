"""Unit tests for the implementation rules of issue #93: the eight tasks' pass conditions, the adoption rule on seeded records, the
record format, and the rules file and entry lines against the repository."""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
TASKS_ROOT = E2E_ROOT / "tasks"
sys.path.insert(0, str(E2E_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import session_context  # noqa: E402
from harness import handoff, implementation_candidates, implementation_rules, records  # noqa: E402

HOSTS = ("claude", "codex")
RULES = implementation_rules.RULES
CASES = implementation_rules.CASES
TASK_OF = implementation_rules.TASK_OF
MODELS = {"main": {"model": "claude-opus-5-5", "effort": "high"}}


def load_task(task_id: str) -> dict:
    return json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))


def run(case: str, host: str, variant: str, rep: int, ok: bool, failing: str | None = None) -> dict:
    """One run whose pass checks all hold, or all but `failing` (the first pass check of the task when `ok` is false)."""
    names = implementation_rules.PASS_CHECKS[case]
    broken = failing or (names[0] if not ok else None)
    return {"case": case, "host": host, "variant": variant, "rep": rep, "checks": {name: name != broken for name in names}}


def runs_of(variant: str, results: dict[tuple[str, str], tuple[bool, ...]] | None = None, *, doubled: tuple[str, ...] = CASES) -> list[dict]:
    """The runs of one variant: two per task in `doubled` and one for every other task, on both hosts. `results` maps (rule, host) to
    the pass state of each run (default: pass)."""
    results = results or {}
    found = []
    for rule, case in TASK_OF.items():
        for host in HOSTS:
            states = results.get((rule, host), (True, True))
            for rep in range(1, (2 if case in doubled else 1) + 1):
                found.append(run(case, host, variant, rep, states[min(rep, len(states)) - 1]))
    return found


def decide(before: dict | None = None, after: dict | None = None, reworded: dict | None = None, *, after_doubled: tuple[str, ...] | None = None,
           reworded_doubled: tuple[str, ...] = ()) -> dict:
    """The decisions for seeded runs. The after variant holds two runs of the tasks that failed twice before on some host and one of the
    others, as the measurement plan runs them, unless `after_doubled` names the doubled tasks."""
    before_runs = runs_of("before", before)
    failing_twice = tuple(TASK_OF[rule] for rule in RULES if any(not any(state for state in (before or {}).get((rule, host), (True, True)))
                                                                 for host in HOSTS))
    runs = before_runs + runs_of("after", after, doubled=failing_twice if after_doubled is None else after_doubled)
    if reworded is not None:
        runs += runs_of("reworded", reworded, doubled=reworded_doubled)
    return implementation_rules.decide(runs, "before", "after", "reworded" if reworded is not None else None)


def statuses(result: dict) -> dict[str, str]:
    return {rule: item["status"] for rule, item in result.items()}


class PassConditionTest(unittest.TestCase):
    def test_여덟_규칙은_과제_T34부터_T41과_하나씩_짝이고_통과_검사는_그_과제의_필수_검사다(self):
        """given 규칙과 과제의 짝과 통과 검사 이름 when 과제 파일과 견주면 then 짝은 T34부터 T41이고 모든 통과 검사가 필수 검사로 있다."""
        # given
        pairs = implementation_rules.TASK_OF

        # when
        missing = {case: [name for name in implementation_rules.PASS_CHECKS[case]
                          if not any(item["id"] == name and item["required"] for item in load_task(case)["checks"])] for case in CASES}
        fixtures = {load_task(case)["fixture"] for case in CASES}

        # then
        self.assertEqual(list(pairs.values()), [f"T{number}" for number in range(34, 42)])
        self.assertEqual(missing, {case: [] for case in CASES})
        self.assertEqual(fixtures, {"orders-svc"})

    def test_통과_검사_하나라도_실패하거나_빠지면_그_과제_실행은_통과가_아니다(self):
        """given 통과 검사가 모두 참인 T34 실행과 검사 하나만 거짓이거나 빠진 실행 when 통과를 보면 then 앞의 것만 통과다."""
        # given
        good = run("T34", "claude", "before", 1, True)
        broken = run("T34", "claude", "before", 1, True, failing="no-extra-files")
        missing = {**good, "checks": {name: value for name, value in good["checks"].items() if name != "no-extra-files"}}

        # when
        outcome = [implementation_rules.passed(item) for item in (good, broken, missing)]

        # then
        self.assertEqual(outcome, [True, False, False])


class DecisionTest(unittest.TestCase):
    FAIL_A_CLAUDE = {("a", "claude"): (False, False)}

    def test_한_호스트에서_두_번_실패한_뒤_after에서_두_번_통과하면_그_규칙만_남긴다(self):
        """given a의 과제가 claude에서 두 번 실패하고 after에서 두 번 통과한 기록 when 결정하면 then a만 kept이고 나머지는 이점 없음이다."""
        # given
        before = self.FAIL_A_CLAUDE

        # when
        result = decide(before)

        # then
        self.assertEqual(result["a"], {"task": "T34", "status": handoff.KEPT, "qualified_on": [{"case": "T34", "host": "claude"}], "reasons": []})
        self.assertEqual({status for rule, status in statuses(result).items() if rule != "a"}, {handoff.NO_BENEFIT})
        self.assertEqual(implementation_rules.kept_rules(result), ["a"])

    def test_두_호스트_모두에서_두_번_통과하던_규칙은_after_없이도_아무것도_더하지_않는다(self):
        """given 모든 과제가 before 두 번 통과한 기록과 after 실행이 없는 기록 when 결정하면 then 모든 규칙이 이점 없음이고 남기는 것이 없다."""
        # given
        runs = runs_of("before")

        # when
        result = implementation_rules.decide(runs, "before", "after")

        # then
        self.assertEqual(set(statuses(result).values()), {handoff.NO_BENEFIT})
        self.assertEqual(implementation_rules.kept_rules(result), [])

    def test_두_번_실패했지만_한_번은_통과한_규칙은_해당_호스트로_정해지지_않는다(self):
        """given a가 claude에서 실패 뒤 통과, codex에서 통과 뒤 실패한 before 기록 when 결정하면 then 두 호스트 모두 정해지지 않는다."""
        # given
        before = {("a", "claude"): (False, True), ("a", "codex"): (True, False)}

        # when
        result = decide(before)

        # then
        self.assertEqual(result["a"]["status"], handoff.NO_BENEFIT)
        self.assertEqual(result["a"]["qualified_on"], [])

    def test_규칙이_정해진_뒤_그_과제가_after에서_다시_실패하면_한_번_고쳐_쓰기로_남는다(self):
        """given a가 두 번 실패하고 after에서 한 번 더 실패한 기록 when 결정하면 then a는 고쳐 쓸 규칙이고 이유가 호스트를 밝힌다."""
        # given
        after = {("a", "claude"): (True, False)}

        # when
        result = decide(self.FAIL_A_CLAUDE, after)

        # then
        self.assertEqual(result["a"]["status"], implementation_rules.REWORD)
        self.assertEqual(result["a"]["reasons"], ["T34 failed an after run on claude"])

    def test_고쳐_쓴_뒤에도_그_과제가_실패하면_규칙을_뺀다(self):
        """given a가 두 번 실패하고 after에서 실패하고 고쳐 쓴 변형에서도 실패한 기록 when 결정하면 then a는 not kept이다."""
        # given
        after, reworded = {("a", "claude"): (True, False)}, {("a", "claude"): (False, True)}

        # when
        result = decide(self.FAIL_A_CLAUDE, after, reworded, reworded_doubled=("T34",))

        # then
        self.assertEqual(result["a"]["status"], handoff.NOT_KEPT)
        self.assertEqual(result["a"]["reasons"], ["T34 failed an after run on claude after the rewording"])
        self.assertEqual(implementation_rules.kept_rules(result), [])

    def test_고쳐_쓴_뒤_그_과제가_두_번_통과하면_규칙을_남긴다(self):
        """given a가 두 번 실패하고 after에서 실패하고 고쳐 쓴 변형에서 두 번 통과한 기록 when 결정하면 then a는 kept이다."""
        # given
        after = {("a", "claude"): (True, False)}

        # when
        result = decide(self.FAIL_A_CLAUDE, after, {}, reworded_doubled=("T34",))

        # then
        self.assertEqual(result["a"]["status"], handoff.KEPT)

    def test_고쳐_쓴_변형의_실행이_모자라면_고쳐_쓴_실행_미측정으로_미룬다(self):
        """given 고쳐 쓴 변형에서 a의 과제가 한 번만 돈 기록 when 결정하면 then a는 고쳐 쓴 실행 미측정이다."""
        # given
        after = {("a", "claude"): (True, False)}

        # when
        result = decide(self.FAIL_A_CLAUDE, after, {}, reworded_doubled=())

        # then
        self.assertEqual(result["a"]["status"], implementation_rules.REWORD_PENDING)

    def test_고쳐_쓰는_중에도_다른_규칙은_첫_after_결과로_정해진다(self):
        """given a와 b가 두 번 실패하고 after에서 a만 다시 실패한 기록 when 결정하면 then a는 고쳐 쓸 규칙이고 b는 kept이다."""
        # given
        before = {("a", "claude"): (False, False), ("b", "codex"): (False, False)}

        # when
        result = decide(before, {("a", "claude"): (True, False)})

        # then
        self.assertEqual((result["a"]["status"], result["b"]["status"]), (implementation_rules.REWORD, handoff.KEPT))

    def test_변경_전에_두_번_통과하던_다른_과제가_after에서_실패하면_정해진_규칙을_모두_뺀다(self):
        """given a와 b가 정해지고 두 번 통과하던 T41이 codex after에서 실패한 기록 when 결정하면 then a와 b가 모두 not kept이고 이유가 T41을 밝힌다."""
        # given
        before = {("a", "claude"): (False, False), ("b", "claude"): (False, False)}

        # when
        result = decide(before, {("h", "codex"): (False,)})

        # then
        self.assertEqual((result["a"]["status"], result["b"]["status"]), (handoff.NOT_KEPT, handoff.NOT_KEPT))
        self.assertIn("T41 passed both before runs on codex and a run of after failed", result["a"]["reasons"])
        self.assertEqual(result["c"]["status"], handoff.NO_BENEFIT)

    def test_after에서_정해진_과제는_두_번_나머지는_한_번_돌아야_하고_모자라면_결정을_미룬다(self):
        """given a의 과제가 after에서 한 번만 돌았거나 다른 과제가 빠진 기록 when 결정하면 then 정해진 규칙은 after 미측정이다."""
        # given
        before = self.FAIL_A_CLAUDE
        once = decide(before, after_doubled=())
        full = runs_of("before", before) + runs_of("after", doubled=("T34",))
        lacking = implementation_rules.decide([item for item in full if not (item["case"] == "T41" and item["variant"] == "after" and item["host"] == "codex")],
                                              "before", "after")

        # when
        found = (once["a"]["status"], lacking["a"]["status"], lacking["b"]["status"])

        # then
        self.assertEqual(found, (handoff.AFTER_PENDING, handoff.AFTER_PENDING, handoff.NO_BENEFIT))

    def test_변경_전_실행이_한_과제라도_모자라면_모든_규칙이_측정되지_않은_것이다(self):
        """given T41의 codex before 실행이 하나뿐인 기록 when 결정하면 then 모든 규칙이 측정되지 않은 것이다."""
        # given
        runs = [item for item in runs_of("before") if not (item["case"] == "T41" and item["host"] == "codex" and item["rep"] == 2)]

        # when
        result = implementation_rules.decide(runs, "before", "after")

        # then
        self.assertEqual(set(statuses(result).values()), {handoff.NOT_MEASURED})


class RecordFormatTest(unittest.TestCase):
    def full_record(self, before=None, after=None, cases=CASES) -> dict:
        failing = tuple(TASK_OF[rule] for rule in RULES if any(not any(state for state in (before or {}).get((rule, host), (True, True)))
                                                               for host in HOSTS))
        entries = [{**item, "models": MODELS, "wall_seconds": 100.0, "cost_usd": 1.0}
                   for item in runs_of("before", before) + runs_of("after", after, doubled=failing) if item["case"] in cases]
        verdicts = [{"case": case, "verdict": "pass", "step": "demo"} for case in cases]
        return records.build_record(93, list(cases), {"before": "0123abc", "after": "4567def"}, entries, verdicts,
                                    implementation_block=implementation_rules.block(entries, "before", "after"))

    def test_기록은_규칙별_결정과_정해진_규칙_목록을_담고_검증을_통과한다(self):
        """given 여덟 과제의 전후 실행을 담은 기록 when 검증하면 then 문제가 없고 implementation 블록이 정해진 규칙과 상태를 담는다."""
        # given
        record = self.full_record({("c", "codex"): (False, False)})

        # when
        problems = records.validate_record(record)

        # then
        self.assertEqual(problems, [])
        self.assertEqual(record["implementation"]["qualifying"], ["c"])
        self.assertEqual(record["implementation"]["rules"]["c"]["status"], handoff.KEPT)
        self.assertEqual(len(record["runs"]), 8 * 2 * 2 + 1 * 2 * 2 + 7 * 2)

    def test_손으로_고친_규칙_상태는_실행과_어긋나므로_거부된다(self):
        """given 이점 없음으로 정해진 규칙을 kept로 고친 기록 when 검증하면 then 규칙과 다르다고 거부한다."""
        # given
        record = copy.deepcopy(self.full_record())
        record["implementation"]["rules"]["e"]["status"] = handoff.KEPT

        # when
        problems = records.validate_record(record)

        # then
        self.assertTrue(any("differ from the decision" in problem for problem in problems), problems)

    def test_모르는_규칙이나_빠진_블록_필드는_거부된다(self):
        """given 규칙 이름을 바꾸고 reworded를 지운 implementation 블록 when 검증하면 then 둘 다 거부한다."""
        # given
        record = copy.deepcopy(self.full_record())
        record["implementation"]["rules"]["z"] = record["implementation"]["rules"].pop("h")
        problems_rules = records.validate_record(record)
        del record["implementation"]["reworded"]

        # when
        problems_block = records.validate_record(record)

        # then
        self.assertTrue(any("rules must hold exactly" in problem for problem in problems_rules), problems_rules)
        self.assertTrue(any("implementation must hold exactly" in problem for problem in problems_block), problems_block)

    def test_여덟_과제_밖의_실행만_있는_기록에는_implementation_블록이_붙지_않는다(self):
        """given T02 실행만 담은 기록 when 블록을 만들면 then 블록이 없다."""
        # given
        entries = [{"case": "T02", "variant": "before", "host": "claude", "rep": 1, "checks": {}}]

        # when
        found = implementation_rules.block(entries, "before", "after")

        # then
        self.assertIsNone(found)


class CandidateTextTest(unittest.TestCase):
    COPIED = ("instructions/implementation-execution.md", "docs/ko/instructions/implementation-execution.ko.md",
              "instructions/implementation-delegation.md", "docs/ko/instructions/implementation-delegation.ko.md")

    def kept_by_record(self) -> list[str] | None:
        path = records.record_path(93)
        if not path.exists():
            return None
        return implementation_rules.kept_rules(json.loads(path.read_text(encoding="utf-8"))["implementation"]["rules"])

    def temp_repo(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for relative in self.COPIED:
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / relative, root / relative)
        return root

    def test_규칙_파일과_두_진입_줄은_기록이_남긴_규칙만_담고_남긴_것이_없으면_모두_없다(self):
        """given 93번 기록이 있으면 그 기록, 없으면 아무 규칙도 남기지 않은 상태 when 저장소를 읽으면 then 정확히 남긴 규칙만 있고 없으면 파일과 두 진입 줄이 없다."""
        # given
        kept = self.kept_by_record()

        # when
        state = implementation_candidates.repository_state()

        # then
        if not kept:
            self.assertEqual(state["rules"], {"en": None, "ko": None})
            self.assertEqual(set(state["entries"].values()), {False})
        else:
            self.assertEqual(state["rules"], {"en": kept, "ko": kept})
            self.assertEqual(set(state["entries"].values()), {True})

    def test_규칙_파일은_고른_규칙만_조건별_절로_나눠_담고_하나도_없으면_파일이_없다(self):
        """given 규칙을 하나, 조건 있는 규칙과 없는 규칙, 전부, 없음으로 고르면 when 그리면 then 고른 규칙만 담고 없음이면 None이다."""
        # given
        selections = [["a"], ["h"], ["b", "g"], list(RULES), []]

        for language in implementation_candidates.LANGUAGES:
            for chosen in selections:
                with self.subTest(language=language, chosen=chosen):
                    # when
                    text = implementation_candidates.render(language, chosen)

                    # then
                    if not chosen:
                        self.assertIsNone(text)
                        continue
                    self.assertEqual(implementation_candidates.held_rules(text, language), chosen)
                    self.assertEqual("## Under a stated condition" in text or "## 명시한 조건에서" in text,
                                     any(rule in implementation_rules.CONDITIONAL_RULES for rule in chosen))

    def test_규칙은_후보_파일과_짝이_맞고_조건_있는_규칙만_조건_절에_있다(self):
        """given 후보 파일의 규칙 여덟 개 when 과제 짝과 조건을 견주면 then 과제 짝이 같고 조건 절은 f, g, h뿐이며 영어와 한국어 줄이 모두 있다."""
        # given
        rules = implementation_candidates.load()["rules"]

        # when
        sections = {name: rule["section"] for name, rule in rules.items()}
        pairs = {name: rule["task"] for name, rule in rules.items()}

        # then
        self.assertEqual(list(rules), list(RULES))
        self.assertEqual(pairs, TASK_OF)
        self.assertEqual({name for name, section in sections.items() if section == "condition"}, set(implementation_rules.CONDITIONAL_RULES))
        self.assertTrue(all(rule["text"]["en"] and rule["text"]["ko"] for rule in rules.values()))

    def test_규칙을_적용하면_정확히_그_규칙과_진입_줄이_생기고_빈_목록을_적용하면_원문으로_돌아온다(self):
        """given 두 지침과 미러의 사본 when 규칙 a를 적용하고 c로 바꾸고 비우면 then 각 단계에서 정확히 그 규칙만 있고 마지막은 처음 바이트와 같다."""
        # given
        root = self.temp_repo()
        original = {relative: (root / relative).read_bytes() for relative in self.COPIED}

        # when
        implementation_candidates.apply(["a"], root)
        first = implementation_candidates.repository_state(root)
        implementation_candidates.apply(["c"], root)
        second = implementation_candidates.repository_state(root)
        implementation_candidates.apply([], root)
        third = implementation_candidates.repository_state(root)

        # then
        self.assertEqual((first["rules"], second["rules"]), ({"en": ["a"], "ko": ["a"]}, {"en": ["c"], "ko": ["c"]}))
        self.assertEqual(set(first["entries"].values()) | set(second["entries"].values()), {True})
        self.assertEqual(third, {"rules": {"en": None, "ko": None}, "entries": {key: False for key in third["entries"]}})
        self.assertEqual({relative: (root / relative).read_bytes() for relative in self.COPIED}, original)

    def test_진입_줄을_더해도_할당받은_worker_맥락은_4000바이트_안이고_더한_줄만큼만_는다(self):
        """given 규칙을 적용한 지침 사본 when 구현 worker 맥락을 그리면 then 4000바이트 안이고 늘어난 바이트는 진입 줄의 바이트다."""
        # given
        root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, root, True)
        shutil.copytree(REPO_ROOT / "instructions", root / "instructions")
        before = len(session_context.render_context(root, "claude", "implementation").encode("utf-8"))
        for relative in ("docs/ko/instructions/implementation-execution.ko.md", "docs/ko/instructions/implementation-delegation.ko.md"):
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / relative, root / relative)

        # when
        candidates = implementation_candidates.load()
        implementation_candidates.apply(list(RULES), root)
        after = len(session_context.render_context(root, "claude", "implementation").encode("utf-8"))

        # then
        entry = candidates["entries"]["delegation"]["text"]["en"].replace("(implementation-rules.md)", "($I/implementation-rules.md)")
        self.assertLess(after, session_context.MAX_ROLE_CONTEXT_BYTES)
        self.assertEqual(after - before, len(entry.encode("utf-8")))

    def test_변경_스캔_줄은_더하고_빼면_원문이_된다(self):
        """given 실행 지침의 수용 절 when 스캔 줄을 더했다 빼면 then 줄이 한 번 들어가고 뺀 결과는 원문과 같다."""
        # given
        candidates = implementation_candidates.load()
        for language in implementation_candidates.LANGUAGES:
            with self.subTest(language):
                text = (REPO_ROOT / candidates["files"]["execution"][language]).read_text(encoding="utf-8")

                # when
                added = implementation_candidates.apply_entry(text, language, candidates["scan"], True)
                removed = implementation_candidates.apply_entry(added, language, candidates["scan"], False)

                # then
                self.assertEqual(added.count(candidates["scan"]["text"][language]), 1)
                self.assertIn("scripts/change_scan.py", added)
                self.assertEqual(removed, text)

    def test_기록이_있으면_결정이_끝나_있고_여덟_과제_실행이_모두_있다(self):
        """given 93번 기록이 있을 때 when 읽으면 then 검증을 통과하고 어느 규칙도 미측정이나 after 미측정이 아니다."""
        # given
        path = records.record_path(93)
        if not path.exists():
            return
        record = json.loads(path.read_text(encoding="utf-8"))

        # when
        found = {item["status"] for item in record["implementation"]["rules"].values()}

        # then
        self.assertEqual(records.validate_record(record), [])
        self.assertFalse(found & {handoff.NOT_MEASURED, handoff.AFTER_PENDING, implementation_rules.REWORD_PENDING})


if __name__ == "__main__":
    unittest.main()
