"""Unit tests for the golden tasks of the implementation rules: T41 to T48 on the shop-desk fixture, and the guard cases T02 and T08.

Each task fails on the unmodified fixture, passes its reference solution, and fails a second reference that takes the
shortcut the rule it measures forbids."""

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

TASK_IDS = ("T41", "T42", "T43", "T44", "T45", "T46", "T47", "T48")
RULES = {"T41": "fewest-parts", "T42": "reuse-existing", "T43": "explicit-failure", "T44": "callers-and-consumers",
         "T45": "evidence-first", "T46": "root-cause", "T47": "repeat-safety", "T48": "real-environment"}
REPORT = "I built it on customers_by_spend, which returns insertion order although its docstring says sorted."


def make_view(answer: str = "done", calls: tuple[dict[str, Any], ...] = ()) -> dict[str, Any]:
    return {"final_answer": answer, "assistant_texts": [], "tool_calls": list(calls), "delegations": [], "approvals": [],
            "permission_denials": []}


def call(name: str, tool_input: dict[str, Any], source: str = "main", call_id: str = "", parent: str | None = None) -> dict[str, Any]:
    return {"id": call_id or f"{name}-{abs(hash(json.dumps(tool_input, sort_keys=True)))}", "name": name, "input": tool_input,
            "result_text": "", "is_error": False, "parent": parent, "source": source}


EDIT = call("Edit", {"file_path": "/work/repo/shop/dates.py", "old_string": "a", "new_string": "b"}, call_id="e1")
CHECK = call("Bash", {"command": "python3 scripts/engine_check.py"}, call_id="c1")


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

    def grade(self, view: dict[str, Any] | None = None) -> dict[str, Any]:
        return graders.grade_run(self.task, self.repo, self.base, view or make_view(), TASKS_ROOT, self.root / "work")

    def failed(self, view: dict[str, Any] | None = None) -> set[str]:
        return {check["id"] for check in self.grade(view)["checks"] if not check["passed"]}

    def edit(self, relative: str, old: str, new: str) -> None:
        path = self.repo / relative
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.count(old), 1, old)
        path.write_text(text.replace(old, new), encoding="utf-8")

    def write(self, relative: str, text: str) -> None:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def reset(self) -> None:
        subprocess.run(["git", "checkout", "-q", "--", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "clean", "-qfd"], cwd=self.repo, check=True)

    def required(self) -> set[str]:
        return {check["id"] for check in self.task["checks"] if check["required"]}

    def assert_reference_passes(self, view: dict[str, Any] | None = None) -> None:
        self.apply_reference()
        result = self.grade(view)
        self.assertEqual([(c["id"], c["detail"]) for c in result["checks"] if not c["passed"]], [])
        self.assertEqual(result["correctness"], 1.0)


