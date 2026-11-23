"""Unit tests for the forced-delegation tasks F02, F82, and T153 of the end-to-end evaluation.

Offline proof: the unmodified fixture fails, the reference solution with a completed implementation delegation passes, and
the same solution without one fails only the delegation check.
"""

from __future__ import annotations

import os
import shutil
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

from harness import graders, render  # noqa: E402

TOOLS_MISSING = render.find_tool(render.BUN_ENV, ("bun",)) is None or render.find_tool(
    render.CHROME_ENV, render.CHROME_NAMES, render.CHROME_FALLBACKS) is None
WORKER_PROMPT = "구현은 직접 하지 말고 구현 워커 에이전트에게 맡겨서 진행해줘."
DELEGATION = {"kind": "agent", "type": "worker", "class": "implementation", "prompt": "", "exit": None,
              "tool_use_id": "t1", "order": 0, "is_error": False, "completed": True}
RUNNER = {**DELEGATION, "kind": "role_runner", "type": "implementation", "exit": 0}
SPAWN = {"id": "s1", "name": "spawn_agent", "source": "main", "is_error": False, "parent": None,
         "input": {"subagent_type": "worker", "model": "gpt-6.2-sol", "reasoning_effort": "high"},
         "result_text": "denied by the guard: example"}


def view_with(*delegations: dict[str, Any], calls: tuple[dict[str, Any], ...] = ()) -> dict[str, Any]:
    return {"delegations": list(delegations), "tool_calls": list(calls), "assistant_texts": [], "final_answer": "done",
            "approvals": [], "permission_denials": []}


class ForcingTaskCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.count = 0

    def results(self, task_id: str, reference: bool, view: dict[str, Any]) -> dict[str, dict[str, Any]]:
        self.count += 1
        task = graders.load_task(TASKS_ROOT, task_id)
        repo = self.root / f"repo-{self.count}"
        base = graders.materialize_fixture(task, FIXTURES_ROOT, TASKS_ROOT, repo)
        if reference:
            overlay = TASKS_ROOT / "reference" / task_id / "files"
            if overlay.is_dir():
                shutil.copytree(overlay, repo, dirs_exist_ok=True)
            env = {**os.environ, "PYTHONPATH": str(TASKS_ROOT / "reference"), "PYTHONDONTWRITEBYTECODE": "1"}
            subprocess.run([sys.executable, "-B", str(TASKS_ROOT / "reference" / task_id / "apply.py"), str(repo)], cwd=repo,
                           env=env, check=True, capture_output=True, text=True)
        work = self.root / f"work-{self.count}"
        shutil.copytree(repo, work / "repo", symlinks=True)
        ctx = graders.GradeContext(task=task, repo=work / "repo", base=base, view=view, tasks_root=TASKS_ROOT, work=work,
                                   origin=repo)
        ctx.snapshot_git_facts()
        return {spec["id"]: graders.run_check(ctx, spec) for spec in task["checks"]}

    def failed_required(self, found: dict[str, dict[str, Any]]) -> set[str]:
        return {name for name, result in found.items() if result["required"] and not result["passed"]}


