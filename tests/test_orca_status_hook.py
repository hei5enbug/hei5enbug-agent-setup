"""Hook that writes Orca status text for the session's events and reminds it of a missing name or tab title."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = SCRIPTS / "orca_status_hook.py"
sys.path.insert(0, str(SCRIPTS))
import orca_status_hook  # noqa: E402

WORKTREE = "/home/test/work/abc-123-api"
PULL_REQUEST = "gh pr create --title t --body b"
PR_URL = "https://example.com/org/repo/pull/7"
SET_STATUS = 'orca worktree set --worktree active --workspace-status in-review --comment "waits for review" --json'
SET_NAME = 'orca worktree set --worktree active --display-name "ABC-123 api" --json'
RENAME = 'orca terminal rename --terminal "$ORCA_TERMINAL_HANDLE" --title "ABC-123 api" --json'


def worktree_json(path: str = WORKTREE, main: bool = False, mode: str = "automatic", status: str | None = None,
                  comment: str = "") -> str:
    record = {
        "id": f"repo-id::{path}", "path": path, "isMainWorktree": main, "displayName": "abc-123-api",
        "displayNameMode": mode, "workspaceStatus": status, "comment": comment,
    }
    return json.dumps({"ok": True, "result": {"worktree": record}})


def entry(kind: str, message: dict, **extra) -> str:
    return json.dumps({"type": kind, "isSidechain": False, "message": message, **extra}, separators=(",", ":"))


def prompt(text: str = "do the task") -> str:
    return entry("user", {"role": "user", "content": text})


def tool_result() -> str:
    block = {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}
    return entry("user", {"role": "user", "content": [block]})


def assistant(*blocks: dict, message_id: str = "m1") -> str:
    return entry("assistant", {"id": message_id, "role": "assistant", "content": list(blocks)})


def text(value: str) -> dict:
    return {"type": "text", "text": value}


def bash(command: str) -> dict:
    return {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": command}}


def tool(name: str, **tool_input) -> dict:
    return {"type": "tool_use", "id": "t1", "name": name, "input": tool_input}


def edit(path: str) -> dict:
    return tool("Edit", file_path=path, old_string="a", new_string="b")


class HookCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.transcript = self.root / "session.jsonl"
        self.state = self.root / "state"
        self.config = self.root / "config"
        self.config.mkdir()
        self.log = self.root / "orca.log"
        self.set_orca(worktree_json())

    def set_orca(self, current: str | None) -> None:
        program = self.bin / "orca"
        if current is None:
            program.write_text("#!/bin/sh\nexit 1\n")
        else:
            (self.root / "orca.json").write_text(current)
            program.write_text(
                f"#!/bin/sh\necho \"$@\" >> '{self.log}'\n"
                f"case \"$1 $2\" in 'worktree current') cat '{self.root / 'orca.json'}';; *) echo '{{\"ok\":true}}';; esac\n"
            )
        program.chmod(program.stat().st_mode | stat.S_IXUSR)

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def writes(self) -> list[str]:
        return [line for line in self.calls() if line.startswith("worktree set")]

    def reads(self) -> list[str]:
        return [line for line in self.calls() if line.startswith("worktree current")]

    def write(self, *lines: str) -> None:
        self.transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def state_reset(self) -> None:
        for path in self.state.rglob("*.json"):
            path.unlink()

    def run_event(self, event: dict, env: dict | None = None) -> dict | None:
        payload = {"session_id": "s1", "cwd": WORKTREE, **event}
        environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("ORCA_", "HEI5ENBUG_", "CLAUDE_PLUGIN_OPTION_")) and key != "PLUGIN_ROOT"
        }
        environment.update({
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "XDG_STATE_HOME": str(self.state),
            "CLAUDE_CONFIG_DIR": str(self.config), "ORCA_TERMINAL_HANDLE": "term_test",
        })
        environment.update(env or {})
        environment = {key: value for key, value in environment.items() if value is not None}
        result = subprocess.run(
            [sys.executable, str(SCRIPT)], input=json.dumps(payload), capture_output=True, text=True, env=environment,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout else None

    def stop(self, env: dict | None = None, **event) -> dict | None:
        return self.run_event(
            {"hook_event_name": "Stop", "transcript_path": str(self.transcript), **event}, env
        )

    def tool_event(self, name: str, tool_input: dict, response: dict | None = None, env: dict | None = None,
                   **event) -> dict | None:
        payload = {"hook_event_name": "PostToolUse", "tool_name": name, "tool_input": tool_input,
                   "tool_use_id": "toolu_1", "tool_response": response or {}, **event}
        return self.run_event(payload, env)

    def submit_prompt(self, env: dict | None = None, **event) -> dict | None:
        return self.run_event({"hook_event_name": "UserPromptSubmit", "prompt": "next", **event}, env)

    def assert_blocks(self, output: dict | None, *needles: str) -> str:
        self.assertIsNotNone(output)
        self.assertEqual(output["decision"], "block")
        reason = output["reason"]
        self.assertLessEqual(reason.count(". ") + 1, 2, reason)
        self.assertIn("end the turn without repeating the reply", reason)
        for needle in needles:
            self.assertIn(needle, reason)
        return reason


class ReviewWriteTest(HookCase):
    def test_풀리퀘스트를_만들면_모델_없이_in_review와_링크_코멘트를_한_번_쓴다(self):
        # Regression: a pull request left the board on in-progress with a stale comment
        # Given
        event = {"command": PULL_REQUEST}
        response = {"stdout": f"Creating pull request\n{PR_URL}\n"}

        # When
        output = self.tool_event("Bash", event, response)
        self.tool_event("Bash", event, response)

        # Then
        self.assertIsNone(output)
        self.assertEqual(
            self.writes(),
            [f"worktree set --worktree id:repo-id::{WORKTREE} --workspace-status in-review "
             f"--comment Waiting for review: {PR_URL} --json"],
        )

    def test_다른_저장소_도구의_요청_생성도_쓰고_다른_명령은_쓰지_않는다(self):
        # Regression: a creator missing from the list, or an unrelated command counted as a request
        creators = ["az repos pr create --title t", "cd /tmp/work && glab mr create --fill"]
        others = ["gh pr view 1", 'echo "gh pr create"', "git status", "git push"]
        for command in creators:
            with self.subTest(command=command):
                self.state_reset()
                self.log.unlink(missing_ok=True)
                self.tool_event("Bash", {"command": command}, {"stdout": PR_URL})
                self.assertEqual(len(self.writes()), 1)
        for command in others:
            with self.subTest(command=command):
                self.state_reset()
                self.log.unlink(missing_ok=True)
                self.tool_event("Bash", {"command": command}, {"stdout": PR_URL})
                self.assertEqual(self.writes(), [])

    def test_사용자_정의_보드는_상태를_바꾸지_않고_코멘트만_쓴다(self):
        # Regression: a customized board status id overwritten
        # Given
        self.set_orca(worktree_json(status="qa"))

        # When
        self.tool_event("Bash", {"command": PULL_REQUEST}, {"stdout": PR_URL})

        # Then
        self.assertEqual(
            self.writes(), [f"worktree set --worktree id:repo-id::{WORKTREE} --comment Waiting for review: {PR_URL} --json"]
        )

    def test_도움말과_드라이런과_생성_결과가_없는_출력은_아무것도_쓰지_않는다(self):
        # Regression: a successful `gh pr create --help`, or any output without the created request, set in-review
        cases = [
            ("gh pr create --help", {"stdout": f"Usage: gh pr create\nSee {PR_URL}"}),
            ("gh pr create -h", {"stdout": PR_URL}),
            ("gh pr create --dry-run", {"stdout": PR_URL}),
            (PULL_REQUEST, {"stdout": "created"}),
            (PULL_REQUEST, {"stdout": "https://example.com/docs/pull-requests"}),
            ("az repos pr create --title t", {"stdout": '{"status": "active"}'}),
            (PULL_REQUEST, {}),
        ]
        for command, response in cases:
            with self.subTest(command=command, response=response):
                self.state_reset()
                self.log.unlink(missing_ok=True)
                self.tool_event("Bash", {"command": command}, response)
                self.assertEqual(self.writes(), [])

    def test_azure_출력의_풀리퀘스트_번호도_생성_결과로_본다(self):
        # Regression: an Azure DevOps request, which prints JSON and no URL line, never reached in-review
        # Given
        output = json.dumps({"pullRequestId": 12, "repository": {"webUrl": "https://example.com/p/_git/r"}})

        # When
        self.tool_event("Bash", {"command": "az repos pr create --title t"}, {"stdout": output})

        # Then
        self.assertEqual(
            self.writes(),
            [f"worktree set --worktree id:repo-id::{WORKTREE} --workspace-status in-review "
             "--comment Waiting for review: https://example.com/p/_git/r/pullrequest/12 --json"],
        )


class QuestionWriteTest(HookCase):
    def test_질문으로_끝난_턴은_읽지_않음과_대기_코멘트를_이전_코멘트_앞에_쓴다(self):
        # Regression: a worktree waiting on the user kept the old comment and no unread mark
        # Given
        self.set_orca(worktree_json(comment="구현 중"))
        self.write(prompt(), assistant(text("정리했습니다.\n\n어느 쪽으로 진행할까요?")))

        # When
        output = self.stop()

        # Then
        self.assertIsNone(output)
        self.assertEqual(
            self.writes(),
            [f"worktree set --worktree id:repo-id::{WORKTREE} --comment Waiting for you: 어느 쪽으로 진행할까요? · 구현 중 --unread --json"],
        )

    def test_마지막_질문_줄을_80자로_줄여_쓰고_두_번째_멈춤은_쓰지_않는다(self):
        # Regression: a long question overflows the comment, or the same question is written at every stop
        # Given
        long_question = "Which of the three rollout orders should we use for the database migration, the API, and the web app?"
        self.write(prompt(), assistant(text(long_question)))

        # When
        self.stop()
        self.stop()

        # Then
        self.assertEqual(len(self.writes()), 1)
        comment = self.writes()[0].split("--comment ", 1)[1].rsplit(" --unread", 1)[0]
        self.assertTrue(comment.startswith("Waiting for you: Which of the three rollout orders"))
        self.assertLessEqual(len(comment.removeprefix("Waiting for you: ")), 80)
        self.assertTrue(comment.endswith("…"))

    def test_같은_턴에_답을_받은_선택_질문은_대기_코멘트를_쓰지_않고_마지막_질문_줄은_쓴다(self):
        # Regression: an AskUserQuestion answered inside the turn left a waiting comment on a worktree that kept working
        # Given
        answered = [
            prompt(),
            assistant(tool("AskUserQuestion", questions=[{"question": "Which order?"}])),
            tool_result(),
            assistant(text("Applied the first order.")),
        ]
        self.write(*answered)

        # When
        self.stop()

        # Then
        self.assertEqual(self.writes(), [])

        # When: the same turn ends with a question line
        self.write(*answered[:-1], assistant(text("Applied it.\n\nShall I push?")))
        self.stop()

        # Then
        self.assertIn("--comment Waiting for you: Shall I push? --unread", self.writes()[0])

    def test_한국어_언어_설정이면_한국어_라벨을_쓴다(self):
        # Regression: labels ignore the Claude Code language setting
        # Given
        (self.config / "settings.json").write_text(json.dumps({"language": "Korean"}))
        self.write(prompt(), assistant(text("계속할까요?")))

        # When
        self.stop()

        # Then
        self.assertIn("--comment 답변 대기: 계속할까요?", self.writes()[0])

    def test_턴에_오르카_설정을_했거나_질문이_아니거나_이미_이어지는_중이면_쓰지_않는다(self):
        # Regression: overwriting the session's own update, noise on plain answers, and a write after a reminder
        cases = {
            "own set in the turn": ([prompt(), assistant(bash(SET_STATUS), text("Ready to continue?"))], {}),
            "plain answer": ([prompt(), assistant(text("done."))], {}),
            "already continuing": ([prompt(), assistant(text("Continue?"))], {"stop_hook_active": True}),
        }
        for name, (lines, options) in cases.items():
            with self.subTest(name=name):
                self.log.unlink(missing_ok=True)
                self.state_reset()
                self.write(*lines)
                self.stop(**options)
                self.assertEqual(self.writes(), [])

    def test_다음_프롬프트는_훅이_쓴_코멘트일_때만_이전_코멘트로_되돌린다(self):
        # Regression: the waiting label stays after the user answers, or the restore overwrites a newer comment
        # Given
        self.set_orca(worktree_json(comment="구현 중"))
        self.write(prompt(), assistant(text("Continue?")))
        self.stop()
        written = self.writes()[0].split("--comment ", 1)[1].rsplit(" --unread", 1)[0]
        self.log.unlink()

        # When: the comment is still the hook's own
        self.set_orca(worktree_json(comment=written))
        self.submit_prompt()

        # Then
        self.assertEqual(self.writes(), [f"worktree set --worktree id:repo-id::{WORKTREE} --comment 구현 중 --json"])

        # When: a later prompt finds nothing left to restore
        self.log.unlink()
        self.submit_prompt()

        # Then
        self.assertEqual(self.writes(), [])

    def test_코멘트가_그사이_바뀌었으면_덮어쓰지_않고_기억만_지운다(self):
        # Regression: restoring over a comment the session wrote after the question
        # Given
        self.write(prompt(), assistant(text("Continue?")))
        self.stop()
        self.log.unlink()
        self.set_orca(worktree_json(comment="리뷰 대기: https://example.com/pr/1"))

        # When
        self.submit_prompt()
        self.set_orca(worktree_json(comment="Waiting for you: Continue?"))
        self.submit_prompt()

        # Then
        self.assertEqual(self.writes(), [])


class ResumeWriteTest(HookCase):
    def test_완료나_할일이거나_상태가_없는_워크트리의_편집과_커밋은_진행중으로_바꾼다(self):
        # Regression: work resumed on a completed card that kept saying done
        for status in ("completed", "todo", None):
            with self.subTest(status=status):
                self.state_reset()
                self.log.unlink(missing_ok=True)
                self.set_orca(worktree_json(status=status))

                # When
                self.tool_event("Edit", {"file_path": f"{WORKTREE}/src/app.py"})

                # Then
                self.assertEqual(self.writes(), [f"worktree set --worktree id:repo-id::{WORKTREE} --workspace-status in-progress --json"])
        self.state_reset()
        self.log.unlink()
        self.tool_event("Bash", {"command": "git commit -m work"})
        self.assertEqual(len(self.writes()), 1)

    def test_진행중이거나_검토중이거나_밖의_파일이거나_사용자_정의_상태면_쓰지_않는다(self):
        # Regression: flipping a review or customized status, or a scratch edit reopening finished work
        cases = {
            "in-progress": (worktree_json(status="in-progress"), f"{WORKTREE}/a.py"),
            "in-review": (worktree_json(status="in-review"), f"{WORKTREE}/a.py"),
            "customized": (worktree_json(status="qa"), f"{WORKTREE}/a.py"),
            "outside": (worktree_json(status="completed"), "/tmp/scratch/a.py"),
        }
        for name, (record, path) in cases.items():
            with self.subTest(name=name):
                self.state_reset()
                self.log.unlink(missing_ok=True)
                self.set_orca(record)
                self.tool_event("Edit", {"file_path": path})
                self.assertEqual(self.writes(), [])

    def test_다른_체크아웃의_커밋은_이_카드를_다시_열지_않고_이_워크트리의_커밋은_연다(self):
        # Regression: `git -C /other commit` or a `cd /other &&` commit reopened this worktree's completed card
        # Given
        self.set_orca(worktree_json(status="completed"))
        elsewhere = ["git -C /home/test/other commit -m x", "cd /home/test/other && git commit -m x", "cd $DIR && git commit"]
        here = ["git commit -m x", f"git -C {WORKTREE} commit -m x", f"cd {WORKTREE}/sub && git commit -m x"]

        # When / Then
        for command in elsewhere:
            with self.subTest(command=command):
                self.state_reset()
                self.log.unlink(missing_ok=True)
                self.tool_event("Bash", {"command": command})
                self.assertEqual(self.writes(), [])
        for command in here:
            with self.subTest(command=command):
                self.state_reset()
                self.log.unlink(missing_ok=True)
                self.tool_event("Bash", {"command": command})
                self.assertEqual(len(self.writes()), 1)

    def test_밖의_파일을_고친_뒤에도_바로_이어진_이_저장소_편집은_카드를_다시_연다(self):
        # Regression: a scratch edit cached the check and hid the next real resume for 60 seconds
        # Given
        self.set_orca(worktree_json(status="completed"))

        # When
        self.tool_event("Edit", {"file_path": "/tmp/scratch/a.py"})
        self.tool_event("Edit", {"file_path": f"{WORKTREE}/src/app.py"})

        # Then
        self.assertEqual(
            self.writes(), [f"worktree set --worktree id:repo-id::{WORKTREE} --workspace-status in-progress --json"]
        )

    def test_상태를_확인한_뒤_잠시_동안은_오르카를_다시_읽지_않는다(self):
        # Regression: reading Orca after every edit slows each tool call
        # Given
        self.set_orca(worktree_json(status="completed"))

        # When
        for index in range(3):
            self.tool_event("Edit", {"file_path": f"{WORKTREE}/f{index}.py"})

        # Then
        self.assertEqual(len(self.reads()), 1)
        self.assertEqual(len(self.writes()), 1)


class NoWriteTest(HookCase):
    def events(self):
        yield "pull request", lambda env, **extra: self.tool_event("Bash", {"command": PULL_REQUEST}, {"stdout": PR_URL}, env, **extra)
        yield "edit", lambda env, **extra: self.tool_event("Edit", {"file_path": f"{WORKTREE}/a.py"}, None, env, **extra)

    def test_오르카_밖이거나_서브에이전트이거나_토글이_꺼지면_아무것도_쓰지_않는다(self):
        # Regression: noise outside Orca, in a subagent, or after the user turned the writes off
        self.set_orca(worktree_json(status="completed"))
        cases = {
            "outside Orca": ({"ORCA_TERMINAL_HANDLE": None}, {}),
            "assigned role": ({"HEI5ENBUG_ASSIGNED_ROLE": "worker"}, {}),
            "toggle off": ({"CLAUDE_PLUGIN_OPTION_ORCA_STATUS_WRITES": "false"}, {}),
            "subagent": ({}, {"agent_id": "agent-1"}),
        }
        for name, (env, extra) in cases.items():
            for kind, run in self.events():
                with self.subTest(name=name, kind=kind):
                    self.state_reset()
                    self.log.unlink(missing_ok=True)
                    run(env, **extra)
                    self.assertEqual(self.writes(), [])

    def test_토글이_꺼져도_질문과_프롬프트는_쓰지_않고_이름_알림은_계속한다(self):
        # Regression: the toggle silences the name reminder, or leaves question writes running
        # Given
        env = {"CLAUDE_PLUGIN_OPTION_ORCA_STATUS_WRITES": "false"}
        self.write(prompt(), assistant(edit(f"{WORKTREE}/a.py"), text("Continue?")))

        # When
        output = self.stop(env)
        self.submit_prompt(env)

        # Then
        self.assertEqual(self.writes(), [])
        self.assert_blocks(output, "--display-name")

    def test_오르카를_읽지_못하면_조용히_통과한다(self):
        # Regression: an Orca failure breaks the tool call or blocks the stop
        # Given
        self.set_orca(None)
        self.write(prompt(), assistant(edit(f"{WORKTREE}/a.py"), text("Continue?")))

        # When / Then
        self.assertIsNone(self.tool_event("Bash", {"command": PULL_REQUEST}, {"stdout": PR_URL}))
        self.assertIsNone(self.tool_event("Edit", {"file_path": f"{WORKTREE}/a.py"}))
        self.assertIsNone(self.submit_prompt())
        self.assertIsNone(self.stop())


class NameAndTitleRuleTest(HookCase):
    def test_파일을_고친_작업_워크트리가_자동_이름이면_이름을_지으라고_막는다(self):
        # Regression: child worktrees stay named by their branch
        # Given
        self.write(prompt(), assistant(edit(f"{WORKTREE}/src/app.py")), tool_result(), assistant(text("done.")))

        # When
        output = self.stop()

        # Then
        reason = self.assert_blocks(output, "--display-name", f"id:repo-id::{WORKTREE}", "orca terminal rename")
        self.assertIn("automatic name", reason)

    def test_이름_규칙은_조건이_아니거나_이어지는_중이거나_하위_세션이면_발동하지_않는다(self):
        # Regression: renaming the shared main clone, a user's name, or an untouched worktree, and reminder loops
        edited = [prompt(), assistant(edit(f"{WORKTREE}/a.py"))]
        cases = {
            "main clone": (worktree_json(main=True), edited, {}),
            "user-set name": (worktree_json(mode="manual"), edited, {}),
            "edit outside the worktree": (worktree_json(), [prompt(), assistant(edit("/tmp/scratch/a.py"))], {}),
            "no change": (worktree_json(), [prompt(), assistant(bash("git status"))], {}),
            "already continuing": (worktree_json(), edited, {"stop_hook_active": True}),
            "subagent": (worktree_json(), edited, {"agent_id": "agent-1"}),
            "outside Orca": (worktree_json(), edited, {"env": {"ORCA_TERMINAL_HANDLE": None}}),
        }
        for name, (record, lines, options) in cases.items():
            with self.subTest(name=name):
                self.state_reset()
                self.set_orca(record)
                self.write(*lines)
                self.assertIsNone(self.stop(**options))

    def test_커밋도_변경으로_보고_한_번만_막는다(self):
        # Regression: a committed-only session is never named, and a second stop repeats the cost
        # Given
        self.write(prompt(), assistant(bash("git commit -m work")))
        self.assert_blocks(self.stop(), "--display-name")

        # When / Then
        self.assertIsNone(self.stop())

    def test_이름이_이미_정해진_것을_확인하면_이후_멈춤에서_오르카를_다시_읽지_않는다(self):
        # Regression: reading Orca at every stop of a named session
        # Given
        self.set_orca(worktree_json(mode="manual"))
        self.write(prompt(), assistant(edit(f"{WORKTREE}/a.py")))
        self.assertIsNone(self.stop())
        self.log.unlink()

        # When
        self.write(prompt(), assistant(edit(f"{WORKTREE}/a.py")), prompt("n"), assistant(edit(f"{WORKTREE}/b.py")))

        # Then
        self.assertIsNone(self.stop())
        self.assertEqual(self.reads(), [])

    def test_설정을_실행했는데_탭_제목을_한_번도_안_바꿨으면_제목을_바꾸라고_막는다(self):
        # Regression: six tabs named only by a path stub
        # Given
        self.set_orca(worktree_json(main=True))
        self.write(prompt(), assistant(bash(SET_STATUS)), prompt("n"), assistant(text("fine.")))

        # When
        output = self.stop()

        # Then
        self.assert_blocks(output, 'orca terminal rename --terminal "$ORCA_TERMINAL_HANDLE"')
        self.assertIsNone(self.stop())

    def test_제목을_바꿨거나_설정을_한_적이_없으면_제목_규칙은_발동하지_않는다(self):
        # Regression: reminding a session that already titled its tab, or one that never touched Orca
        cases = {
            "renamed": [prompt(), assistant(bash(SET_STATUS), bash(RENAME)), prompt("n"), assistant(text("ok."))],
            "never set": [prompt(), assistant(text("ok."))],
        }
        for name, lines in cases.items():
            with self.subTest(name=name):
                self.state_reset()
                self.write(*lines)
                self.assertIsNone(self.stop())

    def test_이름_안내가_제목_명령을_함께_주면_다음_멈춤에서_제목_규칙은_다시_막지_않는다(self):
        # Regression: two blocks in a row for what one command line can say
        # Given
        self.write(prompt(), assistant(edit(f"{WORKTREE}/a.py")))
        self.assert_blocks(self.stop(), "orca terminal rename")

        # When
        self.write(prompt(), assistant(edit(f"{WORKTREE}/a.py"), bash(SET_NAME)), prompt("n"), assistant(text("ok.")))

        # Then
        self.assertIsNone(self.stop())

    def test_오르카를_읽지_못하거나_기록을_읽지_못하면_통과한다(self):
        # Regression: a failed read turns into a blocked stop the agent cannot resolve
        # Given
        self.write(prompt(), assistant(edit(f"{WORKTREE}/a.py")))
        self.set_orca(None)

        # When / Then
        self.assertIsNone(self.stop())
        self.transcript.write_text('{"type":"response_item","payload":{"type":"message"}}\nnot json\n')
        self.set_orca(worktree_json())
        self.assertIsNone(self.stop())
        self.assertIsNone(self.stop(transcript_path=str(self.root / "missing.jsonl")))


class SignalDetectionTest(unittest.TestCase):
    def signals(self, command: str) -> orca_status_hook.Turn:
        turn = orca_status_hook.Turn()
        orca_status_hook.command_signals(command, turn)
        return turn

    def test_명령_안의_오르카와_깃_동작을_구분한다(self):
        # Regression: a quoted or unrelated command counted as an event
        self.assertTrue(self.signals("git commit -m x").commit)
        self.assertTrue(self.signals("orca terminal rename --terminal t --title x").rename)
        named = self.signals("orca worktree set --worktree active --display-name x")
        self.assertTrue(named.set_any and named.named)
        self.assertFalse(self.signals("orca worktree set --worktree active --comment x").named)
        for command in ('echo "gh pr create"', "gh pr view 1", "git status", "orca worktree current --json"):
            with self.subTest(command=command):
                turn = self.signals(command)
                self.assertFalse(turn.pull_request or turn.commit or turn.set_any or turn.rename)


if __name__ == "__main__":
    unittest.main()
