"""Unit tests for the handoff fields of issue #94: the facts of one run, the adoption rule on seeded records, the record
format, and the candidate text against the instruction files."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
TASKS_ROOT = E2E_ROOT / "tasks"
sys.path.insert(0, str(E2E_ROOT))

from harness import handoff, handoff_candidates, records  # noqa: E402

HOSTS = ("claude", "codex")
EXIT_MARKER = "exit code 3"


def load_task(task_id: str) -> dict:
    return json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))


def item(field: str, name: str = "x", failed=(), delegations: int = 1, present=(), missing=("marker",)) -> dict:
    return {"id": name, "field": field, "failed_checks": list(failed), "delegations": delegations,
            "markers_present": list(present), "markers_missing": list(missing)}


def seeded(case: str, host: str, variant: str, rep: int, passed: bool, *items: dict) -> dict:
    return {"case": case, "host": host, "variant": variant, "rep": rep,
            "handoff": {"passed": passed, "items": list(items) or [item("constraints")]}}


def quiet_runs(variant: str, *, passed: bool = True) -> list[dict]:
    """Two quiet runs of every case on both hosts: no failed mapped check and nothing lost."""
    return [seeded(case, host, variant, rep, passed, item("constraints", failed=(), present=("m",), missing=()),
                   item("behavior", failed=(), present=("m",), missing=()))
            for case in handoff.CASES for host in HOSTS for rep in (1, 2)]


def replace_runs(runs: list[dict], case: str, host: str, variant: str, *items: dict, passed: bool | None = None) -> list[dict]:
    """The runs with the two runs of one cell given these items, and their pass state when `passed` is given."""
    changed = []
    for run in runs:
        if (run["case"], run["host"], run["variant"]) == (case, host, variant):
            run = copy.deepcopy(run)
            run["handoff"]["items"] = list(items)
            if passed is not None:
                run["handoff"]["passed"] = passed
        changed.append(run)
    return changed


def lost(field: str, name: str = "x") -> dict:
    """A seeded item whose mapped check failed and whose marker no delegation prompt holds."""
    return item(field, name, failed=("hidden",), present=(), missing=("marker",))


class RunHandoffTest(unittest.TestCase):
    def facts(self, prompts: list[str], failed: tuple[str, ...], klass: str = "implementation") -> dict:
        task = load_task("T42")
        checks = {check["id"]: check["id"] not in failed for check in task["checks"]}
        delegations = [{"class": klass, "prompt": prompt} for prompt in prompts]
        return handoff.run_handoff(task, delegations, checks)

    def by_id(self, facts: dict) -> dict:
        return {entry["id"]: entry for entry in facts["items"]}

    def test_위임_프롬프트에_표지_문자열이_있으면_그_항목의_표지는_있다로_남는다(self):
        """given 종료 코드와 예전 버전을 적은 프롬프트 when 사실을 만들면 then 그 두 항목은 표지가 있고 나머지는 빠진 것으로 남는다."""
        # given
        prompts = [f"Add memo import. A missing file must end with {EXIT_MARKER}. Keep reading files the previous version wrote."]

        # when
        facts = self.by_id(self.facts(prompts, failed=("hidden-exit-code",)))

        # then
        self.assertEqual(facts["missing-file-exit-code"]["markers_present"], ["code 3"])
        self.assertEqual(facts["old-files-readable"]["markers_present"], ["previous version"])
        self.assertEqual(facts["missing-file-silent"]["markers_present"], [])
        self.assertEqual(facts["missing-file-exit-code"]["failed_checks"], ["hidden-exit-code"])

    def test_구현이_아닌_위임의_프롬프트는_표지로_세지_않는다(self):
        """given 표지는 있지만 검토 위임에만 있는 실행 when 사실을 만들면 then 구현 위임이 없어 위임 수가 0이다."""
        # given
        prompts = [f"review that a missing file ends with {EXIT_MARKER}"]

        # when
        facts = self.by_id(self.facts(prompts, failed=("hidden-exit-code",), klass="review"))

        # then
        self.assertEqual(facts["missing-file-exit-code"]["delegations"], 0)
        self.assertEqual(facts["missing-file-exit-code"]["markers_present"], [])

    def test_통과_여부는_사례의_통과_검사만으로_정해진다(self):
        """given 통과 검사 셋 중 하나만 실패한 실행과 통과 검사에 없는 hidden-format만 실패한 실행 when 사실을 만들면 then 앞의 것만 실패다."""
        # given
        prompts = ["add memo import"]

        # when
        by_exit = self.facts(prompts, failed=("hidden-exit-code",))
        by_format = self.facts(prompts, failed=("hidden-format",))

        # then
        self.assertEqual((by_exit["passed"], by_format["passed"]), (False, True))

    def test_씨앗_항목이_없는_과제는_사실이_없다(self):
        """given 제약에 field가 없는 과제 when 사실을 만들면 then None이다."""
        # given
        task = {"constraints": [{"id": "plain", "keywords": ["a"], "applies_to": ["implementation"], "check_ids": []}]}

        # when
        facts = handoff.run_handoff(task, [{"class": "implementation", "prompt": "a"}], {})

        # then
        self.assertIsNone(facts)

    def test_세_사례의_씨앗_항목은_모두_식별자와_검사와_표지와_필드를_갖는다(self):
        """given T02, T05, T42 과제 파일 when 씨앗 항목을 읽으면 then 각 항목에 알려진 field와 표지와 검사가 있고 검사는 실제 검사다."""
        for case in handoff.CASES:
            with self.subTest(case):
                # given
                task = load_task(case)
                check_ids = {check["id"] for check in task["checks"]}

                # when
                items = [entry for entry in task["constraints"] if entry.get("field")]

                # then
                self.assertTrue(items)
                for entry in items:
                    self.assertIn(entry["field"], handoff.FIELDS)
                    self.assertTrue(entry["keywords"] and entry["check_ids"])
                    self.assertLessEqual(set(entry["check_ids"]), check_ids)
                self.assertLessEqual(set(task["handoff"]["pass_checks"]), check_ids)
        fields = {entry["field"] for case in handoff.CASES for entry in load_task(case)["constraints"] if entry.get("field")}
        self.assertEqual(fields, set(handoff.FIELDS))


class QualificationTest(unittest.TestCase):
    def decide(self, runs: list[dict]) -> dict:
        return handoff.decide(runs, handoff.CASES, "before", "after")

    def before_with(self, case: str, host: str, *items: dict, passed: bool = False) -> list[dict]:
        return replace_runs(quiet_runs("before"), case, host, "before", *items, passed=passed)

    def test_매핑_검사가_실패하고_표지가_두_실행_모두_빠지면_필드가_정해진다(self):
        """given T42 codex의 두 before 실행 모두 behavior 항목의 검사가 실패하고 표지가 없을 때 when 정하면 then behavior만 정해진다."""
        # given
        runs = self.before_with("T42", "codex", lost("behavior"))

        # when
        result = self.decide(runs)

        # then
        self.assertEqual(result["behavior"]["qualified_on"], [{"case": "T42", "host": "codex"}])
        self.assertEqual(result["behavior"]["status"], handoff.AFTER_PENDING)
        self.assertEqual(result["constraints"]["status"], handoff.NO_BENEFIT)

    def test_같은_검사가_실패해도_표지가_있으면_필드는_정해지지_않는다(self):
        """given 매핑 검사는 실패했지만 위임 프롬프트에 표지가 있는 두 실행 when 정하면 then 어느 필드도 정해지지 않는다."""
        # given
        present = item("behavior", failed=("hidden",), present=("code 3",), missing=())
        runs = self.before_with("T42", "codex", present)

        # when
        result = self.decide(runs)

        # then
        self.assertEqual({name: entry["status"] for name, entry in result.items()},
                         {"constraints": handoff.NO_BENEFIT, "behavior": handoff.NO_BENEFIT})

    def test_표지가_빠졌어도_검사가_통과했으면_필드는_정해지지_않는다(self):
        """given 표지는 빠졌지만 매핑 검사가 통과한 두 실행 when 정하면 then 어느 필드도 정해지지 않는다."""
        # given
        silent_pass = item("behavior", failed=(), present=(), missing=("marker",))
        runs = self.before_with("T42", "codex", silent_pass, passed=True)

        # when
        result = self.decide(runs)

        # then
        self.assertEqual(result["behavior"]["status"], handoff.NO_BENEFIT)

    def test_위임이_없는_실행은_어느_필드도_정하지_않는다(self):
        """given 검사는 실패했지만 위임하지 않은 두 실행 when 정하면 then 어느 필드도 정해지지 않는다."""
        # given
        no_delegation = item("behavior", failed=("hidden",), delegations=0, present=(), missing=("marker",))
        runs = self.before_with("T42", "codex", no_delegation)

        # when
        result = self.decide(runs)

        # then
        self.assertEqual(result["behavior"]["status"], handoff.NO_BENEFIT)

    def test_두_실행_중_하나만_조건을_채우면_필드는_정해지지_않는다(self):
        """given 첫 before 실행만 조건을 채우고 둘째는 표지가 있을 때 when 정하면 then 필드는 정해지지 않는다."""
        # given
        runs = self.before_with("T42", "codex", lost("behavior"))
        second = next(run for run in runs if (run["case"], run["host"], run["variant"], run["rep"]) == ("T42", "codex", "before", 2))
        second["handoff"]["items"] = [item("behavior", failed=("hidden",), present=("code 3",), missing=())]

        # when
        result = self.decide(runs)

        # then
        self.assertEqual(result["behavior"]["status"], handoff.NO_BENEFIT)

    def test_사례나_호스트에_두_before_실행이_없으면_기준선은_not_measured다(self):
        """given 한 사례의 codex before 실행이 하나뿐일 때 when 정하면 then 두 필드 모두 not measured이고 이점 없음으로 적지 않는다."""
        # given
        runs = [run for run in quiet_runs("before") if (run["case"], run["host"], run["rep"]) != ("T05", "codex", 2)]

        # when
        result = self.decide(runs)

        # then
        self.assertEqual({entry["status"] for entry in result.values()}, {handoff.NOT_MEASURED})

    def test_한_호스트에서만_두_번_실패해도_다른_호스트와_무관하게_정해진다(self):
        """given T02는 claude에서만 두 번 실패하고 codex에서는 통과한 before 실행 when 정하면 then constraints가 claude에서만 정해진다."""
        # given
        runs = self.before_with("T02", "claude", lost("constraints"))

        # when
        result = self.decide(runs)

        # then
        self.assertEqual(result["constraints"]["qualified_on"], [{"case": "T02", "host": "claude"}])

    def test_앞서_정해진_사례가_after에서_두_번_통과하고_퇴행이_없으면_필드를_유지한다(self):
        """given 정해진 사례가 after 두 실행을 통과하고 나머지 통과 사례도 그대로 통과할 때 when 정하면 then 그 필드는 kept다."""
        # given
        runs = self.before_with("T42", "codex", lost("behavior")) + quiet_runs("after")

        # when
        result = self.decide(runs)

        # then
        self.assertEqual(result["behavior"]["status"], handoff.KEPT)
        self.assertEqual(result["constraints"]["status"], handoff.NO_BENEFIT)

    def test_정해진_사례가_after에서_다시_실패하면_필드를_유지하지_않는다(self):
        """given 정해진 T42 codex가 after 두 실행 중 하나에서 실패할 때 when 정하면 then behavior는 not kept이고 이유에 사례와 호스트가 있다."""
        # given
        after = replace_runs(quiet_runs("after"), "T42", "codex", "after", item("behavior"), passed=False)
        runs = self.before_with("T42", "codex", lost("behavior")) + after

        # when
        result = self.decide(runs)

        # then
        self.assertEqual(result["behavior"]["status"], handoff.NOT_KEPT)
        self.assertEqual(len(result["behavior"]["reasons"]), 1)
        self.assertIn("T42", result["behavior"]["reasons"][0])

    def test_before에서_두_번_통과한_사례가_after에서_실패하면_필드를_유지하지_않는다(self):
        """given 정해진 사례는 고쳐졌지만 before에서 두 번 통과한 T02 claude가 after에서 실패할 때 when 정하면 then 필드는 not kept이다."""
        # given
        after = replace_runs(quiet_runs("after"), "T02", "claude", "after", item("constraints"), passed=False)
        runs = self.before_with("T42", "codex", lost("behavior")) + after

        # when
        result = self.decide(runs)

        # then
        self.assertEqual(result["behavior"]["status"], handoff.NOT_KEPT)
        self.assertIn("T02", result["behavior"]["reasons"][0])

    def test_정해진_필드가_있어도_after_실행이_모자라면_결정을_미룬다(self):
        """given after 실행이 하나도 없을 때 when 정하면 then 정해진 필드는 after 미측정이고 유지 여부를 말하지 않는다."""
        # given
        runs = self.before_with("T42", "codex", lost("behavior"))

        # when
        result = self.decide(runs)

        # then
        self.assertEqual(result["behavior"]["status"], handoff.AFTER_PENDING)

    def test_정해지지_않은_필드는_after_결과와_상관없이_이점_없음으로_남는다(self):
        """given 어느 필드도 정해지지 않았고 after 실행이 실패해도 when 정하면 then 둘 다 이점 없음이다."""
        # given
        runs = quiet_runs("before") + quiet_runs("after", passed=False)

        # when
        result = self.decide(runs)

        # then
        self.assertEqual({entry["status"] for entry in result.values()}, {handoff.NO_BENEFIT})


class RecordFormatTest(unittest.TestCase):
    MODELS = {"main": {"model": "claude-opus-5-5", "effort": "high"}}

    def full_record(self) -> dict:
        runs = []
        for run in quiet_runs("before") + quiet_runs("after"):
            runs.append({"case": run["case"], "variant": run["variant"], "host": run["host"], "rep": run["rep"],
                         "models": self.MODELS, "checks": {"hidden": True}, "wall_seconds": 100.0, "cost_usd": 1.0,
                         "handoff": run["handoff"]})
        verdicts = [{"case": case, "verdict": "pass", "step": "demo"} for case in handoff.CASES]
        return records.build_record(94, list(handoff.CASES), {"before": "0123abc", "after": "4567def"}, runs, verdicts,
                                    handoff.block(runs, "before", "after"))

    def test_기록은_실행별_사실과_정해진_필드를_담고_검증을_통과한다(self):
        """given 세 사례의 before와 after 실행 둘씩을 담은 기록 when 검증하면 then 문제가 없고 handoff 블록이 필드별 상태를 담는다."""
        # given
        record = self.full_record()

        # when
        problems = records.validate_record(record)

        # then
        self.assertEqual(problems, [])
        self.assertEqual(record["handoff"]["fields"]["behavior"]["status"], handoff.NO_BENEFIT)
        self.assertEqual(len(record["runs"]), 24)

    def test_손으로_고친_필드_상태는_실행_사실과_어긋나므로_거부된다(self):
        """given 규칙이 이점 없음으로 정한 필드를 kept로 고친 기록 when 검증하면 then 규칙과 다르다고 거부한다."""
        # given
        record = copy.deepcopy(self.full_record())
        record["handoff"]["fields"]["behavior"]["status"] = handoff.KEPT

        # when
        problems = records.validate_record(record)

        # then
        self.assertTrue(any("differ from the decision" in problem for problem in problems), problems)

    def test_모르는_필드나_빠진_항목이_있는_실행_사실은_거부된다(self):
        """given 항목에서 delegations를 지우고 알 수 없는 field를 쓴 실행 사실 when 검증하면 then 둘 다 거부한다."""
        # given
        record = copy.deepcopy(self.full_record())
        del record["runs"][0]["handoff"]["items"][0]["delegations"]
        record["runs"][1]["handoff"]["items"][0]["field"] = "other"

        # when
        problems = records.validate_record(record)

        # then
        self.assertTrue(any("lacks delegations" in problem for problem in problems), problems)
        self.assertTrue(any("field is not one of" in problem for problem in problems), problems)


class CampaignFactsTest(unittest.TestCase):
    def write(self, path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data) + "\n", encoding="utf-8")

    def test_채점된_실행의_위임_프롬프트와_검사_결과가_기록_항목의_handoff_사실이_된다(self):
        """given T42 실행의 view.json에 표지가 빠진 구현 위임과 실패한 hidden-silent 채점 when campaign_runs를 읽으면 then 항목 사실에 둘이 담긴다."""
        # given
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        folder = root / "camp" / "results" / "T42" / "before" / "rep1"
        self.write(root / "camp" / "campaign.json", {"inputs": {"variant_shas": {"before": "0123456789abcdef"}}})
        self.write(folder / "run.json", {"run_id": "T42-before-r1", "task": "T42", "variant": "before", "rep": 1,
                                         "status": "complete", "host": "claude"})
        self.write(folder / "metrics.json", {"success": False, "wall_seconds": 10.0, "host": "claude",
                                             "cost": {"claude_total_cost_usd": 1.0, "claude_runner_list_cost_usd": 0.0,
                                                      "claude_list_cost_usd": 0.0, "codex_list_cost_usd_estimate": None}})
        self.write(folder / "grade" / "grade.json", {"checks": [
            {"id": "hidden-silent", "required": True, "passed": False, "data": {}},
            {"id": "hidden-exit-code", "required": True, "passed": True, "data": {}}]})
        self.write(folder / "command.json", {"argv": ["claude", "--model", "claude-opus-5-5", "--effort", "high"]})
        (folder / "stream.jsonl").write_text(json.dumps({"type": "system", "subtype": "init", "model": "claude-opus-5-5"}) + "\n")
        self.write(folder / "view.json", {"tool_calls": [], "delegations": [
            {"kind": "agent", "type": "worker", "class": "implementation",
             "prompt": f"Add memo import; a missing file must end with {EXIT_MARKER}"}]})

        # when
        found = records.campaign_runs(root, "camp", ("before",), ["T42"], TASKS_ROOT)

        # then
        items = {entry["id"]: entry for entry in found[0]["entry"]["handoff"]["items"]}
        self.assertEqual(items["missing-file-silent"]["failed_checks"], ["hidden-silent"])
        self.assertEqual(items["missing-file-silent"]["markers_present"], [])
        self.assertEqual(items["missing-file-exit-code"]["markers_present"], ["code 3"])
        self.assertFalse(found[0]["entry"]["handoff"]["passed"])


class CandidateTextTest(unittest.TestCase):
    def text(self, language: str) -> str:
        files = handoff_candidates.load()["files"]
        return (REPO_ROOT / files[language]).read_text(encoding="utf-8")

    def kept_by_record(self) -> list[str]:
        path = records.record_path(94)
        if not path.exists():
            return []
        decisions = json.loads(path.read_text(encoding="utf-8"))["handoff"]["fields"]
        return [name for name, decision in decisions.items() if decision["status"] == handoff.KEPT]

    def test_지침_파일과_한국어_미러는_기록이_남긴_필드만_담는다(self):
        """given 94번 기록이 있으면 그 기록, 없으면 아무 필드도 남기지 않은 상태 when 두 파일을 읽으면 then 정확히 남긴 필드만 담는다."""
        # given
        kept = self.kept_by_record()

        # when
        held = {language: handoff_candidates.held_fields(self.text(language), language) for language in handoff_candidates.LANGUAGES}

        # then
        for language, found in held.items():
            self.assertEqual(found["fields"], kept, language)
            self.assertEqual(found["main_owned"], bool(kept), language)

    def test_기록이_있으면_결정이_끝나_있고_세_사례_실행이_모두_있다(self):
        """given 94번 기록이 있을 때 when 읽으면 then 세 사례의 두 호스트에 전후 실행이 둘씩 있고 어느 필드도 미결이 아니다."""
        # given
        path = records.record_path(94)
        if not path.exists():
            return
        record = json.loads(path.read_text(encoding="utf-8"))

        # when
        cells = {(run["case"], run["host"], run["variant"]) for run in record["runs"] if run.get("handoff")}
        counts = {cell: sum(1 for run in record["runs"] if (run["case"], run["host"], run["variant"]) == cell) for cell in cells}

        # then
        self.assertEqual(records.validate_record(record), [])
        self.assertEqual(len(cells), len(handoff.CASES) * 2 * 2)
        self.assertEqual(set(counts.values()), {2})
        self.assertFalse({d["status"] for d in record["handoff"]["fields"].values()} & {handoff.NOT_MEASURED, handoff.AFTER_PENDING})

    def test_후보_문구는_남긴_필드만_더하고_남기지_않으면_파일을_바꾸지_않는다(self):
        """given 현재 지침 문장 when 필드 없이, 하나로, 둘 모두로 적용하면 then 없으면 그대로이고 있으면 그 줄과 main 담당 문장만 바뀐다."""
        # given
        candidates = handoff_candidates.load()
        for language in handoff_candidates.LANGUAGES:
            with self.subTest(language):
                text = self.text(language)

                # when
                none = handoff_candidates.apply(text, language, [], candidates)
                one = handoff_candidates.apply(text, language, ["behavior"], candidates)
                both = handoff_candidates.apply(text, language, ["constraints", "behavior"], candidates)

                # then
                self.assertEqual(none, text)
                self.assertEqual(handoff_candidates.held_fields(one, language, candidates), {"fields": ["behavior"], "main_owned": True})
                self.assertEqual(handoff_candidates.held_fields(both, language, candidates),
                                 {"fields": ["constraints", "behavior"], "main_owned": True})
                self.assertEqual(handoff_candidates.apply(both, language, ["constraints", "behavior"], candidates), both)

    def test_후보_문구를_적용해도_할당_항목_목록의_다른_줄은_그대로다(self):
        """given 두 필드를 적용한 지침 when 새 줄과 바뀐 문장을 빼면 then 원문과 같다."""
        # given
        candidates = handoff_candidates.load()
        for language in handoff_candidates.LANGUAGES:
            with self.subTest(language):
                text = self.text(language)

                # when
                applied = handoff_candidates.apply(text, language, list(candidates["fields"]), candidates)
                restored = applied.replace(candidates["main_owned"]["new"][language], candidates["main_owned"]["old"][language])
                for entry in candidates["fields"].values():
                    restored = restored.replace(entry[language], "")

                # then
                self.assertEqual(restored, text)


if __name__ == "__main__":
    unittest.main()
