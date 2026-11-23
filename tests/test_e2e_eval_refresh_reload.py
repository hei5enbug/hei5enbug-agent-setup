"""Unit tests for the T81 evaluation task: its seeded sessions, its fake Orca and plugin commands, and its graders."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
TASKS_ROOT = E2E_ROOT / "tasks"
FIXTURES_ROOT = E2E_ROOT / "fixtures"
SCRIPT = REPO_ROOT / "skills/orca-plugin-refresh/scripts/orca_plugin_refresh.py"
sys.path.insert(0, str(E2E_ROOT))
sys.path.insert(0, str(REPO_ROOT / "skills/orca-plugin-refresh/scripts"))

from harness import command, graders  # noqa: E402

DONE_ANSWER = "term_demo_a(Claude Code) 세션은 /reload-plugins가 반영됐습니다. term_demo_b(Codex) 세션은 Codex 플러그인을 읽지 못해 건드리지 않았습니다."
DEFERRED_ANSWER = "term_demo_a 세션은 아직 쉬지 않아 도우미에 넘겨 대기 중입니다. term_demo_b는 건드리지 않았습니다."
SELF_UPDATE_ANSWER = ("- **demo-a:** 설치된 버전은 2.26.0입니다. 지침은 바뀌지 않아서 `/compact`는 하지 않았습니다. "
                      "`DISABLE_UPDATES` 설정 때문에 Claude Code 자체 업데이트는 건너뛰었습니다.\n"
                      "- demo-a: Claude Code self-update was skipped because updates are disabled.")
FIRST, CONTROL = "term_demo_a", "term_demo_b"


def make_view(answer: str = "") -> dict[str, Any]:
    return {"final_answer": answer, "assistant_texts": [], "tool_calls": [], "delegations": [], "approvals": [],
            "permission_denials": []}


class RefreshReloadTaskTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.task = json.loads((TASKS_ROOT / "T81.json").read_text(encoding="utf-8"))
        self.repo = self.root / "work" / "repo"
        self.work = self.repo.parent
        self.base = graders.materialize_fixture(self.task, FIXTURES_ROOT, TASKS_ROOT, self.repo)
        self.environment = {**os.environ, **command.task_environment(self.task, self.repo, self.work)}
        for name in ("ORCA_CLI_COMMAND", "ORCA_DEV_REPO_ROOT", "CLAUDE_CODE_ENTRYPOINT", "CODEX_HOME"):
            self.environment.pop(name, None)

    def orca(self, *arguments: str) -> dict[str, Any]:
        done = subprocess.run([str(self.work / "fake-bin" / "orca"), *arguments, "--json"], env=self.environment,
                              capture_output=True, text=True, check=False)
        return json.loads(done.stdout)

    def refresh(self, *arguments: str) -> dict[str, Any]:
        done = subprocess.run([sys.executable, "-B", str(SCRIPT), *arguments, "--json"], env=self.environment,
                              capture_output=True, text=True, check=False, timeout=120)
        return json.loads(done.stdout)

    def calls(self) -> list[dict[str, Any]]:
        path = self.work / "orca-state" / "calls.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []

    def write_calls(self, *sends: tuple[str, str]) -> None:
        lines = [{"argv": ["terminal", "send", "--terminal", handle, "--text", text, "--enter", "--json"], "ok": True}
                 for handle, text in sends]
        (self.work / "orca-state").mkdir(exist_ok=True)
        (self.work / "orca-state" / "calls.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")

    def grade(self, answer: str = "") -> dict[str, bool]:
        result = graders.grade_run(self.task, self.repo, self.base, make_view(answer), TASKS_ROOT, self.root / "grade")
        return {check["id"]: check["passed"] for check in result["checks"]}

    def test_과제_정의는_파일과_검사_함수_환경_자리표시자가_모두_있다(self):
        """T81의 프롬프트, 설정 스크립트, 검사 함수가 있고 환경 변수는 실행 폴더를 가리키며 에이전트 자신의 터미널은 목록에 없다."""
        # Given
        source = (TASKS_ROOT / "custom" / "T81.py").read_text(encoding="utf-8")

        # When
        functions = [check["function"] for check in self.task["checks"] if check["kind"] == "custom"]
        terminals = [item["handle"] for item in self.orca("terminal", "list")["result"]["terminals"]]

        # Then
        self.assertTrue((TASKS_ROOT / self.task["prompt_file"]).is_file())
        self.assertEqual([name for name in functions if f"def {name}(" not in source], [])
        self.assertEqual(self.environment["ORCA_USER_DATA_PATH"], str(self.work / "orca-user"))
        self.assertTrue(self.environment["PATH"].startswith(f"{self.work}/fake-bin:"))
        self.assertNotIn(self.environment["ORCA_TERMINAL_HANDLE"], terminals)
        self.assertEqual(terminals, [FIRST, CONTROL])

    def test_시드_상태는_백그라운드_작업이_남은_Claude_세션과_이미_현재인_Codex_세션을_만든다(self):
        """첫 세션의 기록은 차례가 끝났지만 알림을 남겨야 하는 작업이 있어 owing이고, 표식은 설치된 지침과 옛 폴더를 가리킨다."""
        # Given
        from refresh_host_record import record_state
        marker = json.loads((self.work / "orca-user" / "hei5enbug-agent-setup" / "terminals" / f"{FIRST}.json").read_text(encoding="utf-8"))
        installed = json.loads((self.work / "plugin-state" / "state.json").read_text(encoding="utf-8"))["claude_record"]["installPath"]

        # When
        verdict = record_state("claude", marker["transcript_path"], detailed=True)

        # Then
        self.assertEqual(verdict, "owing")
        self.assertTrue(Path(marker["root"]).is_dir())
        self.assertNotEqual(marker["root"], installed)

    def test_가짜_Orca는_reload를_받으면_세션_기록에_성공_결과를_덧붙이고_끝나지_않은_세션은_한가하지_않다고_답한다(self):
        """첫 세션은 tui-idle을 기다리면 timeout이고, /reload-plugins를 보내면 기록 끝에 Reloaded 결과가 붙으며, 모든 호출이 로그에 남는다."""
        # Given
        transcript = self.work / "transcripts" / "claude-session.jsonl"
        before = len(transcript.read_text(encoding="utf-8").splitlines())

        # When
        waited = self.orca("terminal", "wait", "--terminal", FIRST, "--for", "tui-idle", "--timeout-ms", "500")
        self.orca("terminal", "send", "--terminal", FIRST, "--text", "/reload-plugins", "--enter")

        # Then
        appended = transcript.read_text(encoding="utf-8").splitlines()[before:]
        self.assertEqual(waited["error"]["code"], "timeout")
        self.assertIn("Reloaded: 7 plugins", appended[-1])
        self.assertEqual([call["argv"][:2] for call in self.calls()], [["terminal", "wait"], ["terminal", "send"]])

    def test_실제_스크립트는_백그라운드_작업이_남은_세션에_reload를_보내고_네_검사를_모두_통과한다(self):
        """apply-installed와 apply를 시드 상태에 그대로 실행하면 첫 세션만 reload를 받고 done이 되며, 통제 세션은 건드리지 않고, 네 필수 검사가 통과한다.
        잡는 회귀: 차례가 끝나고 백그라운드 작업만 남은 세션을 쉬지 않는다고 보고 도우미에 넘겨 reload를 보내지 않는 판정."""
        # Given
        run_id = self.refresh("apply-installed")["run_id"]
        self.addCleanup(subprocess.run, ["pkill", "-f", f"self-apply --run-id {run_id}"], check=False)

        # When
        applied = self.refresh("apply", "--run-id", run_id)

        # Then
        by_status = {session["terminal"].removeprefix("…"): session["status"] for session in applied["sessions"]}
        self.assertEqual(by_status["demo_a"], "done")
        self.assertEqual(self.grade(DONE_ANSWER), {"reload-sent-to-running-session": True, "nothing-else-sent-to-running-session": True,
                                                   "nothing-sent-to-control-session": True,
                                                   "running-session-not-reported-unfinished": True})

    def test_Claude_Code_자체_업데이트를_건너뛰었다는_줄은_세션_미완료로_세지_않고_세션을_미룬_줄은_센다(self):
        """demo-a 줄에 자체 업데이트 건너뜀이 있어도 통과하고, 같은 줄에 세션 반영을 미뤘다는 말이 있으면 실패한다.
        잡는 회귀: 자체 업데이트 건너뜀의 `건너뛰`를 세션을 새로 고치지 못했다는 보고로 읽는 판정."""
        # Given
        mixed = SELF_UPDATE_ANSWER + "\ndemo-a 세션은 반영을 건너뛰었습니다."

        # When
        outcomes = [self.grade(answer)["running-session-not-reported-unfinished"] for answer in (SELF_UPDATE_ANSWER, mixed, DEFERRED_ANSWER)]

        # Then
        self.assertEqual(outcomes, [True, False, False])

    def test_refresh_명령_한_번이_같은_결과를_내고_apply와_orphans_절을_함께_담는다(self):
        """refresh --installed 한 번이 시드 상태에서 apply-installed와 apply를 이은 것과 같이 첫 세션에만 reload를 보내고 orphans 절도 낸다.
        잡는 회귀: 합친 명령이 가짜 Orca 위에서 apply 뒤 orphans를 읽지 못해 결과 절이 빠지거나 세션 결과가 달라지는 문제."""
        # Given / When
        output = self.refresh("refresh", "--installed")
        self.addCleanup(subprocess.run, ["pkill", "-f", f"self-apply --run-id {output['update']['run_id']}"], check=False)

        # Then
        by_status = {session["terminal"].removeprefix("…"): session["status"] for session in output["apply"]["sessions"]}
        self.assertEqual(by_status["demo_a"], "done")
        self.assertEqual({"ok", "update", "apply", "orphans"}, set(output))
        self.assertTrue(output["orphans"]["ok"])
        self.assertEqual(self.grade(DONE_ANSWER), {"reload-sent-to-running-session": True, "nothing-else-sent-to-running-session": True,
                                                   "nothing-sent-to-control-session": True,
                                                   "running-session-not-reported-unfinished": True})

    def test_세션이_사라지면_이전_버전_스크립트의_도우미도_제한_시간_안에_끝난다(self):
        """origin/main의 스크립트가 첫 세션을 도우미에 넘겨도, 터미널이 사라진 뒤 도우미가 한 시간을 채우지 않고 곧 끝나며 시드의 기본 한도는 두 분 안이다.
        잡는 회귀: 가짜 Orca가 세션을 없애지 않아 이전 버전 실행의 도우미가 실행이 끝난 뒤에도 한 시간 동안 남는 문제."""
        # Given
        exists = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--verify", "-q", "origin/main"], capture_output=True, check=False)
        if exists.returncode != 0:
            self.skipTest("origin/main is not available")
        before = self.root / "before"
        before.mkdir()
        archive = subprocess.run(["git", "-C", str(REPO_ROOT), "archive", "origin/main"], capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(before)], input=archive.stdout, check=True)
        script = before / "skills/orca-plugin-refresh/scripts/orca_plugin_refresh.py"
        state_path = self.work / "orca-state" / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        seeded = state["vanish_after_seconds"]
        state_path.write_text(json.dumps({**state, "vanish_after_seconds": 3}), encoding="utf-8")
        run_id = json.loads(subprocess.run([sys.executable, "-B", str(script), "apply-installed", "--json"], env=self.environment,
                                           capture_output=True, text=True, check=False, timeout=120).stdout)["run_id"]
        pattern = f"self-apply --run-id {run_id}"
        self.addCleanup(subprocess.run, ["pkill", "-f", pattern], check=False)

        self.orca("terminal", "list")
        time.sleep(4)

        # When
        subprocess.run([sys.executable, "-B", str(script), "apply", "--run-id", run_id, "--json"], env=self.environment,
                       capture_output=True, text=True, check=False, timeout=120)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline and subprocess.run(["pgrep", "-f", pattern], capture_output=True, check=False).returncode == 0:
            time.sleep(1)

        # Then
        self.assertEqual(subprocess.run(["pgrep", "-f", pattern], capture_output=True, check=False).returncode, 1)
        self.assertLessEqual(seeded, 120)
        self.assertEqual([call for call in self.calls() if call["argv"][:2] == ["terminal", "send"]], [])

    def test_apply_앞의_둘러보기_조회는_사라짐_카운트다운을_시작하지_않아_reload가_그대로_나간다(self):
        """apply 전에 terminal list를 부르고 한도(3초)보다 오래 기다려도 세션은 사라지지 않아 apply가 reload를 보내고 네 검사가 통과한다.
        잡는 회귀: 둘러보는 terminal list가 카운트다운을 시작해 늦게 apply한 실행이 세션 없이 실패하는 문제."""
        # Given
        state_path = self.work / "orca-state" / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state_path.write_text(json.dumps({**state, "vanish_after_seconds": 3}), encoding="utf-8")
        run_id = self.refresh("apply-installed")["run_id"]
        self.orca("terminal", "list")
        time.sleep(4)

        # When
        self.refresh("apply", "--run-id", run_id)

        # Then
        self.assertEqual(self.grade(DONE_ANSWER), {"reload-sent-to-running-session": True, "nothing-else-sent-to-running-session": True,
                                                   "nothing-sent-to-control-session": True,
                                                   "running-session-not-reported-unfinished": True})

    def export_origin_main(self) -> Path:
        """The plugin as `origin/main` holds it, in a temp folder; skips when that ref is missing or already holds the change."""
        exists = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--verify", "-q", "origin/main"], capture_output=True, check=False)
        if exists.returncode != 0:
            self.skipTest("origin/main is not available")
        before = self.root / "origin-main-plugin"
        before.mkdir()
        archive = subprocess.run(["git", "-C", str(REPO_ROOT), "archive", "origin/main"], capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(before)], input=archive.stdout, check=True)
        if "NEW_PROCESS_SOURCES" in (before / "skills/orca-plugin-refresh/scripts/refresh_follow.py").read_text(encoding="utf-8"):
            self.skipTest("origin/main already holds the change")
        return before

    def session_flow(self, name: str, plugin_dir: Path, answer: str) -> tuple[list[tuple[str, str]], dict[str, bool]]:
        """Seed T81 from a plugin folder, run what a session runs from that plugin (apply-installed, then the continuation
        script its output names, apply), wait for the helper to end, and return the sends and the graded checks."""
        repo = self.root / name / "repo"
        base = graders.materialize_fixture(self.task, FIXTURES_ROOT, TASKS_ROOT, repo, plugin_dir)
        work = repo.parent
        environment = {**os.environ, **command.task_environment(self.task, repo, work)}
        for key in ("ORCA_CLI_COMMAND", "ORCA_DEV_REPO_ROOT", "CLAUDE_CODE_ENTRYPOINT", "CODEX_HOME"):
            environment.pop(key, None)
        state_path = work / "orca-state" / "state.json"
        state_path.write_text(json.dumps({**json.loads(state_path.read_text(encoding="utf-8")), "vanish_after_seconds": 3}), encoding="utf-8")

        def run(script: str, *arguments: str) -> dict[str, Any]:
            done = subprocess.run([sys.executable, "-B", script, *arguments, "--json"], env=environment, capture_output=True,
                                  text=True, check=False, timeout=120)
            return json.loads(done.stdout)

        installed = run(str(plugin_dir / "skills/orca-plugin-refresh/scripts/orca_plugin_refresh.py"), "apply-installed")
        pattern = f"self-apply --run-id {installed['run_id']}"
        self.addCleanup(subprocess.run, ["pkill", "-f", pattern], check=False)
        run(installed["script"], "apply", "--run-id", installed["run_id"])
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline and subprocess.run(["pgrep", "-f", pattern], capture_output=True, check=False).returncode == 0:
            time.sleep(1)
        self.assertEqual(subprocess.run(["pgrep", "-f", pattern], capture_output=True, check=False).returncode, 1)
        calls = work / "orca-state" / "calls.jsonl"
        sends = [(call["argv"][call["argv"].index("--terminal") + 1], call["argv"][call["argv"].index("--text") + 1])
                 for call in (json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines())
                 if call["argv"][:2] == ["terminal", "send"]]
        graded = graders.grade_run(self.task, repo, base, make_view(answer), TASKS_ROOT, self.root / f"{name}-grade")
        return sends, {check["id"]: check["passed"] for check in graded["checks"]}

    def test_이전_버전_플러그인으로_심은_세션은_옛_스크립트를_돌려_reload를_보내지_않는다(self):
        """origin/main 플러그인으로 시드하고 세션이 도는 흐름(apply-installed, 그 출력의 이어갈 스크립트, apply)을 돌리면 첫 세션에 아무것도 보내지 않고 reload 검사가 실패하며, 도우미도 한도 안에 끝난다.
        잡는 회귀: 시드한 설치 사본이 시험 중인 변형이 아닌 하네스 체크아웃의 코드여서 before 변형도 새 apply를 돌려 두 변형이 구분되지 않는 문제."""
        # Given
        before = self.export_origin_main()

        # When
        sends, results = self.session_flow("before", before, DEFERRED_ANSWER)

        # Then
        self.assertEqual([send for send in sends if send[0] == FIRST], [])
        self.assertFalse(results["reload-sent-to-running-session"])

    def test_새_버전_플러그인으로_심은_세션은_이어갈_스크립트로_reload를_보내고_네_검사를_통과한다(self):
        """이 체크아웃 플러그인으로 시드하고 같은 흐름을 돌리면 첫 세션에 reload만 보내고 네 필수 검사가 모두 통과한다."""
        # Given / When
        sends, results = self.session_flow("after", REPO_ROOT, DONE_ANSWER)

        # Then
        self.assertEqual([send for send in sends if send[0] == FIRST], [(FIRST, "/reload-plugins")])
        self.assertTrue(all(results.values()), results)

    def test_reload를_보내지_않고_도우미에_넘겼다고_답한_실행은_두_검사에서_실패한다(self):
        """기록된 실패 실행은 어떤 명령도 보내지 않고 첫 세션을 대기 중이라고 보고하므로 reload 검사와 보고 검사만 실패한다."""
        # Given
        self.write_calls()

        # When
        results = self.grade(DEFERRED_ANSWER)

        # Then
        self.assertEqual(sorted(name for name, passed in results.items() if not passed),
                         ["reload-sent-to-running-session", "running-session-not-reported-unfinished"])

    def test_세션을_끝내거나_압축하거나_통제_세션에_보낸_실행은_해당_검사에서_실패한다(self):
        """첫 세션에 /exit나 /compact를 더 보내면 그 검사가, 통제 세션에 명령을 보내면 통제 검사가 실패하고 reload 검사는 통과한다."""
        # Given
        self.write_calls((FIRST, "/reload-plugins"), (FIRST, "/compact"), (FIRST, "/exit"), (CONTROL, "/reload-plugins"))

        # When
        results = self.grade(DONE_ANSWER)

        # Then
        self.assertEqual(sorted(name for name, passed in results.items() if not passed),
                         ["nothing-else-sent-to-running-session", "nothing-sent-to-control-session"])
        self.assertTrue(results["reload-sent-to-running-session"])


if __name__ == "__main__":
    unittest.main()
