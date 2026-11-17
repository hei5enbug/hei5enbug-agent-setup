"""Unit tests for the testing rules of issue #95: the cases' pass conditions, the adoption rule on seeded records, the record
format, and the candidate text and script against the repository."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
TASKS_ROOT = E2E_ROOT / "tasks"
sys.path.insert(0, str(E2E_ROOT))

from harness import handoff, records, testing_candidates, testing_rules  # noqa: E402

HOSTS = ("claude", "codex")
CASES = testing_rules.CASES


def load_task(task_id: str) -> dict:
    return json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))


def run(case: str, host: str, variant: str, rep: int, ok: bool, failing: str | None = None) -> dict:
    """One run whose pass checks all hold, or all but `failing` (the first pass check of the case when `ok` is false)."""
    names = testing_rules.PASS_CHECKS[case]
    broken = failing or (names[0] if not ok else None)
    return {"case": case, "host": host, "variant": variant, "rep": rep, "checks": {name: name != broken for name in names}}


def runs_of(variant: str, results: dict[tuple[str, str], tuple[bool, bool]] | None = None) -> list[dict]:
    """Two runs of every case on both hosts; `results` maps (case, host) to the pass state of rep 1 and rep 2 (default: pass)."""
    results = results or {}
    return [run(case, host, variant, rep, results.get((case, host), (True, True))[rep - 1])
            for case in CASES for host in HOSTS for rep in (1, 2)]


def decide(before: dict | None = None, after: dict | None = None, *, with_after: bool = True) -> dict:
    runs = runs_of("before", before) + (runs_of("after", after) if with_after else [])
    return testing_rules.decide(runs, "before", "after")


class PassConditionTest(unittest.TestCase):
    def test_사례의_통과_검사는_과제_파일의_필수_검사_식별자와_일치한다(self):
        """given 네 사례의 통과 검사 이름 when 과제 파일과 견주면 then 모두 그 과제의 필수 검사로 있다."""
        # given
        names = testing_rules.PASS_CHECKS

        # when
        missing = {case: [name for name in checks if not any(item["id"] == name and item["required"] for item in load_task(case)["checks"])]
                   for case, checks in names.items()}

        # then
        self.assertEqual(missing, {case: [] for case in names})

    def test_통과_검사_하나라도_실패하거나_빠지면_그_사례_실행은_통과가_아니다(self):
        """given 통과 검사가 모두 참인 T44 실행과 검사 하나만 거짓이거나 빠진 실행 when 통과를 보면 then 앞의 것만 통과다."""
        # given
        good = run("T44", "claude", "before", 1, True)
        broken = run("T44", "claude", "before", 1, True, failing="assertion-updated")
        missing = {**good, "checks": {name: True for name in ("hidden-tests", "agent-tests")}}

        # when
        outcomes = [testing_rules.passed(item) for item in (good, broken, missing)]

        # then
        self.assertEqual(outcomes, [True, False, False])


class DecisionTest(unittest.TestCase):
    FAIL_A_CLAUDE = {("T43", "claude"): (False, False)}
    FAIL_C_CODEX = {("T45", "codex"): (False, False)}

    def test_사례_A가_한_호스트에서_두_번_실패하면_제약_항목만_정해진다(self):
        """given T43이 claude에서 두 번 실패하고 T45는 모두 통과한 before 실행 when 결정하면 then restraint만 그 호스트로 정해진다."""
        # given / when
        result = decide(self.FAIL_A_CLAUDE, with_after=False)

        # then
        self.assertEqual(result["restraint"]["qualified_on"], [{"case": "T43", "host": "claude"}])
        self.assertEqual(result["restraint"]["status"], testing_rules.AFTER_PENDING)
        self.assertEqual(result["boundaries"]["status"], testing_rules.NO_BENEFIT)

    def test_사례_C가_두_번_실패하면_경계_항목만_정해진다(self):
        """given T45가 codex에서 두 번 실패한 before 실행 when 결정하면 then boundaries만 정해지고 restraint는 이점 없음이다."""
        # given / when
        result = decide(self.FAIL_C_CODEX, with_after=False)

        # then
        self.assertEqual(result["boundaries"]["qualified_on"], [{"case": "T45", "host": "codex"}])
        self.assertEqual(result["restraint"]["status"], testing_rules.NO_BENEFIT)

    def test_두_번_중_한_번만_실패하거나_다른_사례가_실패하면_항목은_정해지지_않는다(self):
        """given T43이 한 번만 실패하고 T44가 두 번 실패한 before 실행 when 결정하면 then 두 항목 모두 이점 없음이다."""
        # given
        before = {("T43", "claude"): (False, True), ("T44", "claude"): (False, False)}

        # when
        result = decide(before, with_after=False)

        # then
        self.assertEqual({name: item["status"] for name, item in result.items()},
                         {"restraint": testing_rules.NO_BENEFIT, "boundaries": testing_rules.NO_BENEFIT})

    def test_사례나_호스트에_두_before_실행이_없으면_기준선은_측정되지_않은_것이다(self):
        """given T07의 codex before 실행이 하나뿐인 기록 when 결정하면 then 두 항목 모두 not measured다."""
        # given
        runs = [item for item in runs_of("before") if not (item["case"] == "T07" and item["host"] == "codex" and item["rep"] == 2)]

        # when
        result = testing_rules.decide(runs, "before", "after")

        # then
        self.assertEqual({item["status"] for item in result.values()}, {testing_rules.NOT_MEASURED})

    def test_정해진_사례가_after에서_두_번_통과하고_퇴행이_없으면_항목을_남긴다(self):
        """given T43이 before에서 두 번 실패하고 after에서 모두 통과한 기록 when 결정하면 then restraint는 kept다."""
        # given / when
        result = decide(self.FAIL_A_CLAUDE)

        # then
        self.assertEqual(result["restraint"], {"status": testing_rules.KEPT, "qualified_on": [{"case": "T43", "host": "claude"}], "reasons": []})

    def test_정해진_사례가_after에서_다시_실패하면_항목을_남기지_않는다(self):
        """given T43이 after의 한 실행에서 다시 실패한 기록 when 결정하면 then restraint는 not kept이고 이유가 사례와 호스트를 밝힌다."""
        # given / when
        result = decide(self.FAIL_A_CLAUDE, {("T43", "claude"): (True, False)})

        # then
        self.assertEqual(result["restraint"]["status"], testing_rules.NOT_KEPT)
        self.assertEqual(result["restraint"]["reasons"], ["T43 failed a before run on claude and an after run failed"])

    def test_before에서_두_번_통과한_사례가_after에서_실패하면_다른_사례여도_항목을_남기지_않는다(self):
        """given T43은 해결됐지만 두 번 통과하던 T07이 codex after에서 실패한 기록 when 결정하면 then restraint는 not kept이다."""
        # given / when
        result = decide(self.FAIL_A_CLAUDE, {("T07", "codex"): (True, False)})

        # then
        self.assertEqual(result["restraint"]["status"], testing_rules.NOT_KEPT)
        self.assertEqual(result["restraint"]["reasons"], ["T07 passed both before runs on codex and an after run failed"])

    def test_before에서_한_번만_통과하던_다른_사례의_after_실패는_퇴행으로_세지_않는다(self):
        """given T44가 before에서 한 번만 통과하다 after에서 실패한 기록 when 결정하면 then T43의 결정은 그 때문에 바뀌지 않는다."""
        # given
        before = {**self.FAIL_A_CLAUDE, ("T44", "claude"): (True, False)}

        # when
        result = decide(before, {("T44", "claude"): (False, False)})

        # then
        self.assertEqual(result["restraint"]["status"], testing_rules.KEPT)

    def test_정해진_항목이_있어도_after_실행이_모자라면_결정을_미룬다(self):
        """given after 실행이 T07 codex에 하나뿐인 기록 when 결정하면 then 정해진 항목은 after 미측정이다."""
        # given
        runs = runs_of("before", self.FAIL_A_CLAUDE) + [item for item in runs_of("after") if not (item["case"] == "T07" and item["rep"] == 2)]

        # when
        result = testing_rules.decide(runs, "before", "after")

        # then
        self.assertEqual(result["restraint"]["status"], testing_rules.AFTER_PENDING)

    def test_두_항목이_함께_정해지면_같은_after_실행으로_각각_정해진다(self):
        """given T43과 T45가 모두 두 번 실패하고 after에서 T45만 다시 실패한 기록 when 결정하면 then restraint는 kept, boundaries는 not kept다."""
        # given
        before = {**self.FAIL_A_CLAUDE, **self.FAIL_C_CODEX}

        # when
        result = decide(before, {("T45", "codex"): (False, True)})

        # then
        self.assertEqual((result["restraint"]["status"], result["boundaries"]["status"]), (testing_rules.KEPT, testing_rules.NOT_KEPT))


class RecordFormatTest(unittest.TestCase):
    MODELS = {"main": {"model": "claude-opus-5-5", "effort": "high"}}

    def full_record(self, before=None, after=None, cases=CASES) -> dict:
        entries = []
        for item in runs_of("before", before) + runs_of("after", after):
            if item["case"] in cases:
                entries.append({**item, "models": self.MODELS, "wall_seconds": 100.0, "cost_usd": 1.0})
        verdicts = [{"case": case, "verdict": "pass", "step": "demo"} for case in cases]
        return records.build_record(95, list(cases), {"before": "0123abc", "after": "4567def"}, entries, verdicts,
                                    testing_block=testing_rules.block(entries, "before", "after"))

    def test_기록은_항목별_결정을_담고_검증을_통과한다(self):
        """given 네 사례의 전후 실행 둘씩을 담은 기록 when 검증하면 then 문제가 없고 testing 블록이 항목별 상태를 담는다."""
        # given
        record = self.full_record({("T43", "claude"): (False, False)})

        # when
        problems = records.validate_record(record)

        # then
        self.assertEqual(problems, [])
        self.assertEqual(record["testing"]["items"]["restraint"]["status"], testing_rules.KEPT)
        self.assertEqual(len(record["runs"]), 32)

    def test_손으로_고친_항목_상태는_실행과_어긋나므로_거부된다(self):
        """given 규칙이 이점 없음으로 정한 항목을 kept로 고친 기록 when 검증하면 then 규칙과 다르다고 거부한다."""
        # given
        record = copy.deepcopy(self.full_record())
        record["testing"]["items"]["boundaries"]["status"] = testing_rules.KEPT

        # when
        problems = records.validate_record(record)

        # then
        self.assertTrue(any("differ from the decision" in problem for problem in problems), problems)

    def test_모르는_항목이나_빠진_블록_필드는_거부된다(self):
        """given 항목 이름을 바꾸고 after를 지운 testing 블록 when 검증하면 then 둘 다 거부한다."""
        # given
        record = copy.deepcopy(self.full_record())
        record["testing"]["items"]["other"] = record["testing"]["items"].pop("boundaries")
        problems_items = records.validate_record(record)
        del record["testing"]["after"]

        # when
        problems_block = records.validate_record(record)

        # then
        self.assertTrue(any("items must hold exactly" in problem for problem in problems_items), problems_items)
        self.assertTrue(any("testing must hold exactly" in problem for problem in problems_block), problems_block)

    def test_다른_이슈가_재는_T07_실행만_있는_기록에는_testing_블록이_붙지_않는다(self):
        """given T07 실행만 담은 기록 when 만들면 then testing 블록이 없고 검증을 통과한다."""
        # given / when
        record = self.full_record(cases=("T07",))

        # then
        self.assertNotIn("testing", record)
        self.assertEqual(records.validate_record(record), [])


class CandidateTextTest(unittest.TestCase):
    def candidates(self) -> dict:
        return testing_candidates.load()

    def text(self, file_key: str, language: str) -> str:
        return (REPO_ROOT / self.candidates()["files"][file_key][language]).read_text(encoding="utf-8")

    def held(self, file_key: str, language: str) -> list[str]:
        return testing_candidates.held_items(self.text(file_key, language), language, file_key)

    def kept_by_record(self) -> list[str]:
        path = records.record_path(95)
        if not path.exists():
            return []
        items = json.loads(path.read_text(encoding="utf-8"))["testing"]["items"]
        return [name for name, decision in items.items() if decision["status"] == handoff.KEPT]

    def test_지침_파일과_한국어_미러는_기록이_남긴_항목만_담는다(self):
        """given 95번 기록이 있으면 그 기록, 없으면 아무 항목도 남기지 않은 상태 when 두 지침과 미러를 읽으면 then 정확히 남긴 항목만 담는다."""
        # given
        kept = self.kept_by_record()

        # when / then
        for file_key, expected in (("testing", kept), ("execution", [name for name in kept if name == "restraint"])):
            for language in testing_candidates.LANGUAGES:
                with self.subTest(file=file_key, language=language):
                    self.assertEqual(self.held(file_key, language), expected)

    def test_스크립트는_제약_항목을_남길_때만_scripts_폴더에_있다(self):
        """given 기록이 남긴 항목 when 후보와 설치 위치를 보면 then 스크립트는 restraint가 남았을 때만 scripts에 있고 후보 폴더에는 그때 없다."""
        # given
        kept = self.kept_by_record()
        candidate, installed = testing_candidates.script_paths()

        # when
        places = (candidate.is_file(), installed.is_file())

        # then
        self.assertEqual(places, (False, True) if "restraint" in kept else (True, False))

    def test_기록이_있으면_결정이_끝나_있고_네_사례_실행이_모두_있다(self):
        """given 95번 기록이 있을 때 when 읽으면 then 네 사례의 두 호스트에 전후 실행이 둘씩 있고 어느 항목도 미결이 아니다."""
        # given
        path = records.record_path(95)
        if not path.exists():
            return
        record = json.loads(path.read_text(encoding="utf-8"))

        # when
        counts: dict[tuple, int] = {}
        for item in record["runs"]:
            key = (item["case"], item["host"], item["variant"])
            counts[key] = counts.get(key, 0) + 1

        # then
        self.assertEqual(records.validate_record(record), [])
        self.assertEqual(len(counts), len(CASES) * 2 * 2)
        self.assertEqual(set(counts.values()), {2})
        self.assertFalse({item["status"] for item in record["testing"]["items"].values()}
                         & {testing_rules.NOT_MEASURED, testing_rules.AFTER_PENDING})

    def test_후보_문구는_남긴_항목만_더하고_남기지_않으면_파일을_바꾸지_않는다(self):
        """given 현재 지침 when 항목 없이, 하나로, 둘 모두로 적용하면 then 없으면 그대로이고 있으면 그 항목의 줄만 더해진다."""
        # given
        candidates = self.candidates()
        for file_key in candidates["files"]:
            for language in testing_candidates.LANGUAGES:
                with self.subTest(file=file_key, language=language):
                    text = self.text(file_key, language)

                    # when
                    none = testing_candidates.apply(text, language, file_key, [], candidates)
                    one = testing_candidates.apply(text, language, file_key, ["boundaries"], candidates)
                    both = testing_candidates.apply(text, language, file_key, list(candidates["items"]), candidates)

                    # then
                    self.assertEqual(none, text)
                    self.assertEqual(testing_candidates.held_items(one, language, file_key, candidates),
                                     ["boundaries"] if file_key == "testing" else [])
                    self.assertEqual(testing_candidates.held_items(both, language, file_key, candidates),
                                     list(candidates["items"]) if file_key == "testing" else ["restraint"])
                    self.assertEqual(testing_candidates.apply(both, language, file_key, list(candidates["items"]), candidates), both)

    def test_항목을_나눠_적용해도_한꺼번에_적용한_것과_같고_더한_줄을_빼면_원문이다(self):
        """given 지침 when 두 항목을 두 순서로 나눠 적용하고 한꺼번에도 적용하면 then 결과가 같고 새 줄을 빼면 원문과 같다."""
        # given
        candidates = self.candidates()
        for language in testing_candidates.LANGUAGES:
            with self.subTest(language):
                text = self.text("testing", language)

                # when
                at_once = testing_candidates.apply(text, language, "testing", ["restraint", "boundaries"], candidates)
                first_late = testing_candidates.apply(
                    testing_candidates.apply(text, language, "testing", ["boundaries"], candidates), language, "testing", ["restraint"], candidates)
                restored = at_once
                for name, edit in testing_candidates.edits_of(candidates, "testing"):
                    restored = restored.replace(edit["text"][language], "")

                # then
                self.assertEqual(first_late, at_once)
                self.assertEqual(restored, text)

    def test_후보_스크립트는_조정자_지침의_경로_형식으로_지침_문구가_가리킨다(self):
        """given 제약 항목의 수용 문구 when 스크립트 이름을 찾으면 then 영어와 한국어 문구 모두 같은 설치 경로를 가리킨다."""
        # given
        edit = next(edit for edit in self.candidates()["items"]["restraint"]["edits"] if edit["file"] == "execution")

        # when
        mentions = {language: "<Source directory>/scripts/changed_assertions.py" in edit["text"][language] for language in edit["text"]}

        # then
        self.assertEqual(mentions, {"en": True, "ko": True})


if __name__ == "__main__":
    unittest.main()
