"""Hook that writes nothing to Orca, keeps the session's tab title, and reminds it of a missing name or tab title."""

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
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "Stop")
        self.assertNotIn("decision", output)
        reason = output["hookSpecificOutput"]["additionalContext"]
        self.assertLessEqual(reason.count(". ") + 1, 2, reason)
        self.assertIn("end the turn without repeating the reply", reason)
        for needle in needles:
            self.assertIn(needle, reason)
        return reason


class TabTitleContextTest(HookCase):
    def rename(self, title: str, terminal: str = '"$ORCA_TERMINAL_HANDLE"', env: dict | None = None) -> None:
        command = f"orca terminal rename --terminal {terminal} --title {title} --json"
        shown = title.strip('"')
        output = json.dumps({"id": "req_1", "ok": True, "result": {"rename": {"handle": "term_test", "title": shown}}},
                            indent=2)
        self.tool_event("Bash", {"command": command}, {"stdout": output}, env)

    def context_of(self, output: dict | None) -> str | None:
        if output is None:
            return None
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        return output["hookSpecificOutput"]["additionalContext"]

    def test_탭_제목을_바꾼_세션은_다음_프롬프트마다_그_제목과_재설정_안내_한_줄을_받는다(self):
        # Regression: the session never sees the title it set, so it cannot tell that a new request is another task
        # Given
        self.rename('"ABC-1 login fix"')

        # When
        first = self.context_of(self.submit_prompt())
        second = self.context_of(self.submit_prompt())

        # Then
        self.assertEqual(first, second)
        self.assertEqual(len(first.splitlines()), 1)
        self.assertIn("Current Orca tab title: ABC-1 login fix.", first)
        self.assertIn("retitle the tab", first)
        self.assertNotIn("worktree comment", first)
        self.assertIn("as does one the user set", first)

    def test_탭_제목을_바꾼_적이_없으면_프롬프트에_아무것도_더하지_않는다(self):
        # Regression: a session without a title gets a line that names nothing, on top of the missing-title reminder
        # Given
        self.tool_event("Bash", {"command": SET_NAME}, {"stdout": "{}"})

        # When
        output = self.submit_prompt()

        # Then
        self.assertIsNone(output)

    def test_제목을_다시_바꾸면_새_제목으로_바뀌고_첫_제목은_남지_않는다(self):
        # Regression: the line keeps the first task's title after the session retitled the tab
        # Given
        self.rename('"ABC-1 login fix"')
        self.rename('"ABC-2 report export"')

        # When
        context = self.context_of(self.submit_prompt())

        # Then
        self.assertIn("Current Orca tab title: ABC-2 report export.", context)
        self.assertNotIn("ABC-1", context)

    def test_다른_터미널의_이름_변경은_기록하지_않고_이전_제목을_그대로_둔다(self):
        # Regression: a rename of another tab replaces this session's title, or creates one it never set
        # Given
        self.rename('"ABC-9 other tab"', terminal="term_other")

        # When
        before = self.submit_prompt()
        self.rename('"ABC-1 login fix"')
        self.rename('"ABC-9 other tab"', terminal="term_other")
        after = self.context_of(self.submit_prompt())

        # Then
        self.assertIsNone(before)
        self.assertIn("ABC-1 login fix", after)
        self.assertNotIn("ABC-9", after)

    def test_이_세션의_터미널_핸들을_값으로_직접_써도_기록한다(self):
        # Regression: a command that spells out the handle instead of the variable is missed
        # Given
        self.rename('"ABC-3 literal handle"', terminal="term_test")

        # When
        context = self.context_of(self.submit_prompt())

        # Then
        self.assertIn("Current Orca tab title: ABC-3 literal handle.", context)

    def test_글자_그대로_읽을_수_없는_제목은_기록하지_않고_이전_제목을_그대로_둔다(self):
        # Regression: a shell variable or command substitution is stored as a title, or erases the earlier one
        # Given
        self.rename('"ABC-1 login fix"')

        # When
        for title in ('"$NEW_TITLE"', '"ABC-2 $(git branch --show-current)"', '"ABC-2 `date`"', "$(date)"):
            with self.subTest(title=title):
                self.rename(title)
                context = self.context_of(self.submit_prompt())

                # Then
                self.assertIn("Current Orca tab title: ABC-1 login fix.", context)

    def test_실행되지_않은_이름_변경은_성공한_명령_안에_있어도_기록하지_않는다(self):
        # Regression: `true || orca terminal rename ...` succeeds without renaming, yet its title is reported as current
        # Given
        command = 'true || orca terminal rename --terminal "$ORCA_TERMINAL_HANDLE" --title "ABC-2 export" --json'

        # When
        self.tool_event("Bash", {"command": command}, {"stdout": ""})
        before = self.submit_prompt()
        self.tool_event("Bash", {"command": command}, {"stdout": '{"ok": true, "result": {"rename": {"title": "ABC-9 other"}}}'})
        mismatched = self.submit_prompt()

        # Then
        self.assertIsNone(before)
        self.assertIsNone(mismatched)

    def test_오르카_터미널_밖이면_제목을_기록하지도_알리지도_않는다(self):
        # Regression: the line appears in sessions with no Orca tab
        # Given
        outside = {"ORCA_TERMINAL_HANDLE": None}
        self.rename('"ABC-1 login fix"', env=outside)

        # When
        before = self.submit_prompt()
        self.rename('"ABC-2 recorded inside"')
        after = self.submit_prompt(outside)

        # Then
        self.assertIsNone(before)
        self.assertIsNone(after)


