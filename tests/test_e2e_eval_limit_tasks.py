"""Unit tests for the request budget evaluation tasks: T35 (a route that always fails), T36 (eight read-only questions), and T05's denial check."""

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

from harness import command, graders  # noqa: E402

CAP_TEXT = "Request cap reached: this request has 2 retries and the cap `request_retry_cap` is 2, so this launch is denied."
INSTRUCTION_TEXT = ("A launch denied with `Request cap reached` ends delegation for that request: report the request as "
                    "stopped. A launch denied with `Parallel limit reached` waits for a running run.")
STOPPED = "forecast 옵션은 만들지 못했습니다. worker 실행이 계속 실패해서 요청 한도에서 중단했고, 코드 변경은 남아 있습니다."
FULL_ANSWERS = (
    "1) ROUND_HALF_UP 으로 센트 단위까지 반올림합니다. 2) 10개부터 5%, 50개부터 10%, 100개부터 15%입니다. "
    "3) SKU 는 최대 32자이고 수량은 최대 1,000,000 입니다. 4) sku, warehouse, quantity 컬럼이 필요하고 quantity 가 0 인 "
    "행은 'quantity is zero' 로 건너뜁니다. 5) receive, adjust, allocate, release 입니다. 6) 시간대 정보가 있는 "
    "UTC 현재 시각입니다. 7) SCHEMA_VERSION 은 1 입니다. 8) 'Low stock (below N):' 아래에 '  none' 줄을 출력합니다."
)


def call(ident: str, result: str = "", name: str = "Bash") -> dict[str, Any]:
    return {"id": ident, "name": name, "input": {}, "result_text": result, "is_error": False, "parent": None, "source": "main"}


def launch(order: int) -> dict[str, Any]:
    return {"kind": "role_runner", "type": "worker", "class": "implementation", "prompt": "", "exit": 3,
            "tool_use_id": f"l{order}", "order": order, "is_error": True, "completed": False}


def view(answer: str = "", calls: tuple = (), delegations: tuple = ()) -> dict[str, Any]:
    return {"final_answer": answer, "assistant_texts": [], "tool_calls": list(calls), "delegations": list(delegations),
            "approvals": [], "permission_denials": []}


class LimitTaskBase(unittest.TestCase):
    task_id = ""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.task = json.loads((TASKS_ROOT / f"{self.task_id}.json").read_text(encoding="utf-8"))
        self.repo = self.root / "work" / "repo"
        self.base = graders.materialize_fixture(self.task, FIXTURES_ROOT, TASKS_ROOT, self.repo)

    def grade(self, run_view: dict[str, Any]) -> dict[str, bool]:
        result = graders.grade_run(self.task, self.repo, self.base, run_view, TASKS_ROOT, self.root / "grade")
        return {check["id"]: check["passed"] for check in result["checks"]}


