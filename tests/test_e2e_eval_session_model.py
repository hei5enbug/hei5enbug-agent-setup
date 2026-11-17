"""Unit tests for the T79 evaluation task: its seeded fake Orca, its call-log graders, and its reference run."""

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

CLAUDE_START = "claude --model claude-opus-5-5 --effort high"
CODEX_START = 'codex -m gpt-6.1-sol -c model_reasoning_effort="high"'
HANDOFF = "Run skill-issue-creator for one issue about release-notes."


def make_view() -> dict[str, Any]:
    return {"final_answer": "", "assistant_texts": [], "tool_calls": [], "delegations": [], "approvals": [],
            "permission_denials": []}


class SessionModelTaskTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.task = json.loads((TASKS_ROOT / "T79.json").read_text(encoding="utf-8"))
        self.repo = self.root / "work" / "repo"
        self.work = self.repo.parent
        self.base = graders.materialize_fixture(self.task, FIXTURES_ROOT, TASKS_ROOT, self.repo)

    def orca(self, *arguments: str) -> dict[str, Any]:
        env = {**os.environ, "FAKE_ORCA_STATE": str(self.work / "orca-state" / "state.json")}
        completed = subprocess.run([str(self.work / "fake-bin" / "orca"), *arguments, "--json"], cwd=self.repo, env=env,
                                   capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout)
        return json.loads(completed.stdout)["result"]

    def kit_workspace(self) -> str:
        return next(item["id"] for item in self.orca("worktree", "list")["worktrees"] if item["displayName"] == "demo-kit")

    def delegate(self, start: str, send: bool = True) -> None:
        created = self.orca("terminal", "create", "--worktree", f"id:{self.kit_workspace()}", "--command", start)
        handle = created["terminal"]["handle"]
        self.orca("terminal", "wait", "--terminal", handle, "--for", "tui-idle", "--timeout-ms", "60000")
        if send:
            self.orca("terminal", "send", "--terminal", handle, "--text", HANDOFF, "--enter")

    def grade(self) -> dict[str, bool]:
        result = graders.grade_run(self.task, self.repo, self.base, make_view(), TASKS_ROOT, self.root / "grade")
        return {check["id"]: check["passed"] for check in result["checks"]}

    def test_과제_정의는_파일과_검사_함수와_환경_자리표시자를_모두_가진다(self):
        """T79의 프롬프트, 참조 해법, 검사 함수가 있고 환경 변수가 실행 폴더의 가짜 Orca와 사용자 자료 폴더를 가리킨다."""
        # Given
        source = (TASKS_ROOT / "custom" / "T79.py").read_text(encoding="utf-8")

        # When
        functions = [check["function"] for check in self.task["checks"] if check["kind"] == "custom"]
        environment = command.task_environment(self.task, self.repo, self.work)

        # Then
        self.assertTrue((TASKS_ROOT / self.task["prompt_file"]).is_file())
        self.assertTrue((TASKS_ROOT / "reference" / "T79" / "apply.py").is_file())
        self.assertEqual([name for name in functions if f"def {name}(" not in source], [])
        self.assertEqual(environment["ORCA_USER_DATA_PATH"], str(self.work / "orca-user-data"))
        self.assertEqual(environment["FAKE_ORCA_STATE"], str(self.work / "orca-state" / "state.json"))

    def test_시드_상태는_플러그인_저장소의_작업공간과_에이전트_터미널_없음과_원래_세션_표식을_만든다(self):
        """demo-kit은 선언된 추적기를 가진 플러그인이고 작업공간에 터미널이 없으며, 원래 세션 표식이 사용자 메시지가 든 기록을 가리킨다."""
        # Given
        workspace = self.kit_workspace()
        marker = self.work / "orca-user-data" / "hei5enbug-agent-setup" / "terminals" / "term_demo_a.json"

        # When
        terminals = self.orca("terminal", "list", "--worktree", f"id:{workspace}")["terminals"]
        transcript = Path(json.loads(marker.read_text(encoding="utf-8"))["transcript_path"])
        found = subprocess.run(
            [sys.executable, str(REPO_ROOT / "skills/skill-issue-creator/scripts/find_tracker.py"), str(self.work / "demo-kit")],
            capture_output=True, text=True, check=False)

        # Then
        self.assertEqual(terminals, [])
        self.assertIn("release-notes", transcript.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(found.stdout)["status"], "declared")
        self.assertEqual(json.loads(found.stdout)["plugin_name"], "demo-kit")

    def test_가짜_Orca는_터미널_생성이_핸들을_돌려주고_대기와_전송을_받아들인다(self):
        """terminal create는 요청한 작업공간에 터미널을 더하고, wait는 satisfied, send는 accepted를 돌려준다."""
        # Given
        workspace = self.kit_workspace()

        # When
        self.delegate(CLAUDE_START)
        terminals = self.orca("terminal", "list", "--worktree", f"id:{workspace}")["terminals"]
        waited = self.orca("terminal", "wait", "--terminal", terminals[0]["handle"], "--for", "tui-idle")
        sent = self.orca("terminal", "send", "--terminal", terminals[0]["handle"], "--text", "x", "--enter")

        # Then
        self.assertEqual([item["handle"] for item in terminals], ["term_started_2"])
        self.assertTrue(waited["wait"]["satisfied"])
        self.assertTrue(sent["send"]["accepted"])

    def test_아무것도_하지_않은_실행은_저장소_검사만_통과한다(self):
        """세션을 시작하지 않으면 위임, 모델 지정, Fable·Astra 없음, 전달 검사가 모두 실패하고 저장소는 그대로다."""
        # Given / When
        outcome = self.grade()

        # Then
        self.assertEqual({name for name, passed in outcome.items() if passed}, {"repositories-untouched"})

    def test_참조_해법과_Codex_형식의_시작은_모든_검사를_통과한다(self):
        """Claude의 --model과 --effort로도, Codex의 -m과 -c model_reasoning_effort로도 모든 필수 검사가 통과한다."""
        for start in (CLAUDE_START, CODEX_START):
            with self.subTest(start=start):
                # Given
                self.setUp()
                self.delegate(start)

                # When
                outcome = self.grade()

                # Then
                self.assertEqual([name for name, passed in outcome.items() if not passed], [])

    def test_참조_실행_스크립트는_모든_검사를_통과한다(self):
        """tasks/reference/T79/apply.py를 실행하면 Opus와 high를 적은 시작과 전달이 남아 모든 필수 검사가 통과한다."""
        # Given
        script = TASKS_ROOT / "reference" / "T79" / "apply.py"

        # When
        subprocess.run([sys.executable, "-B", str(script), str(self.repo)], cwd=self.repo, check=True, capture_output=True,
                       text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        outcome = self.grade()

        # Then
        self.assertEqual([name for name, passed in outcome.items() if not passed], [])

    def test_모델_없는_시작은_모델_지정_검사만_실패하고_Fable이나_Astra는_그_검사만_실패한다(self):
        """모델이나 effort가 빠진 시작은 지정 검사에서, Fable이나 Astra를 적은 시작은 금지 검사에서 실패하고 나머지는 통과한다."""
        cases = {
            "no model": ("claude", {"every-start-names-model-and-effort"}),
            "no effort": ("claude --model claude-opus-5-5", {"every-start-names-model-and-effort"}),
            "fable": ("claude --model claude-fable-5-2 --effort high", {"no-fable-or-astra-start"}),
            "astra": ('codex -m gpt-6-astra -c model_reasoning_effort="high"', {"no-fable-or-astra-start"}),
        }
        for name, (start, failing) in cases.items():
            with self.subTest(case=name):
                # Given
                self.setUp()
                self.delegate(start)

                # When
                outcome = self.grade()

                # Then
                self.assertEqual({check for check, passed in outcome.items() if not passed}, failing)

    def test_전달이_없거나_다른_저장소에서_시작하면_해당_검사가_실패한다(self):
        """작업 요약을 보내지 않으면 전달 검사가, 플러그인이 아닌 저장소의 작업공간에서 시작하면 위임 검사가 실패한다."""
        # Given
        self.delegate(CLAUDE_START, send=False)

        # When
        unsent = self.grade()
        self.setUp()
        main_a = next(item["id"] for item in self.orca("worktree", "list")["worktrees"] if item["displayName"] == "demo-a")
        self.orca("terminal", "create", "--worktree", f"id:{main_a}", "--command", CLAUDE_START)
        elsewhere = self.grade()

        # Then
        self.assertEqual({check for check, passed in unsent.items() if not passed}, {"handoff-sent-to-the-new-terminal"})
        self.assertFalse(elsewhere["delegated-through-a-new-terminal"])


if __name__ == "__main__":
    unittest.main()
