"""PreToolUse hook that denies a command creating a top-level Orca worktree."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "orca_placement_hook.py"
REASON = (
    "Blocked: this command creates a top-level Orca worktree. Put a new worktree under an existing workspace so "
    "every worktree of one ticket stays in one group: use `--parent-worktree active` in this repository, "
    "`--parent-worktree id:<repoId>::<clone path>` for another repository's workspace, or the group root's id for a "
    "task that changes several repositories; with orchestration, use `--worktree new-child` or an existing "
    "worktree. Only when Orca lists no workspace for the repository, or the user asked for a top-level worktree in "
    "this conversation, create it with a parent and then run `orca worktree set --worktree <id> --no-parent "
    "--json`."
)


def run_hook(stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT)], input=stdin, capture_output=True, text=True, check=False)


def bash_event(command: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


class OrcaPlacementHookTest(unittest.TestCase):
    def assert_denied(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(
            output,
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": REASON,
                }
            },
        )

    def test_복합_명령_안의_부모_없는_워크트리_생성을_차단한다(self):
        # Given
        command = (
            "S=/tmp/work; orca worktree create --repo id:demo-repo --name abc-123-api --branch feature/ABC-123 "
            '--base-branch upstream/main --no-parent --comment "ABC-123 demo" --json > $S/wt.json 2>&1; '
            'python3 -c "print(1)"'
        )

        # When
        result = run_hook(bash_event(command))

        # Then
        self.assert_denied(result)

    def test_오케스트레이션의_최상위_워크트리_시작도_차단한다(self):
        # Given
        commands = [
            "orca orchestration worker-start --spec-file s.md --worktree new-top-level --agent claude --json",
            "orca orchestration worker-start --spec-file s.md --worktree=new-top-level --agent claude --json",
        ]

        for command in commands:
            with self.subTest(command=command):
                # When
                result = run_hook(bash_event(command))

                # Then
                self.assert_denied(result)

    def test_명령_치환_안에서_실행되는_부모_없는_워크트리_생성도_차단한다(self):
        # Given
        commands = [
            'result="$(orca worktree create --repo id:demo-repo --name demo --base-branch main --no-parent --json)"',
            "cat > /tmp/work/brief.md <<EOF\nRun `orca worktree create --repo id:demo-repo --name x --no-parent`\nEOF",
        ]

        for command in commands:
            with self.subTest(command=command):
                # When
                result = run_hook(bash_event(command))

                # Then
                self.assert_denied(result)

    def test_허용된_명령과_따옴표_속_글과_잘못된_입력은_출력_없이_정상_종료한다(self):
        # Given
        inputs = [
            bash_event("orca worktree create --repo id:demo-repo --name x --parent-worktree active --json"),
            bash_event("orca worktree set --worktree id:demo-repo::/tmp/work --no-parent --json"),
            bash_event('echo "orca worktree create --no-parent"'),
            bash_event("cat > /tmp/work/note.md <<'EOF'\norca worktree create --no-parent\n`orca worktree create --no-parent`\nEOF"),
            bash_event("orca orchestration worker-start --worktree new-child --name x --agent claude --json"),
            '{"tool_input": {"command": "orca worktree create --no-parent"',
        ]

        for stdin in inputs:
            with self.subTest(stdin=stdin):
                # When
                result = run_hook(stdin)

                # Then
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