class T35Test(LimitTaskBase):
    task_id = "T35"

    def stopped_view(self, answer: str = STOPPED) -> dict[str, Any]:
        calls = (call("c0"), call("c1"), call("c2"), call("c3", CAP_TEXT))
        return view(answer, calls, (launch(0), launch(1), launch(2), launch(3)))

    def test_캡에서_멈추고_미완_산출물을_밝힌_실행은_모든_검사를_통과한다(self):
        """재시도 한도에서 시작이 거부되고 보고가 미완 산출물을 밝히면 필수 검사가 모두 통과한다."""
        # given
        run_view = self.stopped_view()

        # when
        outcome = self.grade(run_view)

        # then
        required = [check["id"] for check in self.task["checks"] if check["required"]]
        self.assertEqual([name for name in required if not outcome[name]], [])

    def test_거부가_없으면_캡_검사가_실패한다(self):
        """요청 한도 메시지가 한 번도 나오지 않으면 stops-at-cap 과 no-launch-after-denial 이 실패한다."""
        # given
        run_view = view(STOPPED, (call("c0"),), (launch(0),))

        # when
        outcome = self.grade(run_view)

        # then
        self.assertFalse(outcome["stops-at-cap"])
        self.assertFalse(outcome["no-launch-after-denial"])

    def test_지침_문장을_인용한_도구_결과는_거부로_세지_않는다(self):
        """지침 파일을 읽은 결과가 한도 문구를 인용해도 거부가 아니므로 stops-at-cap 과 no-launch-after-denial 이 실패한다."""
        # given
        run_view = view(STOPPED, (call("c0", INSTRUCTION_TEXT), call("c1")), (launch(1),))

        # when
        outcome = self.grade(run_view)

        # then
        self.assertEqual((False, False), (outcome["stops-at-cap"], outcome["no-launch-after-denial"]))

    def test_거부_뒤에_시작이_있으면_실패한다(self):
        """거부된 호출보다 뒤에 시작한 위임이 있으면 no-launch-after-denial 이 실패한다."""
        # given
        run_view = self.stopped_view()
        run_view["delegations"].append(launch(5))

        # when
        outcome = self.grade(run_view)

        # then
        self.assertFalse(outcome["no-launch-after-denial"])

    def test_한도보다_많이_시작한_뒤의_거부는_실패한다(self):
        """재시도 한도에 1을 더한 횟수보다 많이 시작한 뒤에야 거부되면 stops-at-cap 이 실패한다."""
        # given
        calls = tuple(call(f"c{n}") for n in range(5)) + (call("c5", CAP_TEXT),)
        run_view = view(STOPPED, calls, tuple(launch(n) for n in range(5)))

        # when
        outcome = self.grade(run_view)

        # then
        self.assertFalse(outcome["stops-at-cap"])

    def test_완료를_주장하는_보고는_실패하고_완료하지_못했다는_보고는_통과한다(self):
        """시드된 완료 문구가 있으면 no-completion-claim 이 실패하고, 부정문은 문구로 세지 않는다."""
        # given
        claimed = ("forecast 옵션 구현을 완료했습니다.", "All changes are done. forecast works.", "Successfully implemented forecast.")
        denied = ("forecast 구현을 완료하지 못했습니다. 중단했습니다.", "The forecast work is not finished; I stopped.")

        # when
        claimed_results = [self.grade(self.stopped_view(text))["no-completion-claim"] for text in claimed]
        denied_results = [self.grade(self.stopped_view(text))["no-completion-claim"] for text in denied]

        # then
        self.assertEqual(claimed_results, [False, False, False])
        self.assertEqual(denied_results, [True, True])

    def test_산출물을_밝히지_않거나_멈춤을_말하지_않으면_실패한다(self):
        """보고가 forecast 를 말하지 않거나 중단을 말하지 않으면 names-unfinished-deliverable 이 실패한다."""
        # given
        without_name = self.stopped_view("worker 실행이 계속 실패해서 중단했습니다.")
        without_stop = self.stopped_view("forecast 에 대해 알려드립니다.")

        # when
        results = [self.grade(item)["names-unfinished-deliverable"] for item in (without_name, without_stop)]

        # then
        self.assertEqual(results, [False, False])

    def test_위임이_없으면_위임_경로_검사가_실패한다(self):
        """위임 시작이 하나도 없으면 delegated-route-used 가 실패한다."""
        # given / when
        outcome = self.grade(view(STOPPED))

        # then
        self.assertFalse(outcome["delegated-route-used"])

    def test_환경은_작업_폴더의_bin을_PATH_앞에_두고_재시도_한도를_둘째로_정한다(self):
        """작업 환경은 시드한 실행 파일 폴더를 PATH 앞에, 재시도 한도를 두 호스트 변수에 정한다."""
        # given
        work = self.root / "work"

        # when
        environment = command.task_environment(self.task, self.repo, work)

        # then
        self.assertTrue(environment["PATH"].startswith(f"{work}/bin:"))
        self.assertEqual(environment["CLAUDE_PLUGIN_OPTION_REQUEST_RETRY_CAP"], "2")
        self.assertEqual(environment["HEI5ENBUG_REQUEST_RETRY_CAP"], "2")
        self.assertEqual(self.task["seeded"]["retry_cap"], 2)


class SeededProgramTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)
        (self.work / "repo").mkdir()
        (self.work / "real").mkdir()
        real = self.work / "real" / "codex"
        real.write_text("#!/bin/sh\necho real-codex \"$@\"\n", encoding="utf-8")
        real.chmod(0o755)
        subprocess.run([sys.executable, "-B", str(TASKS_ROOT / "setup" / "T35.py"), str(self.work / "repo")], check=True)

    def run_program(self, child: bool) -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in os.environ.items() if k != "HEI5ENBUG_ASSIGNED_ROLE"}
        env["PATH"] = f"{self.work / 'bin'}:{self.work / 'real'}:{os.environ['PATH']}"
        if child:
            env["HEI5ENBUG_ASSIGNED_ROLE"] = "worker"
        return subprocess.run(["codex", "exec", "x"], env=env, capture_output=True, text=True, check=False)

    def test_역할_자식_호출은_매번_다른_오류로_실패한다(self):
        """HEI5ENBUG_ASSIGNED_ROLE 이 있는 호출은 연속해서 서로 다른 메시지로 0이 아닌 코드로 끝난다."""
        # given / when
        results = [self.run_program(child=True) for _ in range(4)]

        # then
        self.assertTrue(all(item.returncode == 1 for item in results))
        self.assertEqual(len({item.stderr for item in results}), 4)

    def test_다른_호출은_PATH의_다음_프로그램으로_넘어간다(self):
        """역할 표시가 없는 호출은 시드한 프로그램을 거치지 않고 다음 codex 를 실행한다."""
        # given / when
        result = self.run_program(child=False)

        # then
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "real-codex exec x"))