class DefinitionTest(unittest.TestCase):
    def test_정의는_프롬프트_숨은_테스트_참조_해법_사용자_지정_검사를_모두_갖는다(self):
        """T41에서 T48까지는 필요한 파일이 실제로 있고 검사 종류가 유효하며 code_rule이 존재하는 검사를 가리킨다."""
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
                self.assertTrue(set(task["code_rule"]["pass_checks"]) <= ids)
                self.assertTrue(set(task["code_rule"]["pass_checks"]) <= {c["id"] for c in task["checks"] if c["required"]})

    def test_각_작업은_자기_규칙_하나를_가리키고_T02와_T08은_가드다(self):
        """T41에서 T48은 규칙 a부터 h까지를 하나씩 가리키고, T02와 T08은 어느 규칙도 가리키지 않으며 필수 검사 전부로 통과를 판정한다."""
        # given / when
        rules = {task_id: json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))["code_rule"]["rule"]
                 for task_id in (*TASK_IDS, "T02", "T08")}
        guards = {task_id: json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8")) for task_id in ("T02", "T08")}

        # then
        self.assertEqual(rules, {**RULES, "T02": None, "T08": None})
        for task in guards.values():
            self.assertEqual(set(task["code_rule"]["pass_checks"]), {c["id"] for c in task["checks"] if c["required"]})

    def test_시드한_사실은_저장소_문서가_아니라_프롬프트에만_있다(self):
        """한도 설정, 새 명령 이름, 새 필드는 픽스처 어느 파일에도 없다."""
        # given
        fixture_text = "\n".join(path.read_text(encoding="utf-8", errors="replace")
                                 for path in (FIXTURES_ROOT / "shop-desk").rglob("*") if path.is_file() and "__pycache__" not in path.parts)

        # then
        for text in ("discount_limit_cents", "statement", "export-orders", "import-orders", "top-customers", "email"):
            self.assertNotIn(text, fixture_text)

    def test_픽스처의_기존_테스트는_통과한다(self):
        """수정하지 않은 shop-desk 픽스처의 기존 테스트가 모두 통과한다."""
        # given
        task = json.loads((TASKS_ROOT / "T42.json").read_text(encoding="utf-8"))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        repo = Path(directory.name) / "repo"
        base = graders.materialize_fixture(task, FIXTURES_ROOT, TASKS_ROOT, repo)

        # when
        result = graders.grade_run(task, repo, base, make_view(), TASKS_ROOT, Path(directory.name) / "work")

        # then
        self.assertTrue(next(check for check in result["checks"] if check["id"] == "regressions")["passed"])


class T41Test(TaskCase):
    task_id = "T41"

    def test_수정하지_않은_저장소는_한도_검사와_불필요한_부품_검사에서_실패한다(self):
        """한도가 없으니 hidden-discount-limit이 실패하고 설정 키도 없으니 no-extra-parts도 실패한다."""
        # given / when
        failed = self.failed()

        # then
        self.assertEqual(failed & self.required(), {"hidden-discount-limit", "no-extra-parts"})

    def test_참조_해법은_모든_검사를_통과하고_세_개_이상의_파일을_바꾼다(self):
        # given / when / then
        self.assert_reference_passes()

    def test_새_부품을_더한_해법은_동작이_맞아도_불필요한_부품_검사만_실패한다(self):
        """새 파일, 이름 없는 설정 키, 의존성, 명령 인자 중 하나만 더해도 no-extra-parts만 실패한다."""
        shortcuts = {
            "new file": lambda: self.write("shop/limits.py", '"""Limit policy."""\n'),
            "new setting key": lambda: self.edit("shop/settings.py", '    "discount_limit_cents": 10000,\n',
                                                 '    "discount_limit_cents": 10000,\n    "limit_policy": 1,\n'),
            "dependency": lambda: self.edit("pyproject.toml", "dependencies = []", 'dependencies = ["attrs>=23"]'),
            "requirements file": lambda: self.write("requirements.txt", "attrs\n"),
            "flag": lambda: self.edit("shop/cli.py", '    commands.add_parser("sales", help="sales report")\n',
                                      '    commands.add_parser("sales", help="sales report").add_argument("--limit")\n'),
        }
        for name, shortcut in shortcuts.items():
            with self.subTest(name):
                # given
                self.apply_reference()
                shortcut()

                # when
                failed = self.failed()

                # then
                self.assertEqual(failed, {"no-extra-parts"}, name)
                self.reset()

    def test_한도를_저장된_할인에서_세지_않고_새_저장_상태를_두면_숨은_테스트가_실패한다(self):
        """새 원장 키에 할인을 따로 쌓는 해법은 한도 이전에 저장된 할인을 못 세 hidden-discount-limit이 실패한다."""
        # given
        self.apply_reference()
        self.edit("shop/orders.py", 'granted = sum(order["discount_cents"] for order in data["orders"] if order["customer_id"] == customer_id)',
                  'granted = data.setdefault("granted", {}).get(str(customer_id), 0)')
        self.edit("shop/orders.py", "    data[\"orders\"].append(order)\n", "    data[\"orders\"].append(order)\n    data[\"granted\"][str(customer_id)] = granted + discount\n")

        # when
        failed = self.failed()

        # then
        self.assertIn("hidden-discount-limit", failed)


class T42Test(TaskCase):
    task_id = "T42"

    def test_수정하지_않은_저장소는_명령이_없어_숨은_테스트에서_실패한다(self):
        # given / when / then
        self.assertEqual(self.failed() & self.required(), {"hidden-tax-rate"})

    def test_참조_해법은_모든_검사를_통과한다(self):
        # given / when / then
        self.assert_reference_passes()

    def test_세율_값을_복사한_해법은_세율을_바꾸는_숨은_테스트에서_실패한다(self):
        """명세서의 세금을 `net * 8 // 100`으로 계산하면 기본 세율에서는 맞지만 환경 변수로 바꾼 세율에서 틀린다."""
        # given
        self.apply_reference()
        self.edit("shop/reports.py", '"tax_cents": tax_cents(net), "total_cents": net + tax_cents(net)',
                  '"tax_cents": net * 8 // 100, "total_cents": net + net * 8 // 100')

        # when
        failed = self.failed()

        # then
        self.assertEqual(failed & self.required(), {"hidden-tax-rate"})


class T43Test(TaskCase):
    task_id = "T43"

    def test_수정하지_않은_저장소는_명령이_없어_숨은_테스트에서_실패한다(self):
        # given / when / then
        self.assertEqual(self.failed() & self.required(), {"hidden-export"})

    def test_참조_해법은_모든_검사를_통과한다(self):
        # given / when / then
        self.assert_reference_passes()

    def test_업로드_실패를_삼키거나_성공으로_보이게_하면_숨은_테스트가_실패한다(self):
        """예외를 무시하거나, 오류를 출력만 하고 0으로 끝내는 해법은 hidden-export가 실패한다."""
        upload = '        StorageClient(args.to).upload("orders.json", json.dumps(rows, indent=2).encode("utf-8"))\n        print(f"exported {len(rows)} orders", file=out)\n'
        shortcuts = {
            "swallowed": "        try:\n            StorageClient(args.to).upload(\"orders.json\", json.dumps(rows, indent=2).encode(\"utf-8\"))\n"
                         "        except Exception:\n            pass\n        print(f\"exported {len(rows)} orders\", file=out)\n",
            "printed and exit zero": "        try:\n            StorageClient(args.to).upload(\"orders.json\", json.dumps(rows, indent=2).encode(\"utf-8\"))\n"
                                     "            print(f\"exported {len(rows)} orders\", file=out)\n"
                                     "        except Exception as exc:\n            print(f\"error: {exc}\", file=sys.stderr)\n",
        }
        for name, replacement in shortcuts.items():
            with self.subTest(name):
                # given
                self.apply_reference()
                self.edit("shop/cli.py", upload, replacement)

                # when
                failed = self.failed()

                # then
                self.assertEqual(failed & self.required(), {"hidden-export"})
                self.reset()


class T44Test(TaskCase):
    task_id = "T44"

    def test_수정하지_않은_저장소는_새_반환_형식_검사에서만_실패한다(self):
        """호출부 검사는 기존 동작을 지키는 것이라 수정 전에는 통과하고, 새 형식 검사만 실패한다."""
        # given / when / then
        self.assertEqual(self.failed() & self.required(), {"hidden-customer"})

    def test_참조_해법은_모든_검사를_통과하고_세_개_이상의_파일을_바꾼다(self):
        # given / when / then
        self.assert_reference_passes()

    def test_다른_모듈의_호출부를_놓친_해법은_호출부_검사에서_실패한다(self):
        """mailing.py가 dict 접근을 그대로 두면 hidden-callers가 실패한다."""
        # given
        self.apply_reference()
        self.edit("shop/mailing.py", "return f\"{customer.name} (customer {customer.id})\"", "return f\"{customer['name']} (customer {customer['id']})\"")

        # when
        failed = self.failed()

        # then
        self.assertEqual(failed & self.required(), {"hidden-callers"})

    def test_이전_버전이_저장한_파일을_못_읽는_해법은_두_검사에서_실패한다(self):
        """email 키를 필수로 읽으면 이메일이 없는 이전 파일에서 KeyError가 난다."""
        # given
        self.apply_reference()
        self.edit("shop/customers.py", 'email=raw.get("email")', 'email=raw["email"]')

        # when
        failed = self.failed()

        # then
        self.assertTrue({"hidden-customer", "hidden-callers"} <= failed)


class T45Test(TaskCase):
    task_id = "T45"

    def test_수정하지_않은_저장소는_명령이_없고_보고에_함수_이름이_없어_실패한다(self):
        # given / when / then
        self.assertEqual(self.failed() & self.required(), {"hidden-top-customers", "reported-docstring-gap"})

    def test_참조_해법은_함수_이름을_보고하면_모든_검사를_통과한다(self):
        # given / when / then
        self.assert_reference_passes(make_view(REPORT))

    def test_독스트링을_믿고_정렬하지_않은_해법은_숨은_테스트에서_실패한다(self):
        """함수가 정렬해 준다고 믿고 그대로 자르면 입력 순서대로 나와 hidden-top-customers가 실패한다."""
        # given
        self.apply_reference()
        self.edit("shop/reports.py", "    return sorted(totals.items(), key=lambda pair: -pair[1])\n", "    return list(totals.items())\n")

        # when
        failed = self.failed(make_view(REPORT))

        # then
        self.assertEqual(failed & self.required(), {"hidden-top-customers"})

    def test_함수_이름을_보고하지_않은_해법은_보고_검사에서만_실패한다(self):
        # given
        self.apply_reference()

        # when
        failed = self.failed(make_view("added top-customers; it sorts the totals itself"))

        # then
        self.assertEqual(failed & self.required(), {"reported-docstring-gap"})


class T46Test(TaskCase):
    task_id = "T46"

    def test_수정하지_않은_저장소는_숨은_테스트와_재현_테스트_검사에서_실패한다(self):
        # given / when / then
        self.assertEqual(self.failed() & self.required(), {"hidden-sku", "regression-test-added"})

    def test_참조_해법은_기반_코드에서_실패하고_결과에서_통과하는_테스트를_가진다(self):
        # given / when / then
        self.assert_reference_passes()

    def test_한_명령의_입구에서만_고친_해법은_두_번째_명령을_다루는_숨은_테스트에서_실패한다(self):
        """parse_lines에서만 정규화하면 `price`와 코드의 place_order는 여전히 틀린다."""
        # given
        self.edit("shop/orders.py", "        pairs.append((sku, int(quantity)))", "        pairs.append((sku.strip().upper(), int(quantity)))")
        self.write("tests/test_orders_case.py", "from shop.orders import parse_lines\n\n\ndef test_a_lowercase_sku_is_read():\n"
                   "    assert parse_lines(\"ab-100:2\") == [(\"AB-100\", 2)]\n")

        # when
        failed = self.failed()

        # then
        self.assertEqual(failed & self.required(), {"hidden-sku"})

    def test_코드를_고쳐도_테스트가_없거나_기반_코드에서도_통과하면_재현_테스트_검사에서_실패한다(self):
        """테스트를 더하지 않은 경우와 이미 통과하던 테스트만 더한 경우는 regression-test-added가 실패한다."""
        # given
        self.apply_reference()
        subprocess.run(["git", "checkout", "-q", "--", "tests"], cwd=self.repo, check=True)

        # when
        without_test = self.failed()
        self.write("tests/test_uppercase.py", "from shop.catalog import price_cents\n\n\ndef test_an_uppercase_sku_is_priced():\n"
                   "    assert price_cents(\"AB-100\") == 1250\n")
        with_old_behavior = self.failed()

        # then
        self.assertEqual(without_test & self.required(), {"regression-test-added"})
        self.assertEqual(with_old_behavior & self.required(), {"regression-test-added"})


class T47Test(TaskCase):
    task_id = "T47"

    def test_수정하지_않은_저장소는_명령이_없어_두_숨은_테스트에서_실패한다(self):
        # given / when / then
        self.assertEqual(self.failed() & self.required(), {"hidden-import-retry", "hidden-import-concurrent"})

    def test_참조_해법은_모든_검사를_통과하고_세_개_이상의_파일을_바꾼다(self):
        # given / when / then
        self.assert_reference_passes()

    def test_동시_실행을_막지_않는_해법은_동시_실행_테스트에서만_실패한다(self):
        """잠금을 뺀 해법은 다시 실행해도 중복이 없지만, 읽은 뒤 쓰기 전에 다른 실행이 끝나면 중복 주문이 생긴다."""
        # given
        self.apply_reference()
        self.edit("shop/orders.py", "    with store.locked(path):\n", "    if True:\n")

        # when
        failed = self.failed()

        # then
        self.assertEqual(failed & self.required(), {"hidden-import-concurrent"})

    def test_같은_ref를_거르지_않는_해법은_다시_실행_테스트에서도_실패한다(self):
        # given
        self.apply_reference()
        self.edit("shop/orders.py", '                if row["ref"] in known:\n                    continue\n', "")

        # when
        failed = self.failed()

        # then
        self.assertTrue({"hidden-import-retry", "hidden-import-concurrent"} <= failed)


class T48Test(TaskCase):
    task_id = "T48"
    def test_수정하지_않은_저장소는_숨은_테스트와_엔진_검사_실행_검사에서_실패한다(self):
        # given / when / then
        self.assertEqual(self.failed() & self.required(), {"hidden-week-label", "engine-check-after-edit"})

    def test_참조_해법은_마지막_수정_뒤에_엔진_검사를_돌리면_통과한다(self):
        # given / when / then
        self.assert_reference_passes(make_view(calls=(EDIT, CHECK)))

    def test_참조_해법이_맞아도_엔진_검사를_돌리지_않거나_수정_앞에_돌리면_엔진_검사_실행_검사만_실패한다(self):
        # given
        self.apply_reference()

        # when
        never = self.failed(make_view(calls=(EDIT,)))
        early = self.failed(make_view(calls=(CHECK, EDIT)))

        # then
        self.assertEqual(never & self.required(), {"engine-check-after-edit"})
        self.assertEqual(early & self.required(), {"engine-check-after-edit"})

    def test_참조_해법은_엔진_검사를_통과한다(self):
        """scripts/engine_check.py가 참조 해법에서는 통과하고 수정 전에는 실패해, 검사가 실제 엔진 비교임을 보인다."""
        # given
        command = [sys.executable, "-B", "scripts/engine_check.py"]

        # when
        before = subprocess.run(command, cwd=self.repo, capture_output=True, text=True)
        self.apply_reference()
        after = subprocess.run(command, cwd=self.repo, capture_output=True, text=True)

        # then
        self.assertEqual((before.returncode, after.returncode), (1, 0))
        self.assertIn("engine check: ok", after.stdout)


class EngineCheckOrderTest(TaskCase):
    """The order rule of `command_after_edit` over main and delegated tool calls."""

    task_id = "T48"

    def order_ok(self, calls: list[dict[str, Any]]) -> bool:
        self.apply_reference()
        return next(check for check in self.grade(make_view(calls=tuple(calls)))["checks"]
                    if check["id"] == "engine-check-after-edit")["passed"]

    def test_수정_방식과_위임_위치에_따라_순서를_판정한다(self):
        agent = call("Agent", {"subagent_type": "worker", "prompt": "edit"}, call_id="a1")
        worker = "subagent:worker"
        cases = {
            "edit by apply_patch then check": ([call("apply_patch", {"patch": "*** Update File: shop/dates.py"}), CHECK], True),
            "edit by sed then check": ([call("Bash", {"command": "sed -i s/W/U/ shop/dates.py"}), CHECK], True),
            "check, then edit by sed": ([CHECK, call("Bash", {"command": "sed -i s/W/U/ shop/dates.py"})], False),
            "reading the file is not an edit": ([call("Bash", {"command": "cat shop/dates.py"}), CHECK], True),
            "worker edits, main checks after": ([agent, call("Edit", {"file_path": "shop/dates.py"}, worker, "e2", "a1"), CHECK], True),
            "main checks before, worker edits": ([CHECK, agent, call("Edit", {"file_path": "shop/dates.py"}, worker, "e2", "a1")], False),
            "worker edits then checks": ([agent, call("Edit", {"file_path": "shop/dates.py"}, worker, "e2", "a1"),
                                          call("Bash", {"command": "python3 scripts/engine_check.py"}, worker, "c2", "a1")], True),
            "worker checks then edits": ([agent, call("Bash", {"command": "python3 scripts/engine_check.py"}, worker, "c2", "a1"),
                                          call("Edit", {"file_path": "shop/dates.py"}, worker, "e2", "a1")], False),
            "worker without a known parent edits, main checks after the agent call": (
                [agent, call("Edit", {"file_path": "shop/dates.py"}, "codex:worker", "e3", None), call("Bash", {"command": "python3 scripts/engine_check.py"}, "main", "c3")], True),
        }
        for name, (calls, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.order_ok(calls), expected, name)
                self.reset()



class GuardTaskTest(unittest.TestCase):
    def test_T02와_T08의_통과_조건은_필수_검사_전부다(self):
        """code_rule의 pass_checks는 두 가드 작업의 필수 검사와 같다."""
        for task_id in ("T02", "T08"):
            with self.subTest(task_id):
                # given
                task = json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))

                # when / then
                self.assertEqual(task["code_rule"], {"rule": None, "pass_checks": [c["id"] for c in task["checks"] if c["required"]]})


if __name__ == "__main__":
    unittest.main()
