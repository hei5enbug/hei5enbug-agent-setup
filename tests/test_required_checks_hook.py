"""PreToolUse hook that reminds the agent to list required checks before a commit or push. It never blocks."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "required_checks_hook.py"
MESSAGE = (
    "Before a commit or push, the reply lists each check that the project instructions or a changed skill "
    "require for this change, such as an evaluation, a test run, or a final review, as done or as not done with "
    "its reason. A required check is never waived by judging the change small or reference-only, and a commit or "
    "push with a check not done waits until the user agrees after seeing that list."
)


def run_hook(stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT)], input=stdin, capture_output=True, text=True, check=False)


def bash_event(command: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


class RequiredChecksHookTest(unittest.TestCase):
    def assert_reminder(self, command: str) -> None:
        result = run_hook(bash_event(command))
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["hookSpecificOutput"]["additionalContext"], MESSAGE)

    def test_커밋과_푸시_명령은_필수_검사_목록_알림을_출력한다(self):
        # Given
        commands = ["git commit -m x", "git -C /tmp/work push origin main"]

        for command in commands:
            with self.subTest(command=command):
                # When / Then
                self.assert_reminder(command)

    def test_복합_명령_안의_커밋과_푸시도_알림을_출력한다(self):
        # Given
        commands = [
            "cd /tmp/work && git add -A && git commit -m x",
            "(git push)",
            "git status; git -c user.name=demo commit -m x",
            "echo done | git push origin main",
            "cd /tmp/work\ngit push origin main",
            "git -C '/tmp/work (copy)' push",
        ]

        for command in commands:
            with self.subTest(command=command):
                # When / Then
                self.assert_reminder(command)

    def test_커밋과_푸시가_아닌_입력은_출력_없이_정상_종료한다(self):
        # Given
        inputs = [
            bash_event("git status"),
            bash_event("git log --oneline"),
            bash_event("git log --grep commit"),
            bash_event("echo 'example; git push origin main'"),
            bash_event("ls"),
            json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/tmp/work/git-commit.md"}}),
            json.dumps({"tool_name": "Bash", "tool_input": {"command": 3}}),
            "git commit {not json",
            "",
        ]

        for stdin in inputs:
            with self.subTest(stdin=stdin):
                # When
                result = run_hook(stdin)

                # Then
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_출력은_차단이나_승인_결정_없는_PreToolUse_객체_하나다(self):
        # Given
        stdin = bash_event("git commit -m x")

        # When
        result = run_hook(stdin)

        # Then
        output = json.loads(result.stdout)
        self.assertEqual(list(output), ["hookSpecificOutput"])
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertNotIn("permissionDecision", output["hookSpecificOutput"])
        self.assertEqual(result.stdout.count("\n"), 1)


if __name__ == "__main__":
    unittest.main()