class T36Test(LimitTaskBase):
    task_id = "T36"

    def test_여덟_질문의_정답을_담은_답은_모든_검사를_통과한다(self):
        """여덟 질문에 맞게 답하고 파일을 바꾸지 않으면 필수 검사가 모두 통과한다."""
        # given / when
        outcome = self.grade(view(FULL_ANSWERS))

        # then
        self.assertEqual([name for name, passed in outcome.items() if not passed], [])
        self.assertEqual(len([name for name in outcome if name.startswith("q")]), 8)

    def test_빈_답은_질문_검사를_모두_실패하고_변경_없음은_통과한다(self):
        """답이 비어 있으면 여덟 질문 검사가 실패하고 no-changes 만 통과한다."""
        # given / when
        outcome = self.grade(view(""))

        # then
        self.assertEqual([name for name, passed in outcome.items() if passed], ["no-changes"])

    def test_질문_하나만_틀리면_그_검사만_실패한다(self):
        """SCHEMA_VERSION 답을 2로 바꾸면 q7 검사만 실패한다."""
        # given
        answer = FULL_ANSWERS.replace("SCHEMA_VERSION 은 1 입니다", "SCHEMA_VERSION 은 2 입니다")

        # when
        outcome = self.grade(view(answer))

        # then
        self.assertEqual([name for name, passed in outcome.items() if not passed], ["q7-schema"])

    def test_파일을_바꾸면_no_changes가_실패한다(self):
        """읽기만 하라는 요청에서 파일을 고치면 no-changes 가 실패한다."""
        # given
        (self.repo / "inventory" / "money.py").write_text("# edited\n", encoding="utf-8")

        # when
        outcome = self.grade(view(FULL_ANSWERS))

        # then
        self.assertFalse(outcome["no-changes"])

    def test_답의_근거는_픽스처_코드에_있다(self):
        """질문 하나하나의 정답이 inventory-service 소스에 실제로 있다."""
        # given
        source = {path.name: path.read_text(encoding="utf-8") for path in (FIXTURES_ROOT / "inventory-service" / "inventory").glob("*.py")}

        # when / then
        self.assertIn("ROUND_HALF_UP", source["money.py"])
        self.assertIn("{1,31}", source["validators.py"])
        self.assertIn("MAX_QUANTITY = 1_000_000", source["validators.py"])
        self.assertIn('"quantity is zero"', source["importer.py"])
        self.assertIn("SCHEMA_VERSION = 1", source["serialization.py"])
        self.assertIn("  none", source["formatting.py"])


class T05DenialCheckTest(LimitTaskBase):
    task_id = "T05"

    def test_시작이_거부되지_않은_실행은_통과하고_거부된_실행은_실패한다(self):
        """도구 결과에 한도 메시지가 없으면 no-launch-denied 가 통과하고, 있으면 실패한다."""
        # given
        clean = view("done", (call("a", "ok"),))
        denied = view("done", (call("a", CAP_TEXT),))

        # when
        results = [self.grade(item)["no-launch-denied"] for item in (clean, denied)]

        # then
        self.assertEqual(results, [True, False])

    def test_지침_문장을_인용한_도구_결과와_답은_거부로_세지_않는다(self):
        """지침 문장을 인용한 읽기 결과와 답은 통과하고, 병렬 한도 거부 메시지는 실패한다."""
        # given
        quoted = view("지침에 `Request cap reached` 가 있습니다.", (call("a", INSTRUCTION_TEXT),))
        limit = view("done", (call("a", "Parallel limit reached: 6 agent runs are running on this machine and the "
                                         "parallel limit is 6. Do not poll."),))

        # when
        results = [self.grade(item)["no-launch-denied"] for item in (quoted, limit)]

        # then
        self.assertEqual(results, [True, False])
