"""PreToolUse hook that denies a command creating a top-level Orca worktree."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = SCRIPTS / "orca_placement_hook.py"
sys.path.insert(0, str(SCRIPTS))
import session_memory  # noqa: E402

MEMORY_ENV = "HEI5ENBUG_AVAILABLE_MEMORY_MB_FOR_TESTS"
OPTION_ENV = "CLAUDE_PLUGIN_OPTION_SESSION_MEMORY_MIN_MB"
ENOUGH_MB = "100000"
REASON = (
    "Blocked: this command creates a top-level Orca worktree. Put a new worktree under an existing workspace so "
    "every worktree of one ticket stays in one group: use `--parent-worktree active` in this repository, "
    "`--parent-worktree id:<repoId>::<clone path>` for another repository's workspace, or the group root's id for a "
    "task that changes several repositories; with orchestration, use `--worktree new-child` or an existing "
    "worktree. Only when Orca lists no workspace for the repository, or the user asked for a top-level worktree in "
    "this conversation, create it with a parent and then run `orca worktree set --worktree <id> --no-parent "
    "--json`."
)


def run_hook(
    stdin: str, memory_mb: str | None = ENOUGH_MB, option: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key not in {MEMORY_ENV, OPTION_ENV, "PLUGIN_ROOT"}}
    env[MEMORY_ENV] = "unknown" if memory_mb is None else memory_mb
    if option is not None:
        env[OPTION_ENV] = option
    return subprocess.run(
        [sys.executable, str(SCRIPT)], input=stdin, capture_output=True, text=True, check=False, env=env
    )


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


START_COMMANDS = {
    "worktree create with --agent": "orca worktree create --repo id:demo-repo --name x --parent-worktree active --agent claude --json",
    "worktree create with --agent=": "orca worktree create --repo id:demo-repo --name x --parent-worktree active --agent=codex --json",
    "worker-start": "orca orchestration worker-start --spec-file s.md --worktree new-child --name x --json",
    "agent launch": "orca agent launch --worktree active --agent claude --json",
    "terminal create running claude": "orca terminal create --worktree active --command '/usr/local/bin/claude --resume' --json",
    "terminal create running codex": "orca-dev terminal create --worktree active --command=codex --json",
    "start inside a substitution": 'handle="$(orca agent launch --worktree active --agent codex --json)"',
    # Regression: the documented shell-prefixed launch `cd '<path>' && <host>` bypasses the gate
    "terminal create with a cd prefix": "orca terminal create --worktree id:demo --title x --command \"cd '/tmp/work' && claude\" --json",
    # Regression: single quotes inside an unquoted here-document do not stop the substitution from running
    "substitution in an unquoted here-document": "cat > /tmp/work/x.md <<EOF\n'$(orca agent launch --agent claude --json)'\nEOF",
}
NOT_START_COMMANDS = [
    "orca worktree set --worktree id:demo-repo::/tmp/work --agent claude --json",
    "orca worktree create --repo id:demo-repo --name x --parent-worktree active --json",
    "orca terminal create --worktree active --command zsh --json",
    "orca terminal create --worktree active --json",
    "orca terminal send --terminal t1 --text 'run claude' --command claude --enter --json",
    "orca agent list --json",
    'echo "orca agent launch --agent claude"',
    # Regression: a single-quoted or escaped substitution is literal text, yet was denied on low memory
    "printf '%s\\n' '$(orca agent launch --agent claude)'",
    'echo "\\$(orca agent launch --agent claude)"',
]


class SessionMemoryGateTest(unittest.TestCase):
    def assert_memory_denied(self, result: subprocess.CompletedProcess[str], available: int, threshold: int) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        reason = output["permissionDecisionReason"]
        self.assertIn(f"{available} MB of memory is available, below the {threshold} MB", reason)
        self.assertIn("never poll memory", reason)
        self.assertIn("session-triage", reason)
        self.assertIn("session_memory_min_mb", reason)

    def assert_allowed(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_메모리가_기준_미만이면_에이전트_시작_명령_네_형태를_차단한다(self):
        # Regression: a start form missing from the gate pushes the machine into swap
        for name, command in START_COMMANDS.items():
            with self.subTest(name=name):
                # Given
                stdin = bash_event(command)

                # When
                result = run_hook(stdin, memory_mb="1500")

                # Then
                self.assert_memory_denied(result, available=1500, threshold=2048)

    def test_메모리가_기준_이상이면_에이전트_시작_명령을_허용한다(self):
        # Regression: a gate that denies with enough memory blocks every start
        for name, command in START_COMMANDS.items():
            for memory_mb in ("2048", "4096"):
                with self.subTest(name=name, memory_mb=memory_mb):
                    # When
                    result = run_hook(bash_event(command), memory_mb=memory_mb)

                    # Then
                    self.assert_allowed(result)

    def test_메모리를_알_수_없으면_차단하지_않는다(self):
        # Regression: an unreadable memory source denies every start on an unsupported platform
        for name, command in START_COMMANDS.items():
            with self.subTest(name=name):
                # When
                result = run_hook(bash_event(command), memory_mb=None)

                # Then
                self.assert_allowed(result)

    def test_옵션이_0이나_off이면_메모리가_부족해도_허용한다(self):
        # Regression: the off switch is ignored and the user cannot start sessions
        command = START_COMMANDS["agent launch"]
        for option in ("0", "off", "OFF", "false", "no"):
            with self.subTest(option=option):
                # When
                result = run_hook(bash_event(command), memory_mb="10", option=option)

                # Then
                self.assert_allowed(result)

    def test_옵션_값이_기준이_되고_잘못된_값은_기본_2048을_쓴다(self):
        # Regression: a custom threshold is ignored, or an invalid value turns the gate off
        command = START_COMMANDS["agent launch"]
        cases = [("512", "600", None), ("512", "500", 512), ("not-a-number", "1500", 2048), ("-5", "1500", 2048),
                 ("1.5", "1500", 2048), ("", "1500", 2048)]
        for option, memory_mb, denied_threshold in cases:
            with self.subTest(option=option, memory_mb=memory_mb):
                # When
                result = run_hook(bash_event(command), memory_mb=memory_mb, option=option)

                # Then
                if denied_threshold is None:
                    self.assert_allowed(result)
                else:
                    self.assert_memory_denied(result, available=int(memory_mb), threshold=denied_threshold)

    def test_시작이_아닌_명령은_메모리가_부족해도_차단하지_않는다(self):
        # Regression: gating terminal send or other commands blocks work that starts no session
        for command in NOT_START_COMMANDS:
            with self.subTest(command=command):
                # When
                result = run_hook(bash_event(command), memory_mb="10")

                # Then
                self.assert_allowed(result)

    def test_최상위_워크트리_차단이_메모리_차단보다_우선한다(self):
        # Regression: the memory reason hides the placement reason for a command that breaks both rules
        command = "orca worktree create --repo id:demo-repo --name x --no-parent --agent claude --json"

        # When
        result = run_hook(bash_event(command), memory_mb="10")

        # Then
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"], REASON)

    def test_리눅스_meminfo_파싱이_가용_메모리를_메가바이트로_돌려준다(self):
        # Regression: MemAvailable read in kB or a missing field returns a wrong number instead of None
        meminfo = "MemTotal:       16384000 kB\nMemFree:          200000 kB\nMemAvailable:    3145728 kB\nBuffers: 1 kB\n"

        # When / Then
        self.assertEqual(session_memory.parse_meminfo(meminfo), 3072)
        self.assertIsNone(session_memory.parse_meminfo("MemTotal: 16384000 kB\n"))

    def test_맥_sysctl_출력_파싱이_여유_비율을_총량에_곱하고_잘못된_출력은_none이다(self):
        # Regression: swapping the two sysctl lines or accepting garbage reports a false amount
        eight_gib = str(8 * 1024**3)

        # When / Then
        self.assertEqual(session_memory.parse_darwin(f"25\n{eight_gib}\n"), 2048)
        self.assertIsNone(session_memory.parse_darwin(""))
        self.assertIsNone(session_memory.parse_darwin(f"abc\n{eight_gib}\n"))
        self.assertIsNone(session_memory.parse_darwin(f"250\n{eight_gib}\n"))


if __name__ == "__main__":
    unittest.main()