class ForcingTaskTest(ForcingTaskCase):
    def test_두_과제의_프롬프트는_구현_워커에게_맡기라고_요청한다(self):
        """F02와 F82 프롬프트는 원래 과제 프롬프트에 구현 워커 위임 요청 한 문장을 더한 것이다."""
        for forced, original in (("F02", "T02"), ("F82", "T82")):
            with self.subTest(forced):
                text = (TASKS_ROOT / "prompts" / f"{forced}.txt").read_text(encoding="utf-8")
                source = (TASKS_ROOT / "prompts" / f"{original}.txt").read_text(encoding="utf-8")
                self.assertTrue(text.startswith(source.rstrip("\n")) and WORKER_PROMPT in text)

    def test_두_과제의_검사_함수와_참조_해법이_모두_있다(self):
        """custom 검사 함수가 정의돼 있고 참조 해법이 있다."""
        for task_id in ("F02", "F82"):
            with self.subTest(task_id):
                task = graders.load_task(TASKS_ROOT, task_id)
                source = (TASKS_ROOT / "custom" / f"{task_id}.py").read_text(encoding="utf-8")
                missing = [c["id"] for c in task["checks"] if c["kind"] == "custom" and f"def {c['function']}(" not in source]
                self.assertEqual((missing, (TASKS_ROOT / "reference" / task_id / "apply.py").is_file()), ([], True))

    def test_F02는_수정하지_않은_저장소와_위임_없는_해법에서_실패한다(self):
        """원본은 숨은 테스트와 위임 검사에서, 위임 없는 참조 해법은 위임 검사에서만 실패한다."""
        base = self.failed_required(self.results("F02", False, view_with(DELEGATION)))
        no_delegation = self.failed_required(self.results("F02", True, view_with()))
        self.assertTrue({"hidden-tests", "new-tests"} <= base)
        self.assertEqual(no_delegation, {"worker-delegated"})

    def test_F02는_위임이_끝난_참조_해법에서_모든_필수_검사를_통과한다(self):
        """워커나 러너 위임이 끝났으면 통과하고, 실패한 위임은 위임으로 세지 않는다."""
        for delegation in (DELEGATION, RUNNER):
            with self.subTest(delegation["kind"]):
                self.assertEqual(self.failed_required(self.results("F02", True, view_with(delegation))), set())
        failed = {**DELEGATION, "is_error": True, "completed": False}
        self.assertEqual(self.failed_required(self.results("F02", True, view_with(failed))), {"worker-delegated"})

    def test_worker_route는_스폰_호출의_역할_모델_노력과_결과_앞부분을_기록한다(self):
        """가드 거부 사유는 스폰 호출 결과 앞부분으로 남는다."""
        found = self.results("F02", True, view_with(DELEGATION, calls=(SPAWN,)))["worker-route"]
        spawn = found["data"]["spawns"][0]
        self.assertEqual((found["passed"], spawn["model"], spawn["effort"], spawn["agent_type"], spawn["result"]),
                         (True, "gpt-6.2-sol", "high", "worker", "denied by the guard: example"))

    def test_T153은_수정하지_않은_저장소와_위임_없는_해법에서_실패하고_위임이_끝난_해법에서_통과한다(self):
        """원본은 숨은 테스트와 위임 검사에서, 위임 없는 참조 해법은 위임 검사에서만 실패하고, 위임이 끝난 참조 해법은 모든 필수 검사를 통과한다."""
        base = self.failed_required(self.results("T153", False, view_with(DELEGATION)))
        no_delegation = self.failed_required(self.results("T153", True, view_with()))
        passed = self.failed_required(self.results("T153", True, view_with(DELEGATION)))
        self.assertTrue({"hidden-tests", "readme-lock-timeout"} <= base)
        self.assertEqual((no_delegation, passed), ({"worker-delegated"}, set()))

    def test_T153_프롬프트는_T57_요구사항_뒤에_구현_워커_위임_요청_한_문장을_더한다(self):
        """T153 프롬프트는 구현 워커 위임 요청 문장으로 끝나고 위임 요청 없이 같은 요구사항을 담는다."""
        text = (TASKS_ROOT / "prompts" / "T153.txt").read_text(encoding="utf-8")
        self.assertIn(WORKER_PROMPT, text)
        self.assertIn("INVENTORY_LOCK_TIMEOUT", text)

    @unittest.skipIf(TOOLS_MISSING, "bun or Chrome is not installed")
    def test_F82는_원본과_위임_없는_해법에서_실패하고_위임_있는_해법에서_통과한다(self):
        """네 줄 수정 해법에 위임이 끝난 기록이 있어야 통과한다."""
        base = self.failed_required(self.results("F82", False, view_with(DELEGATION)))
        no_delegation = self.failed_required(self.results("F82", True, view_with()))
        passed = self.failed_required(self.results("F82", True, view_with(DELEGATION)))
        self.assertTrue({"spacing-16", "label-full-name"} <= base)
        self.assertEqual((no_delegation, passed), ({"worker-delegated"}, set()))


if __name__ == "__main__":
    unittest.main()
