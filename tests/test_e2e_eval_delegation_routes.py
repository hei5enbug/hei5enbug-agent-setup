"""Tests for the route measurement of #109: forcing and grading a route, and the tasks T65 and T66."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
TASKS_ROOT = E2E_ROOT / "tasks"
FIXTURES_ROOT = E2E_ROOT / "fixtures"
sys.path.insert(0, str(E2E_ROOT))

from harness import command, graders, matrix, runner  # noqa: E402
from harness.config import HarnessConfig  # noqa: E402
from harness.process import ProcessResult  # noqa: E402
from test_e2e_eval_graders import apply_reference, delegation, make_view  # noqa: E402

WORKER_CALL = delegation("role_runner", "implementation", "edit three files", exit_code=0, ident="w1")
FAILED_WORKER_CALL = delegation("role_runner", "implementation", "edit three files", exit_code=3, ident="w2")
REVIEW_CALL = delegation("agent", "review", "review the diff", ident="r1")


def load_task(task_id: str) -> dict:
    return json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))


class TempCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)

    def materialize(self, task_id: str):
        task = load_task(task_id)
        self.count = getattr(self, "count", 0) + 1
        repo = self.root / f"repo-{task_id}-{self.count}"
        return task, repo, graders.materialize_fixture(task, FIXTURES_ROOT, TASKS_ROOT, repo)

    def grade(self, task: dict, repo: Path, base: str, view: dict) -> dict:
        return graders.grade_run(task, repo, base, view, TASKS_ROOT, self.root / f"work-{self.count}")


class RouteVariantTest(unittest.TestCase):
    def variant(self, **extra) -> dict:
        return command.validate_variant({"name": "v", "ref": "HEAD", **extra})

    def test_경로를_정한_변형은_프롬프트_끝에_그_경로의_문장을_붙이고_정하지_않으면_그대로_둔다(self):
        """given 프롬프트 파일 when 변형의 route가 main, delegate, 없음 then 문장이 붙거나 붙지 않는다."""
        # given
        with tempfile.TemporaryDirectory() as folder:
            tasks = Path(folder)
            (tasks / "p.txt").write_text("기능을 추가해줘\n", encoding="utf-8")
            task = {"prompt_file": "p.txt"}

            # when
            main = command.run_prompt(tasks, task, self.variant(route="main"))
            delegate = command.run_prompt(tasks, task, self.variant(route="delegate"))
            plain = command.run_prompt(tasks, task, self.variant())
            expected_only = command.run_prompt(tasks, task, self.variant(expect_route="delegate"))

        # then
        self.assertEqual(plain, "기능을 추가해줘")
        self.assertEqual(expected_only, plain)
        self.assertEqual(main, f"기능을 추가해줘\n\n{command.ROUTE_SENTENCES['main']}")
        self.assertEqual(delegate, f"기능을 추가해줘\n\n{command.ROUTE_SENTENCES['delegate']}")
        self.assertNotEqual(main, delegate)

    def test_알_수_없는_경로는_변형_검증에서_거절하고_expect_route는_채점_경로만_정한다(self):
        """given route 값 when 변형을 검증하면 then 알 수 없는 값은 ConfigError이고 expect_route는 채점 경로로만 읽힌다."""
        # given
        bad = {"name": "v", "ref": "HEAD", "route": "both"}

        # when
        with self.assertRaises(command.ConfigError):
            command.validate_variant(bad)

        # then
        self.assertEqual(command.expected_route(self.variant(expect_route="main")), "main")
        self.assertEqual(command.expected_route(self.variant(route="delegate", expect_route="main")), "delegate")
        self.assertIsNone(command.expected_route(self.variant()))

    def test_저장소의_경로_변형은_서로_다른_경로를_강제하고_전_변형은_경로가_없다(self):
        """given 저장소의 변형 파일 when 읽으면 then route-main과 route-delegate는 각각 다른 경로이고 before는 경로가 없다."""
        # given
        root = E2E_ROOT / "variants"

        # when
        loaded = {name: command.load_variant(root, name) for name in ("before", "route-main", "route-delegate")}

        # then
        self.assertEqual([loaded[name].get("route") for name in loaded], [None, "main", "delegate"])
        self.assertEqual(len({loaded[name]["ref"] for name in loaded}), 1)


class RouteRunnerTest(TempCase):
    def setUp(self) -> None:
        super().setUp()
        tasks = self.root / "tasks"
        (tasks / "prompts").mkdir(parents=True)
        (tasks / "prompts" / "T65.txt").write_text("기능을 추가해줘\n", encoding="utf-8")
        self.task = {"id": "T65", "fixture": "demo", "prompt_file": "prompts/T65.txt", "limits": {"wall_seconds": 1, "max_budget_usd": 1}}
        self.cfg = HarnessConfig(run_root=self.root / "runs", tasks_root=tasks)
        self.spec = matrix.make_spec(self.cfg.run_root, "c", "T65", "route-main", 1)
        self.plugin = {"ref": "HEAD", "sha": "abc", "path": "/tmp/p"}
        patch = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.root / "claude"), "CODEX_HOME": str(self.root / "codex")})
        patch.start()
        self.addCleanup(patch.stop)
        graders_stub = SimpleNamespace(materialize_fixture=lambda task, fixtures, tasks_root, dest: Path(dest).mkdir(parents=True) or "base1")
        patch = mock.patch.object(runner, "load_graders", return_value=graders_stub)
        patch.start()
        self.addCleanup(patch.stop)

    def test_실행은_경로_문장이_붙은_프롬프트로_시작하고_run_json에_경로를_남긴다(self):
        """given 경로를 강제하는 변형 when 실행을 시작하면 then 에이전트 프롬프트에 문장이 있고 run.json과 채점 입력이 같은 경로를 가진다."""
        # given
        variant = command.validate_variant({"name": "route-main", "ref": "HEAD", "route": "main"})
        seen = {}

        def finish(spec, task, run, proc, cfg, interrupt=None):
            seen["run"] = run
            return run

        now = datetime(2026, 11, 17, tzinfo=timezone.utc)
        stopped = ProcessResult(returncode=0, timed_out=False, wall_seconds=1.0, started_at=now, ended_at=now)

        # when
        with mock.patch.object(runner, "run_agent", return_value=stopped), mock.patch.object(runner, "finish_run", finish):
            runner.execute_run(self.spec, self.task, variant, self.plugin, self.cfg, {})

        # then
        prompt = (self.spec.result_dir / "prompt.txt").read_text(encoding="utf-8")
        self.assertTrue(prompt.endswith(command.ROUTE_SENTENCES["main"]))
        self.assertEqual(seen["run"]["route"], "main")

    def test_채점_뷰에는_run_json의_경로가_들어가고_경로가_없는_실행의_뷰에는_없다(self):
        """given run.json에 경로가 있는 실행과 없는 실행 when 분석하면 then 채점에 넘긴 뷰와 view.json의 route가 그 값이다."""
        # given
        records = {"view": make_view(), "facts": {}, "claude_report": {}, "codex_report": {}, "usage_source": "x", "checks": {},
                   "violations": [], "extra": {}}
        seen = []

        def grade(spec, task, run, cfg, graders_module, view, interrupt=None):
            seen.append(view)
            return {"checks": [], "success": True}, None

        base = {"run_id": self.spec.run_id, "task": "T65", "variant": "route-main", "rep": 1, "status": "complete", "plugin": {"path": "/tmp/p"},
                "attempts": 1, "base_commit": "base1"}

        # when
        with mock.patch.object(runner, "claude_records", return_value=records), mock.patch.object(runner, "grade_run", grade), \
                mock.patch.object(runner.metrics, "build_metrics", return_value={"success": True}):
            runner.analyze(self.spec, self.task, {**base, "route": "delegate"}, self.cfg)
            routed = json.loads((self.spec.result_dir / "view.json").read_text(encoding="utf-8"))
            runner.analyze(self.spec, self.task, base, self.cfg)
            plain = json.loads((self.spec.result_dir / "view.json").read_text(encoding="utf-8"))

        # then
        self.assertEqual((seen[0].get("route"), routed.get("route")), ("delegate", "delegate"))
        self.assertNotIn("route", seen[1])
        self.assertNotIn("route", plain)


class RouteCheckTest(TempCase):
    def check(self, route, delegations) -> dict | None:
        task, repo, base = self.materialize("T65")
        view = {**make_view(delegations=tuple(delegations)), **({"route": route} if route else {})}
        result = self.grade(task, repo, base, view)
        return next((item for item in result["checks"] if item["id"] == "route-followed"), None)

    def test_main_경로는_구현_위임이_하나라도_있으면_실패하고_없으면_통과한다(self):
        """given main 경로 when 구현 위임이 시도됐거나 없으면 then 시도만 해도 실패하고 리뷰 위임은 세지 않는다."""
        # given
        # when
        clean = self.check("main", [REVIEW_CALL])
        tried = self.check("main", [FAILED_WORKER_CALL])

        # then
        self.assertTrue(clean["passed"] and clean["required"])
        self.assertFalse(tried["passed"])

    def test_delegate_경로는_끝까지_성공한_구현_위임이_있어야_통과한다(self):
        """given delegate 경로 when 위임이 없거나 실패했거나 성공하면 then 성공한 구현 위임이 있을 때만 통과한다."""
        # given
        # when
        none = self.check("delegate", [])
        failed = self.check("delegate", [FAILED_WORKER_CALL])
        done = self.check("delegate", [FAILED_WORKER_CALL, WORKER_CALL])

        # then
        self.assertEqual([none["passed"], failed["passed"], done["passed"]], [False, False, True])

    def test_경로가_없는_실행에는_route_followed_검사가_붙지_않는다(self):
        """given 경로 없는 뷰 when 채점하면 then 검사 목록에 route-followed가 없다."""
        # given
        # when
        check = self.check(None, [WORKER_CALL])

        # then
        self.assertIsNone(check)

    def test_경로를_어기면_다른_검사가_모두_통과해도_성공이_아니다(self):
        """given 참조 해법과 main 경로에서 구현 위임이 있는 뷰 when 채점하면 then 다른 검사는 통과하지만 success는 False다."""
        # given
        task, repo, base = self.materialize("T65")
        apply_reference("T65", repo)
        view = {**make_view("done", delegations=(WORKER_CALL,)), "route": "main"}

        # when
        result = self.grade(task, repo, base, view)

        # then
        failed = [item["id"] for item in result["checks"] if not item["passed"]]
        self.assertEqual(failed, ["route-followed"])
        self.assertFalse(result["success"])


class DelegationTaskTest(TempCase):
    EXPECTED_FAILURES = {"T65": {"hidden-tests", "new-tests", "readme-export", "mirror-updated"}, "T66": {"hidden-tests", "new-tests"}}

    def test_수정하지_않은_저장소는_기대한_필수_검사에서_실패하고_기존_테스트는_통과한다(self):
        """given 수정하지 않은 저장소 when 채점하면 then 숨은 테스트와 새 테스트 검사가 실패하고 regressions는 통과한다."""
        for task_id, expected in self.EXPECTED_FAILURES.items():
            with self.subTest(task_id):
                # given
                task, repo, base = self.materialize(task_id)

                # when
                result = self.grade(task, repo, base, make_view())

                # then
                outcome = {item["id"]: item["passed"] for item in result["checks"]}
                self.assertFalse(result["success"])
                self.assertEqual({name for name, passed in outcome.items() if not passed} & {c["id"] for c in task["checks"] if c["required"]}, expected)
                self.assertTrue(outcome["regressions"])

    def test_참조_해법은_모든_검사를_통과하고_바꾼_파일_수가_과제의_범위_안이다(self):
        """given 참조 해법 when 채점하면 then 모든 검사가 통과하고 T65는 다섯 개, T66은 세 개 파일을 바꾼다."""
        for task_id, count in (("T65", 5), ("T66", 3)):
            with self.subTest(task_id):
                # given
                task, repo, base = self.materialize(task_id)
                apply_reference(task_id, repo)

                # when
                result = self.grade(task, repo, base, make_view("done"))

                # then
                by_id = {item["id"]: item for item in result["checks"]}
                self.assertEqual([name for name, item in by_id.items() if not item["passed"]], [])
                self.assertEqual(len(by_id["files-in-range"]["data"]["changed"]), count)
                self.assertEqual(result["correctness"], 1.0)

    def test_테스트를_더하지_않은_해법은_new_tests에서만_실패한다(self):
        """given 테스트 파일을 뺀 참조 해법 when 채점하면 then new-tests만 실패하고 숨은 테스트는 통과한다."""
        for task_id, test_file in (("T65", "tests/test_export.py"), ("T66", "tests/test_transfer.py")):
            with self.subTest(task_id):
                # given
                task, repo, base = self.materialize(task_id)
                apply_reference(task_id, repo)
                (repo / test_file).unlink()

                # when
                result = self.grade(task, repo, base, make_view("done"))

                # then
                failed = {item["id"] for item in result["checks"] if not item["passed"]}
                self.assertEqual(failed, {"new-tests", "files-in-range"} if task_id == "T66" else {"new-tests"})

    def test_범위를_넘는_변경은_참고_검사만_실패시키고_성공은_유지한다(self):
        """given 참조 해법에 파일 둘을 더 바꾼 저장소 when 채점하면 then files-in-range만 실패하고 success는 True다."""
        # given
        task, repo, base = self.materialize("T65")
        apply_reference("T65", repo)
        (repo / "docs" / "ko" / "AGENTS.ko.md").write_text("# 변경\n", encoding="utf-8")
        (repo / "config" / "settings.toml").write_text("page_size = 20\n# note\n", encoding="utf-8")

        # when
        result = self.grade(task, repo, base, make_view("done"))

        # then
        failed = {item["id"] for item in result["checks"] if not item["passed"]}
        self.assertEqual(failed, {"files-in-range"})
        self.assertTrue(result["success"])


if __name__ == "__main__":
    unittest.main()
