"""Unit tests for the golden tasks of the test rules: T38 (existing assertions beside a new behavior), T39 (a stated behavior
change that one assertion follows), T40 (boundary and failure-path tests), and the guard case T07."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
TASKS_ROOT = E2E_ROOT / "tasks"
FIXTURES_ROOT = E2E_ROOT / "fixtures"
sys.path.insert(0, str(E2E_ROOT))

from harness import graders  # noqa: E402

TASK_IDS = ("T38", "T39", "T40")
FAULT_IDS = ("boundary-rejects-limit", "boundary-allows-one-more", "error-wrong-class", "error-wrong-count")


def make_view() -> dict[str, Any]:
    return {"final_answer": "done", "assistant_texts": [], "tool_calls": [], "delegations": [], "approvals": [],
            "permission_denials": []}


class TaskCase(unittest.TestCase):
    task_id = ""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.task = json.loads((TASKS_ROOT / f"{self.task_id}.json").read_text(encoding="utf-8"))
        self.repo = self.root / "repo"
        self.base = graders.materialize_fixture(self.task, FIXTURES_ROOT, TASKS_ROOT, self.repo)

    def apply_reference(self) -> None:
        script = TASKS_ROOT / "reference" / self.task_id / "apply.py"
        env = {**os.environ, "PYTHONPATH": str(TASKS_ROOT / "reference"), "PYTHONDONTWRITEBYTECODE": "1"}
        subprocess.run([sys.executable, "-B", str(script), str(self.repo)], cwd=self.repo, env=env, check=True,
                       capture_output=True, text=True)

    def grade(self) -> dict[str, Any]:
        return graders.grade_run(self.task, self.repo, self.base, make_view(), TASKS_ROOT, self.root / "work")

    def outcome(self) -> dict[str, bool]:
        return {check["id"]: check["passed"] for check in self.grade()["checks"]}

    def failed(self) -> set[str]:
        return {name for name, passed in self.outcome().items() if not passed}

    def edit(self, relative: str, old: str, new: str) -> None:
        path = self.repo / relative
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.count(old), 1, old)
        path.write_text(text.replace(old, new), encoding="utf-8")

    def required(self) -> set[str]:
        return {check["id"] for check in self.task["checks"] if check["required"]}


class DefinitionTest(unittest.TestCase):
    def test_정의는_프롬프트_숨은_테스트_참조_해법_사용자_지정_검사를_모두_갖는다(self):
        """T38에서 T40까지는 필요한 파일이 실제로 있고 검사 종류가 유효하며 rule_test가 존재하는 검사를 가리킨다."""
        for task_id in TASK_IDS:
            with self.subTest(task_id):
                # given
                task = json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))
                custom = (TASKS_ROOT / "custom" / f"{task_id}.py").read_text(encoding="utf-8")

                # when
                missing = [name for name, found in {
                    "prompt": (TASKS_ROOT / task["prompt_file"]).is_file(),
                    "fixture": (FIXTURES_ROOT / task["fixture"]).is_dir(),
                    "hidden": (TASKS_ROOT / task["hidden_tests"]["source"]).is_dir(),
                    "reference": (TASKS_ROOT / "reference" / task_id / "apply.py").is_file(),
                }.items() if not found]
                unknown = [check["kind"] for check in task["checks"] if check["kind"] not in graders.CHECKS]
                functions = [check["function"] for check in task["checks"] if check["kind"] == "custom"]
                ids = {check["id"] for check in task["checks"]}

                # then
                self.assertEqual((missing, unknown), ([], []))
                self.assertTrue(all(f"def {name}(" in custom for name in functions))
                self.assertTrue(set(task["rule_test"]["pass_checks"]) <= ids)

    def test_사례_A는_변경_단언_항목_C는_경계_항목을_가리키고_B와_T07은_가드다(self):
        """T38은 changed-assertions, T40은 boundary-coverage, T39와 T07은 어느 항목도 자격을 주지 않는다."""
        # given / when
        items = {task_id: json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))["rule_test"]["item"]
                 for task_id in (*TASK_IDS, "T07")}

        # then
        self.assertEqual(items, {"T38": "changed-assertions", "T39": None, "T40": "boundary-coverage", "T07": None})

    def test_T07의_통과_조건은_테스트_무변경_검사다(self):
        """T07 사례의 통과는 tests-untouched이고 수정하지 않은 저장소에서 그 검사가 통과한다."""
        # given
        task = json.loads((TASKS_ROOT / "T07.json").read_text(encoding="utf-8"))
        repo = Path(tempfile.mkdtemp()) / "repo"
        self.addCleanup(lambda: __import__("shutil").rmtree(repo.parent, ignore_errors=True))
        base = graders.materialize_fixture(task, FIXTURES_ROOT, TASKS_ROOT, repo)

        # when
        result = graders.grade_run(task, repo, base, make_view(), TASKS_ROOT, repo.parent / "work")

        # then
        self.assertEqual(task["rule_test"], {"item": None, "pass_checks": ["tests-untouched"]})
        self.assertTrue(next(check for check in result["checks"] if check["id"] == "tests-untouched")["passed"])

    def test_시드한_사실은_저장소_문서가_아니라_프롬프트에만_있다(self):
        """상한 40, half up, 250 g 단위는 픽스처 어느 파일에도 없다."""
        # given
        fixture_text = "\n".join(path.read_text(encoding="utf-8", errors="replace")
                                 for path in (FIXTURES_ROOT / "parcel-desk").rglob("*") if path.is_file())

        # then
        for text in ("250 g step", "half up", "PickupLimitError", "pickup limit"):
            self.assertNotIn(text, fixture_text)


class T38Test(TaskCase):
    task_id = "T38"

    def test_수정하지_않은_저장소는_구역_C_검사에서_실패하고_기존_단언은_그대로다(self):
        """아무것도 하지 않으면 hidden-zone-c가 실패하고, 기존 테스트와 단언 검사와 다른 구역 검사는 통과한다."""
        # given / when
        failed = self.failed()

        # then
        self.assertEqual(failed & self.required(), {"hidden-zone-c"})

    def test_참조_해법은_모든_검사를_통과하고_세_개_이상의_파일을_바꾼다(self):
        """참조 해법은 success이고 정확도 1.0이며 기존 단언이 한 줄도 바뀌지 않는다."""
        # given
        self.apply_reference()

        # when
        result = self.grade()

        # then
        self.assertEqual([(c["id"], c["detail"]) for c in result["checks"] if not c["passed"]], [])
        self.assertEqual(result["correctness"], 1.0)

    def test_기존_단언을_느슨하게_고친_해법은_단언_유지_검사에서만_실패한다(self):
        """구현은 맞아도 `billable_grams(1200) == 1500` 기대값을 바꾸면 existing-assertions-kept만 실패한다."""
        # given
        self.apply_reference()
        self.edit("tests/test_rates.py", "assert billable_grams(1200) == 1500", "assert billable_grams(1200) == 1250")

        # when
        failed = self.failed()

        # then
        self.assertEqual(failed, {"existing-assertions-kept"})

    def test_한_줄로_단계를_바꾼_짧은_구현은_기존_단언을_깨서_회귀와_다른_구역_검사가_실패한다(self):
        """WEIGHT_STEP_GRAMS를 250으로 바꾸면 구역 A와 B의 기존 단언이 깨진다."""
        # given
        self.edit("parcel/rates.py", "WEIGHT_STEP_GRAMS = 500", "WEIGHT_STEP_GRAMS = 250")

        # when
        failed = self.failed()

        # then
        self.assertTrue({"regressions", "hidden-other-zones"} <= failed)

    def test_단언을_지우거나_테스트를_없애거나_건너뛰거나_파일을_지우면_실패한다(self):
        """기존 단언 삭제, 테스트 함수 삭제, skip 표식 추가, 테스트 파일 삭제는 각각 단언 유지 검사를 실패시킨다."""
        cases = {
            "assertion removed": ("tests/test_rates.py", "    assert base_fee_cents(1200, \"B\") == 1350\n", ""),
            "test removed": ("tests/test_rates.py", "def test_unknown_zone_is_rejected():\n    with pytest.raises(UnknownZone):\n"
                             "        base_fee_cents(100, \"Z\")\n", ""),
            "skip added": ("tests/test_rates.py", "def test_weight_outside_the_limits_is_rejected", "@pytest.mark.skip\n"
                           "def test_weight_outside_the_limits_is_rejected"),
        }
        for name, (path, old, new) in cases.items():
            with self.subTest(name):
                # given
                self.apply_reference()
                self.edit(path, old, new)

                # when
                failed = self.failed()

                # then
                self.assertIn("existing-assertions-kept", failed)
                self.reset()

    def reset(self) -> None:
        subprocess.run(["git", "checkout", "-q", "--", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "clean", "-qfd"], cwd=self.repo, check=True)

    def test_새_테스트_파일과_추가한_단언은_단언_유지_검사에서_문제가_아니다(self):
        """새 테스트 파일과 기존 파일에 더한 단언은 목록에 오르지 않아 검사가 통과한다."""
        # given
        self.apply_reference()
        (self.repo / "tests" / "test_zone_c_extra.py").write_text(
            "from parcel.rates import billable_grams\n\n\ndef test_extra():\n    assert billable_grams(1, \"C\") == 250\n",
            encoding="utf-8")
        with (self.repo / "tests" / "test_rates.py").open("a", encoding="utf-8") as handle:
            handle.write("\n\ndef test_added():\n    assert billable_grams(250, \"C\") == 250\n")

        # when
        outcome = self.outcome()

        # then
        self.assertTrue(outcome["existing-assertions-kept"])
        self.assertTrue(outcome["new-tests"])


class T39Test(TaskCase):
    task_id = "T39"

    def test_수정하지_않은_저장소는_half_up_검사와_낡은_단언_검사에서_실패한다(self):
        """아무것도 하지 않으면 hidden-half-up과 old-assertion-updated가 실패하고 나머지 필수 검사는 통과한다."""
        # given / when
        failed = self.failed()

        # then
        self.assertEqual(failed & self.required(), {"hidden-half-up", "old-assertion-updated"})

    def test_참조_해법은_모든_검사를_통과한다(self):
        """구현을 바꾸고 낡은 단언 하나만 11로 고친 참조 해법은 success이고 정확도 1.0이다."""
        # given
        self.apply_reference()

        # when
        result = self.grade()

        # then
        self.assertEqual([(c["id"], c["detail"]) for c in result["checks"] if not c["passed"]], [])
        self.assertTrue(result["success"])

    def test_낡은_기대값을_그대로_둔_해법은_테스트_통과와_낡은_단언_검사에서_실패한다(self):
        """구현만 half up으로 바꾸고 `== 10`을 두면 agent-tests-pass와 old-assertion-updated가 실패한다."""
        # given
        self.apply_reference()
        self.edit("tests/test_rounding.py", "def test_a_large_fraction_rounds_up():\n    assert round_cents(Decimal(\"10.7\")) == 11",
                  "def test_a_large_fraction_is_dropped_too():\n    assert round_cents(Decimal(\"10.7\")) == 10")

        # when
        failed = self.failed()

        # then
        self.assertEqual(failed, {"agent-tests-pass", "old-assertion-updated"})

    def test_다른_기존_단언을_함께_고치면_다른_단언_유지_검사가_실패한다(self):
        """바꿀 단언 말고 `round_cents(Decimal('10.2')) == 10`도 고치면 other-assertions-kept가 실패한다."""
        # given
        self.apply_reference()
        self.edit("tests/test_rounding.py", "assert round_cents(Decimal(\"10.2\")) == 10", "assert round_cents(Decimal(\"10.2\")) == 10 or True")

        # when
        failed = self.failed()

        # then
        self.assertEqual(failed, {"other-assertions-kept"})

    def test_낡은_테스트를_건너뛰거나_지우면_실패한다(self):
        """낡은 단언을 skip으로 넘기거나 단언만 지우면 구현이 맞아도 필수 검사가 실패한다."""
        edits = {
            "skipped": ("def test_a_large_fraction_rounds_up():", "@pytest.mark.skip\ndef test_a_large_fraction_rounds_up():"),
            "assertion removed": ("    assert round_cents(Decimal(\"10.7\")) == 11\n", "    pass\n"),
        }
        for name, (old, new) in edits.items():
            with self.subTest(name):
                # given
                self.apply_reference()
                self.edit("tests/test_rounding.py", old, new)

                # when
                failed = self.failed()

                # then
                self.assertTrue(failed & {"other-assertions-kept", "old-assertion-updated"}, name)
                subprocess.run(["git", "checkout", "-q", "--", "."], cwd=self.repo, check=True)


class T40Test(TaskCase):
    task_id = "T40"

    def test_수정하지_않은_저장소는_상한_검사와_자체_테스트_검사에서_실패한다(self):
        """상한이 없으면 hidden-limit이 실패하고, 참조에 통과하는 테스트가 없어 own-tests-kill-faults도 실패한다."""
        # given / when
        failed = self.failed()

        # then
        self.assertEqual(failed & self.required(), {"hidden-limit", "own-tests-kill-faults"})

    def test_참조_해법은_숨은_테스트와_자체_테스트_검사를_모두_통과한다(self):
        """경계와 오류 경로를 모두 다룬 테스트는 참조에서 통과하고 네 결함 사본을 모두 잡는다."""
        # given
        self.apply_reference()

        # when
        result = self.grade()

        # then
        own = next(check for check in result["checks"] if check["id"] == "own-tests-kill-faults")
        self.assertEqual([(c["id"], c["detail"]) for c in result["checks"] if not c["passed"]], [])
        self.assertEqual(own["data"]["survived"], [])
        self.assertEqual(set(own["data"]["outcome"]), {"reference", *FAULT_IDS})

    def test_기존_테스트만으로는_어느_결함_사본도_잡히지_않는다(self):
        """결함이 기존 테스트에 걸리면 새 테스트의 공이 아니므로, 기존 테스트는 결함 사본 넷 모두에서 통과해야 한다."""
        # given
        self.apply_reference()
        (self.repo / "tests" / "test_pickup.py").write_text(
            subprocess.run(["git", "show", f"{self.base}:tests/test_pickup.py"], cwd=self.repo, check=True,
                           capture_output=True, text=True).stdout, encoding="utf-8")

        # when
        result = self.grade()

        # then
        own = next(check for check in result["checks"] if check["id"] == "own-tests-kill-faults")
        self.assertEqual(own["data"]["outcome"]["reference"], "passed")
        self.assertEqual(sorted(own["data"]["survived"]), sorted(FAULT_IDS))

    def write_pickup_tests(self, limit_ok: bool, one_over: bool, error_class: str, exact_count: bool) -> None:
        """The pre-existing pickup tests plus a limit test block with the named parts left weak."""
        original = subprocess.run(["git", "show", f"{self.base}:tests/test_pickup.py"], cwd=self.repo, check=True,
                                  capture_output=True, text=True).stdout
        header = original.replace("from parcel.errors import UnknownZone, ValidationError",
                                  "from parcel.errors import PickupLimitError, UnknownZone, ValidationError")
        message = "pickup limit is 40 parcels, got 41" if exact_count else "pickup limit is 40 parcels"
        lines = ["", ""]
        if limit_ok:
            lines += ["def test_the_limit_itself_is_allowed():", "    assert pickup_fee_cents(40, \"A\") == 4800", "", ""]
        lines += ["def test_above_the_limit_raises():", f"    with pytest.raises({error_class}, match=\"{message}\"):"]
        lines += ["        pickup_fee_cents(41, \"A\")" if one_over else "        pickup_fee_cents(500, \"A\")"]
        (self.repo / "tests" / "test_pickup.py").write_text(header + "\n".join(lines) + "\n", encoding="utf-8")

    def test_테스트가_결함_사본_하나를_놓치면_그_결함을_짚어_실패한다(self):
        """경계 두 개와 오류 경로 두 개 각각에 대해 그것을 확인하는 부분만 빼면 그 사본만 살아남는다."""
        weakened = {
            "boundary-rejects-limit": {"limit_ok": False, "one_over": True, "error_class": "PickupLimitError", "exact_count": True},
            "boundary-allows-one-more": {"limit_ok": True, "one_over": False, "error_class": "PickupLimitError", "exact_count": False},
            "error-wrong-class": {"limit_ok": True, "one_over": True, "error_class": "Exception", "exact_count": True},
            "error-wrong-count": {"limit_ok": True, "one_over": True, "error_class": "PickupLimitError", "exact_count": False},
        }
        for fault, options in weakened.items():
            with self.subTest(fault):
                # given
                self.write_pickup_tests(**options)

                # when
                own = next(check for check in self.grade()["checks"] if check["id"] == "own-tests-kill-faults")

                # then
                self.assertFalse(own["passed"])
                self.assertEqual(own["data"]["outcome"]["reference"], "passed")
                self.assertIn(fault, own["data"]["survived"])

    def test_모든_부분을_갖춘_테스트는_결함_사본을_모두_잡는다(self):
        """같은 도우미로 만든 완전한 테스트는 네 결함 사본을 모두 잡아 도우미의 약화 단위가 맞음을 보인다."""
        # given
        self.write_pickup_tests(limit_ok=True, one_over=True, error_class="PickupLimitError", exact_count=True)

        # when
        own = next(check for check in self.grade()["checks"] if check["id"] == "own-tests-kill-faults")

        # then
        self.assertEqual(own["data"]["survived"], [], own["data"])

    def test_결함_정의는_참조_구현에_정확히_한_번_적용된다(self):
        """모든 결함 치환은 참조 구현에서 정확히 한 곳과 맞고, 결함 사본은 참조와 다르다."""
        # given
        faults = json.loads((TASKS_ROOT / "faults" / "T40" / "faults.json").read_text(encoding="utf-8"))
        reference = (TASKS_ROOT / "faults" / "T40" / "reference" / "parcel" / "pickup.py").read_text(encoding="utf-8")

        # when / then
        self.assertEqual([fault["id"] for fault in faults], list(FAULT_IDS))
        for fault in faults:
            self.assertEqual(reference.count(fault["old"]), 1, fault["id"])
            self.assertNotEqual(reference.replace(fault["old"], fault["new"]), reference)


if __name__ == "__main__":
    unittest.main()