class NoOrcaWriteTest(HookCase):
    def events(self):
        yield "pull request", lambda env, **extra: self.tool_event("Bash", {"command": PULL_REQUEST}, {"stdout": PR_URL}, env, **extra)
        yield "edit", lambda env, **extra: self.tool_event("Edit", {"file_path": f"{WORKTREE}/a.py"}, None, env, **extra)
        yield "commit", lambda env, **extra: self.tool_event("Bash", {"command": "git commit -m x"}, None, env, **extra)

    def test_풀리퀘스트_생성_완료_상태_워크트리의_편집_질문으로_끝난_턴은_오르카_설정을_호출하지_않는다(self):
        # Regression: the hook wrote stale board statuses, comments, and unread flags into Orca
        # Given
        self.set_orca(worktree_json(status="completed", comment="구현 중"))
        self.write(prompt(), assistant(edit(f"{WORKTREE}/a.py"), text("Shall I push?")))

        # When
        for _, run in self.events():
            run({})
        self.stop()
        self.submit_prompt()

        # Then
        self.assertEqual(self.writes(), [])
        self.assertEqual([call for call in self.calls() if not call.startswith("worktree current")], [])

    def test_이름_변경_뒤_다음_프롬프트는_탭_제목_줄을_받고_그_줄에_워크트리_코멘트가_없다(self):
        # Regression: the tab title line asks the session to refresh a worktree comment that is no longer written
        # Given
        command = 'orca terminal rename --terminal "$ORCA_TERMINAL_HANDLE" --title "ABC-123 demo" --json'
        output = json.dumps({"ok": True, "result": {"rename": {"handle": "term_test", "title": "ABC-123 demo"}}})
        self.tool_event("Bash", {"command": command}, {"stdout": output})

        # When
        context = self.submit_prompt()["hookSpecificOutput"]["additionalContext"]

        # Then
        self.assertIn("Current Orca tab title: ABC-123 demo.", context)
        self.assertIn("retitle the tab", context)
        self.assertNotIn("worktree comment", context)
        self.assertEqual(self.writes(), [])

    def test_오르카_밖이거나_서브에이전트이면_아무것도_하지_않는다(self):
        # Regression: noise outside Orca or in a subagent
        # Given
        self.set_orca(worktree_json(status="completed"))
        cases = {
            "outside Orca": ({"ORCA_TERMINAL_HANDLE": None}, {}),
            "assigned role": ({"HEI5ENBUG_ASSIGNED_ROLE": "worker"}, {}),
            "subagent": ({}, {"agent_id": "agent-1"}),
        }
        for name, (env, extra) in cases.items():
            for kind, run in self.events():
                with self.subTest(name=name, kind=kind):
                    self.state_reset()
                    self.log.unlink(missing_ok=True)

                    # When
                    run(env, **extra)

                    # Then
                    self.assertEqual(self.calls(), [])

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
        self.write(prompt(), assistant(bash(SET_NAME)), prompt("n"), assistant(text("fine.")))

        # When
        output = self.stop()

        # Then
        self.assert_blocks(output, 'orca terminal rename --terminal "$ORCA_TERMINAL_HANDLE"')
        self.assertIsNone(self.stop())

    def test_제목을_바꿨거나_설정을_한_적이_없으면_제목_규칙은_발동하지_않는다(self):
        # Regression: reminding a session that already titled its tab, or one that never touched Orca
        cases = {
            "renamed": [prompt(), assistant(bash(SET_NAME), bash(RENAME)), prompt("n"), assistant(text("ok."))],
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
        for command in ('echo "git commit"', "gh pr view 1", "git status", "orca worktree current --json"):
            with self.subTest(command=command):
                turn = self.signals(command)
                self.assertFalse(turn.commit or turn.set_any or turn.rename)


if __name__ == "__main__":
    unittest.main()
