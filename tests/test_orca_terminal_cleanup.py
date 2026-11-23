"""The first-prompt hook closes only never-used shell terminals of the session's own worktree, with no model turn."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
E2E_ROOT = REPO_ROOT / "evals/e2e"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(E2E_ROOT))

import orca_terminal_cleanup  # noqa: E402
from harness import graders  # noqa: E402

OWN = "term_own"
PROMPT = "demo % "


def agent(handle: str, worktree: str = "w1") -> dict:
    return {"handle": handle, "worktreeId": worktree, "agentIdentity": "claude", "screen": ["❯ "]}


def shell(handle: str, worktree: str = "w1", history: tuple[str, ...] = (), typed: str = "",
          process: str | None = None, **extra) -> dict:
    lines = [PROMPT + command for command in history]
    return {"handle": handle, "worktreeId": worktree, "history": lines, "typed": typed, "process": process, **extra}


class StubOrca:
    """A stand-in for `orca ... --json` over a list of terminal records; it records every call it receives."""

    def __init__(self, terminals: list[dict], fail_reads: bool = False) -> None:
        self.terminals = terminals
        self.fail_reads = fail_reads
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *arguments: str) -> dict | None:
        self.calls.append(arguments)
        if arguments[:2] == ("terminal", "list"):
            listed = [{key: item[key] for key in ("handle", "worktreeId", "agentIdentity") if key in item}
                      for item in self.terminals]
            return {"ok": True, "result": {"terminals": listed}}
        found = next((item for item in self.terminals if item["handle"] == arguments[arguments.index("--terminal") + 1]),
                     None)
        if found is None or (arguments[:2] == ("terminal", "read") and self.fail_reads):
            return None
        if arguments[:2] == ("terminal", "close"):
            self.terminals = [item for item in self.terminals if item is not found]
            return {"ok": True, "result": {"closed": 1}}
        screen = "--screen" in arguments
        shown = [*found["history"]] if found["process"] else [*found["history"], PROMPT + found["typed"]]
        terminal = {"handle": found["handle"], "status": found.get("status", "running"), "source":
                    "screen" if screen else "stream", "tail": found.get("screen", shown) if screen else [
                        *found["history"], PROMPT + found["typed"]]}
        if found.get("draft"):
            terminal["draft"] = found["draft"]
        return {"ok": True, "result": {"terminal": terminal}}

    def closes(self) -> list[str]:
        return [call[call.index("--terminal") + 1] for call in self.calls if call[:2] == ("terminal", "close")]


class TailShapeTest(unittest.TestCase):
    def test_로그인_안내_줄이_앞에_붙은_출력이나_줄바꿈으로_이은_한_덩어리_글도_프롬프트뿐이면_쓴_적_없는_것으로_본다(self):
        """Orca가 출력을 목록이 아닌 글 하나로 주거나 셸이 `Last login` 줄을 먼저 찍어도 쓴 적 없는 셸이 열린 채 남지 않는다."""
        # Given
        banner = "Last login: Mon Nov 23 09:00:00 on ttys001"

        # When / Then
        self.assertTrue(orca_terminal_cleanup.only_prompts(f"{banner}\n{PROMPT}"))
        self.assertTrue(orca_terminal_cleanup.only_prompts([banner, PROMPT]))
        self.assertFalse(orca_terminal_cleanup.only_prompts([banner]))
        self.assertFalse(orca_terminal_cleanup.only_prompts(f"{banner}\n{PROMPT}ls"))


class CloseUnusedTest(unittest.TestCase):
    def close(self, *terminals: dict, **options) -> list[str]:
        stub = StubOrca(list(terminals), **options)
        self.assertEqual(orca_terminal_cleanup.close_unused(stub, OWN), stub.closes())
        return stub.closes()

    def test_쓴_적_없는_셸은_닫고_입력이_있거나_명령을_실행한_셸은_닫지_않는다(self):
        """빈 프롬프트 하나뿐인 셸만 닫히고 입력 중인 셸, 이전 명령이 보이는 셸, 프로세스가 도는 셸은 남는다."""
        # Given
        terminals = (agent(OWN), shell("empty"), shell("typed", typed="git sta"), shell("ran", history=("ls",)),
                     shell("busy", history=("sleep 100",), process="sleep 100"))

        # When
        closed = self.close(*terminals)

        # Then
        self.assertEqual(closed, ["empty"])

    def test_에이전트_터미널과_세션_자신의_터미널과_다른_워크트리의_터미널은_읽지도_닫지도_않는다(self):
        """agentIdentity가 있는 터미널, 자기 터미널, 다른 worktreeId의 쓴 적 없는 셸에는 읽기 호출조차 하지 않는다."""
        # Given
        stub = StubOrca([agent(OWN), agent("other_agent"), shell("elsewhere", worktree="w2")])

        # When
        closed = orca_terminal_cleanup.close_unused(stub, OWN)

        # Then
        self.assertEqual(closed, [])
        self.assertEqual([call[:2] for call in stub.calls], [("terminal", "list")])

    def test_자기_터미널이_목록에_없으면_아무것도_하지_않는다(self):
        """자기 워크트리를 확인할 수 없으면 쓴 적 없는 셸이 있어도 닫지 않는다."""
        # Given
        terminals = (shell("empty"),)

        # When
        closed = self.close(*terminals)

        # Then
        self.assertEqual(closed, [])

    def test_읽기에_실패하거나_초안이_있거나_실행_중이_아니면_닫지_않는다(self):
        """읽기 실패, 입력 초안, running이 아닌 상태는 모두 쓴 적 없는 셸로 보지 않는다."""
        # Given / When
        failed_read = self.close(agent(OWN), shell("empty"), fail_reads=True)
        with_draft = self.close(agent(OWN), shell("empty", draft="abc"))
        exited = self.close(agent(OWN), shell("empty", status="exited"))

        # Then
        self.assertEqual((failed_read, with_draft, exited), ([], [], []))

    def test_화면에_프롬프트_말고_다른_줄이_있으면_닫지_않는다(self):
        """출력은 프롬프트뿐이어도 화면에 다른 줄이 있으면 쓴 적 없는 셸이 아니다."""
        # Given
        crowded = shell("crowded", screen=["Last login: Mon", PROMPT])

        # When
        closed = self.close(agent(OWN), crowded)

        # Then
        self.assertEqual(closed, [])

    def test_프롬프트_모양_판정은_입력이_붙은_줄을_거른다(self):
        """% $ # > ❯로 끝나는 빈 입력줄만 프롬프트이고 글자가 붙은 줄, 빈 줄은 아니다."""
        # Given
        lines = {"user@host repo % ": True, "$": True, "~/repo ❯": True, "demo % ls": False, "demo % 5%": False,
                 "": False, "total 4": False}

        # When
        judged = {line: orca_terminal_cleanup.is_bare_prompt(line) for line in lines}

        # Then
        self.assertEqual(judged, lines)


class FirstPromptHookTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        task = json.loads((E2E_ROOT / "tasks/T34.json").read_text(encoding="utf-8"))
        self.repo = self.root / "work" / "repo"
        graders.materialize_fixture(task, E2E_ROOT / "fixtures", E2E_ROOT / "tasks", self.repo)
        self.work = self.repo.parent
        self.config = self.root / "config"
        self.config.mkdir()

    def environment(self, **extra: str | None) -> dict[str, str]:
        base = {key: value for key, value in os.environ.items() if not key.startswith(("ORCA_", "HEI5ENBUG_"))}
        base.update({
            "PATH": f"{self.work / 'fake-bin'}{os.pathsep}{os.environ['PATH']}", "ORCA_TERMINAL_HANDLE": "term_demo_a",
            "FAKE_ORCA_STATE": str(self.work / "orca-state" / "state.json"),
            "XDG_STATE_HOME": str(self.root / "state"), "CLAUDE_CONFIG_DIR": str(self.config),
        })
        base.update({key: value for key, value in extra.items() if value is not None})
        return {key: value for key, value in base.items() if extra.get(key, "") is not None}

    def submit(self, session: str | None = "s1", **extra: str | None) -> subprocess.CompletedProcess[str]:
        event = {"hook_event_name": "UserPromptSubmit", "prompt": "next", "cwd": str(self.repo)}
        if session is not None:
            event["session_id"] = session
        return subprocess.run([sys.executable, str(SCRIPTS / "orca_status_hook.py")], input=json.dumps(event),
                              capture_output=True, text=True, env=self.environment(**extra), cwd=self.repo, check=False)

    def handles(self) -> list[str]:
        state = json.loads((self.work / "orca-state" / "state.json").read_text(encoding="utf-8"))
        return [item["handle"] for item in state["terminals"]]

    def orca(self, *arguments: str) -> None:
        subprocess.run([str(self.work / "fake-bin" / "orca"), *arguments, "--json"], cwd=self.repo,
                       env=self.environment(), capture_output=True, text=True, check=True)

    def test_첫_프롬프트에서_쓴_적_없는_셸만_닫고_입력이_있는_셸과_자기_터미널은_둔다(self):
        """모델 턴 없이 훅이 term_shell_empty만 닫고, 출력은 없으며 입력 중인 셸에는 어떤 입력도 가지 않는다."""
        # Given
        before = self.handles()

        # When
        result = self.submit()

        # Then
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertEqual(before, ["term_demo_a", "term_shell_empty", "term_shell_typed"])
        self.assertEqual(self.handles(), ["term_demo_a", "term_shell_typed"])
        calls = [json.loads(line)["argv"][:2] for line in
                 (self.work / "orca-state" / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertNotIn(["terminal", "send"], calls)

    def test_같은_세션의_다음_프롬프트는_새로_생긴_쓴_적_없는_셸을_닫지_않는다(self):
        """첫 프롬프트에서만 닫으므로 두 번째 프롬프트는 오르카를 읽지도 않는다."""
        # Given
        self.submit()
        self.orca("terminal", "create", "--worktree", f"id:demo-a::{self.repo.resolve()}")
        calls_before = (self.work / "orca-state" / "calls.jsonl").read_text(encoding="utf-8").count("\n")

        # When
        self.submit()

        # Then
        self.assertIn("term_new_3", self.handles())
        self.assertEqual((self.work / "orca-state" / "calls.jsonl").read_text(encoding="utf-8").count("\n"),
                         calls_before)

    def test_다른_세션의_첫_프롬프트는_다시_정리한다(self):
        """세션마다 한 번이므로 새 세션 ID의 첫 프롬프트는 그때 있는 쓴 적 없는 셸을 닫는다."""
        # Given
        self.submit("s1")
        self.orca("terminal", "create", "--worktree", f"id:demo-a::{self.repo.resolve()}")

        # When
        self.submit("s2")

        # Then
        self.assertEqual(self.handles(), ["term_demo_a", "term_shell_typed"])

    def test_오르카_터미널_밖이거나_세션_ID가_없으면_아무것도_닫지_않는다(self):
        """ORCA_TERMINAL_HANDLE이 없거나 상태를 기억할 세션 ID가 없으면 터미널을 그대로 둔다."""
        # Given
        before = self.handles()

        # When
        outside = self.submit(ORCA_TERMINAL_HANDLE=None)
        anonymous = self.submit(session=None)

        # Then
        self.assertEqual((outside.returncode, anonymous.returncode), (0, 0))
        self.assertEqual(self.handles(), before)

    def test_하위_에이전트와_역할_세션에서는_닫지_않는다(self):
        """서브에이전트나 배정된 역할 세션은 자기 작업공간이 아니므로 정리하지 않는다."""
        # Given
        before = self.handles()

        # When
        result = self.submit(HEI5ENBUG_ASSIGNED_ROLE="worker")

        # Then
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.handles(), before)


if __name__ == "__main__":
    unittest.main()
