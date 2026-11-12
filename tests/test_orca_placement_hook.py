"""PreToolUse hook that denies a command creating a top-level Orca worktree."""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
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
    "Blocked: this command creates a top-level Orca worktree. Put a new worktree under its own repository's "
    "existing workspace: use `--parent-worktree active` in this repository, "
    "or `--parent-worktree id:<repoId>::<clone path>` for another repository's workspace; with orchestration, use "
    "`--worktree new-child` or an existing worktree. Only when Orca lists no workspace for the repository, or the "
    "user asked for a top-level worktree in "
    "this conversation, create it with a parent and then run `orca worktree set --worktree <id> --no-parent "
    "--json`."
)


STUB_DIRECTORY = tempfile.mkdtemp(prefix="orca-stub-")
atexit.register(shutil.rmtree, STUB_DIRECTORY, True)
STUB = Path(STUB_DIRECTORY) / "orca"
STUB.write_text(
    '#!/bin/sh\nif [ "$2" = list ] && [ -n "$ORCA_STUB_LIST" ]; then cat "$ORCA_STUB_LIST"; exit 0; fi\n'
    'if [ -n "$ORCA_STUB_JSON" ]; then cat "$ORCA_STUB_JSON"; else exit 1; fi\n'
)
STUB.chmod(0o755)


def run_hook(
    stdin: str, memory_mb: str | None = ENOUGH_MB, option: str | None = None, orca_terminal: bool = False,
    orca_json: str | None = None, orca_list: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {MEMORY_ENV, OPTION_ENV, "PLUGIN_ROOT", "ORCA_TERMINAL_HANDLE", "ORCA_STUB_JSON", "ORCA_STUB_LIST"}
    }
    env["PATH"] = f"{STUB_DIRECTORY}{os.pathsep}{env.get('PATH', '')}"
    env[MEMORY_ENV] = "unknown" if memory_mb is None else memory_mb
    if option is not None:
        env[OPTION_ENV] = option
    if orca_terminal:
        env["ORCA_TERMINAL_HANDLE"] = "term_test"
    if orca_json is not None:
        env["ORCA_STUB_JSON"] = orca_json
    if orca_list is not None:
        env["ORCA_STUB_LIST"] = orca_list
    return subprocess.run(
        [sys.executable, str(SCRIPT)], input=stdin, capture_output=True, text=True, check=False, env=env
    )


def bash_event(command: str, cwd: str | None = None) -> str:
    event = {"tool_name": "Bash", "tool_input": {"command": command}}
    if cwd is not None:
        event["cwd"] = cwd
    return json.dumps(event)


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


def git(path: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Demo", "-c", "user.email=demo@example.com", "-C", str(path), *args],
        capture_output=True, text=True, check=True,
    )


COMPLETED = "orca worktree set --worktree {selector} --workspace-status completed --comment done --json"


class CompletedStatusGateTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        origin = root / "origin.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], capture_output=True, check=True)
        self.work = root / "work"
        subprocess.run(["git", "clone", str(origin), str(self.work)], capture_output=True, check=True)
        (self.work / "a.txt").write_text("a\n")
        git(self.work, "add", "a.txt")
        git(self.work, "commit", "-m", "first")
        git(self.work, "push", "-u", "origin", "HEAD:main")
        git(self.work, "branch", "--set-upstream-to=origin/main")

    def run_completed(self, selector: str = "active", command: str | None = None) -> subprocess.CompletedProcess[str]:
        text = command or COMPLETED.format(selector=selector)
        return run_hook(bash_event(text, cwd=str(self.work)))

    def reason_of(self, result: subprocess.CompletedProcess[str]) -> str:
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        return output["permissionDecisionReason"]

    def test_완료로_바꾸려는_워크트리에_커밋하지_않은_변경이_있으면_차단하고_남은_것을_알려준다(self):
        # Regression: a false Done leaves uncommitted work behind a completed card
        # Given
        (self.work / "a.txt").write_text("changed\n")
        (self.work / "new.txt").write_text("new\n")

        # When
        reason = self.reason_of(self.run_completed())

        # Then
        self.assertIn("2 uncommitted changes", reason)
        self.assertIn("a.txt", reason)
        self.assertIn("new.txt", reason)
        self.assertNotIn("--comment", reason)

    def test_업스트림에_없는_커밋이_있으면_차단한다(self):
        # Regression: a false Done leaves unpushed commits behind a completed card
        # Given
        (self.work / "a.txt").write_text("two\n")
        git(self.work, "commit", "-am", "second")

        # When
        reason = self.reason_of(self.run_completed())

        # Then
        self.assertIn("1 commit its upstream lacks", reason)
        self.assertNotIn("uncommitted", reason)

    def test_업스트림이_없는_브랜치의_커밋도_원격에_없으면_남은_일로_센다(self):
        # Regression: a branch that was never pushed passes as done because it has no upstream
        # Given
        git(self.work, "checkout", "-b", "feature/abc-123")
        (self.work / "b.txt").write_text("b\n")
        git(self.work, "add", "b.txt")
        git(self.work, "commit", "-m", "feature")

        # When
        reason = self.reason_of(self.run_completed(selector=f"id:repo-id::{self.work}"))

        # Then
        self.assertIn("1 commit its upstream lacks", reason)

    def test_깨끗하고_푸시된_워크트리나_다른_상태와_풀_수_없는_선택자는_통과한다(self):
        # Regression: a gate that blocks a clean Done, other statuses, or a target it cannot resolve
        # Given
        commands = [
            COMPLETED.format(selector="active"),
            COMPLETED.format(selector=f"path:{self.work}"),
            COMPLETED.format(selector=f"id:repo-id::{self.work}"),
        ]
        (self.work / "a.txt").write_text("dirty\n")
        dirty = [
            "orca worktree set --worktree active --workspace-status in-review --comment waits --json",
            "orca worktree set --worktree active --comment completed --json",
            COMPLETED.format(selector="name:demo"),
            COMPLETED.format(selector="branch:feature/abc-123"),
            COMPLETED.format(selector="path:/home/test/does-not-exist"),
            'echo "orca worktree set --workspace-status completed"',
        ]

        # When / Then
        for command in dirty:
            with self.subTest(command=command):
                result = self.run_completed(command=command)
                self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)
        git(self.work, "checkout", "--", "a.txt")
        for command in commands:
            with self.subTest(command=command):
                result = self.run_completed(command=command)
                self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)


def current_worktree_json(repo_id: str = "repo-a") -> str:
    record = {"id": f"{repo_id}::/home/test/{repo_id}", "repoId": repo_id, "path": f"/home/test/{repo_id}"}
    return json.dumps({"ok": True, "result": {"worktree": record}})


class ParentRepositoryGateTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.current = self.root / "current.json"
        self.current.write_text(current_worktree_json())
        for name in ("a", "b"):
            subprocess.run(["git", "init", "-q", "-b", "main", str(self.root / name)], check=True)
        git(self.root / "a", "commit", "--allow-empty", "-m", "first")
        self.linked = self.root / "a-feature"
        git(self.root / "a", "worktree", "add", "-b", "feature", str(self.linked))

    def run_command(self, command: str, orca_json: str | None = "default") -> subprocess.CompletedProcess[str]:
        stub = str(self.current) if orca_json == "default" else orca_json
        return run_hook(bash_event(command, cwd=str(self.root / "a")), orca_json=stub)

    def assert_denied(self, command: str, orca_json: str | None = "default") -> None:
        result = self.run_command(command, orca_json)
        self.assertEqual(result.returncode, 0, result.stderr)
        reason = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("parent belongs to another repository", reason)
        self.assertIn("--reference <issue link>", reason)

    def assert_allowed(self, command: str, orca_json: str | None = "default") -> None:
        result = self.run_command(command, orca_json)
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)

    def test_다른_저장소의_워크트리를_부모로_주는_생성과_설정과_워커_시작을_차단한다(self):
        # Regression: a ticket's worktrees in several repositories were nested under one group root
        commands = [
            "orca worktree create --repo id:repo-b --name x --parent-worktree active --json",
            "orca worktree create --repo id:repo-b --name x --parent-worktree id:repo-a::/home/test/repo-a --json",
            f"orca worktree create --repo path:{self.root / 'b'} --name x --parent-worktree path:{self.root / 'a'} --json",
            f"orca worktree create --repo path:{self.root / 'b'} --name x --parent-worktree active --json",
            "orca orchestration worker-start --worktree new-child --repo id:repo-b --agent claude --spec x --json",
            "orca worktree set --worktree id:repo-b::/home/test/repo-b --parent-worktree id:repo-a::/home/test/repo-a",
            "orca worktree set --worktree active --parent-worktree id:repo-b::/home/test/repo-b --json",
            'result="$(orca worktree create --repo id:repo-b --name x --parent-worktree active --json)"',
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assert_denied(command)

    def test_자기_저장소의_작업공간이나_연결된_워크트리를_부모로_주면_허용한다(self):
        # Regression: a gate that blocks the placement the rule asks for
        commands = [
            "orca worktree create --repo id:repo-a --name x --parent-worktree active --json",
            "orca worktree create --repo id:repo-b --name x --parent-worktree id:repo-b::/home/test/repo-b --json",
            f"orca worktree create --repo path:{self.root / 'a'} --name x --parent-worktree path:{self.linked} --json",
            "orca worktree create --repo id:repo-a --name x --json",
            "orca orchestration worker-start --worktree new-child --agent claude --spec x --json",
            "orca orchestration worker-start --worktree current --repo id:repo-b --agent claude --spec x",
            "orca orchestration worker-start --worktree new-child --repo id:repo-a --agent claude --spec x --json",
            "orca worktree set --worktree id:repo-a::/home/test/repo-a --parent-worktree active --json",
            "orca worktree set --worktree active --comment hello --json",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assert_allowed(command)

    def test_사용자가_정한_폴더_작업공간을_부모로_주는_생성과_설정은_허용하고_다른_저장소의_부모는_계속_차단한다(self):
        # Regression: a ticket's worktrees cannot be grouped under the folder the user named, or the folder case
        # loosens the denial of another repository's worktree as a parent
        # Given
        allowed = [
            "orca worktree create --repo id:demo --parent-worktree folder:demo-folder",
            "orca worktree set --worktree id:demo::/tmp/work/demo-a --parent-worktree folder:demo-folder",
            "orca worktree create --repo id:demo --name x --parent-worktree folder:demo-folder --json",
        ]
        denied = [
            "orca worktree create --repo id:demo --parent-worktree id:other::/tmp/work/other",
            "orca worktree set --worktree id:demo::/tmp/work/demo-a --parent-worktree id:other::/tmp/work/other",
        ]

        # When / Then
        for command in allowed:
            with self.subTest(command=command):
                self.assert_allowed(command)
        for command in denied:
            with self.subTest(command=command):
                self.assert_denied(command)
        reason = json.loads(self.run_command(denied[0]).stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("folder:<id>", reason)

    def test_저장소를_알_수_없으면_허용한다(self):
        # Regression: a gate that denies when it cannot tell, such as a name selector or an unreadable Orca
        commands = [
            "orca worktree create --repo name:demo --name x --parent-worktree active --json",
            "orca worktree create --repo id:repo-b --name x --parent-worktree branch:feature/abc-123 --json",
            "orca worktree create --repo id:repo-b --name x --parent-worktree name:demo --json",
            "orca worktree set --worktree name:demo --parent-worktree id:repo-a::/home/test/repo-a",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assert_allowed(command)
        self.assert_allowed("orca worktree create --repo id:repo-b --name x --parent-worktree active --json", None)


MAIN_CLONE = "/tmp/work/demo-a"
CHILD = "/tmp/work/demo-a-abc-1"
RENAME_MAIN = 'orca worktree set --worktree {selector} --display-name "ABC-1 demo" --json'


def listed(path: str, main: bool, name: str, branch: str, repo_id: str = "repo-a") -> dict:
    return {
        "id": f"{repo_id}::{path}", "repoId": repo_id, "path": path, "isMainWorktree": main, "displayName": name,
        "branch": f"refs/heads/{branch}", "identity": {"key": f"wt2:local:{name}"},
    }


class MainCloneRenameGateTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        records = [
            listed(MAIN_CLONE, True, "main", "main"),
            listed(CHILD, False, "abc-1-api", "feature/ABC-1"),
            listed("/tmp/work/demo-b", True, "twin", "main", "repo-b"),
            listed("/tmp/work/demo-b-x", False, "twin", "feature/x", "repo-b"),
        ]
        self.listing = self.write("list.json", {"ok": True, "result": {"worktrees": records}})
        self.current = self.write("current.json", {"ok": True, "result": {"worktree": records[0]}})

    def write(self, name: str, payload: dict) -> str:
        path = self.root / name
        path.write_text(json.dumps(payload))
        return str(path)

    def run_command(self, command: str, current: str | None = "default", listing: str | None = "default"):
        return run_hook(
            bash_event(command, cwd="/tmp/work"),
            orca_json=self.current if current == "default" else current,
            orca_list=self.listing if listing == "default" else listing,
        )

    def assert_denied(self, command: str, **options) -> None:
        result = self.run_command(command, **options)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        reason = output["permissionDecisionReason"]
        self.assertIn("main clone", reason)
        self.assertIn('orca terminal rename --terminal "$ORCA_TERMINAL_HANDLE" --title', reason)

    def assert_allowed(self, command: str, **options) -> None:
        result = self.run_command(command, **options)
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)

    def test_에이전트_실행과_함께_쓴_메인_클론_이름_변경도_차단한다(self):
        self.assert_denied(
            "orca agent launch --worktree active --agent claude --json; "
            f'orca worktree set --worktree path:{MAIN_CLONE} --display-name "ABC-1 demo"'
        )

    def test_메인_클론에_표시_이름을_주는_명령은_모든_선택자_형식에서_차단하고_세션_제목을_안내한다(self):
        # Regression: a session renamed the shared main clone, so every other session in it showed a ticket it was not on
        selectors = [
            f"path:{MAIN_CLONE}", f"id:repo-a::{MAIN_CLONE}", "name:main", "branch:main", "branch:refs/heads/main",
            "identity:wt2:local:main", "active", "current",
        ]
        for selector in selectors:
            with self.subTest(selector=selector):
                self.assert_denied(RENAME_MAIN.format(selector=selector))
        self.assert_denied(f'orca worktree set --worktree path:{MAIN_CLONE} --display-name="ABC-1 demo"')
        self.assert_denied(f'x="$(orca worktree set --worktree path:{MAIN_CLONE} --display-name \'ABC-1 demo\')"')
        self.assert_denied(f'cd /tmp/work && orca worktree set --worktree path:{MAIN_CLONE} --comment c --display-name n')

    def test_연결된_워크트리와_빈_이름과_이름이_아닌_변경은_메인_클론에도_허용한다(self):
        # Regression: a gate that blocks child worktrees, the restore of the automatic name, or other metadata
        commands = [
            RENAME_MAIN.format(selector=f"path:{CHILD}"),
            RENAME_MAIN.format(selector=f"id:repo-a::{CHILD}"),
            RENAME_MAIN.format(selector="name:abc-1-api"),
            f'orca worktree set --worktree path:{MAIN_CLONE} --display-name "" --json',
            f"orca worktree set --worktree path:{MAIN_CLONE} --display-name= --json",
            f'orca worktree set --worktree path:{MAIN_CLONE} --comment "ABC-1 demo" --json',
            f'echo "orca worktree set --worktree path:{MAIN_CLONE} --display-name x"',
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assert_allowed(command)
        child_current = self.write("child.json", {"ok": True, "result": {"worktree": listed(CHILD, False, "x", "y")}})
        self.assert_allowed(RENAME_MAIN.format(selector="active"), current=child_current)

    def test_오르카를_읽지_못하거나_대상을_못_찾거나_하나로_정할_수_없으면_허용한다(self):
        # Regression: a gate that denies when it cannot tell
        command = RENAME_MAIN.format(selector=f"path:{MAIN_CLONE}")
        self.assert_allowed(command, current=None, listing=None)
        self.assert_allowed(command, listing=self.write("bad.json", {"ok": False}))
        self.assert_allowed(RENAME_MAIN.format(selector="path:/tmp/work/unknown"))
        self.assert_allowed(RENAME_MAIN.format(selector="name:twin"))
        self.assert_allowed(RENAME_MAIN.format(selector="folder:abc"))
        self.assert_allowed(RENAME_MAIN.format(selector="active"), current=None)


def enter_event(**tool_input) -> str:
    return json.dumps({"tool_name": "EnterWorktree", "tool_input": tool_input})


class EnterWorktreeGateTest(unittest.TestCase):
    def test_오르카_터미널에서_새_워크트리를_만드는_호출은_차단하고_오르카_명령을_알려준다(self):
        # Regression: worktrees made with the host tool inside Orca are never listed by Orca
        for tool_input in ({}, {"name": "feature-x"}, {"path": ""}, {"name": "x", "path": "  "}):
            with self.subTest(tool_input=tool_input):
                # When
                result = run_hook(enter_event(**tool_input), orca_terminal=True)

                # Then
                self.assertEqual(result.returncode, 0, result.stderr)
                reason = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
                self.assertIn("orca worktree create --repo path:<repo> --name <branch> --base-branch <base>", reason)
                self.assertIn("--parent-worktree active --json", reason)

    def test_오르카_밖이거나_기존_경로로_들어가거나_다른_도구면_허용한다(self):
        # Regression: a gate that blocks entering a worktree Orca already lists, or any work outside Orca
        cases = [
            (enter_event(name="feature-x"), False),
            (enter_event(path="/tmp/work/abc-123"), True),
            (json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo EnterWorktree"}}), True),
        ]
        for stdin, orca_terminal in cases:
            with self.subTest(stdin=stdin, orca_terminal=orca_terminal):
                # When
                result = run_hook(stdin, orca_terminal=orca_terminal)

                # Then
                self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)

    def test_훅_등록은_엔터워크트리를_같은_훅으로_매칭한다(self):
        # Regression: the gate exists but no matcher sends EnterWorktree calls to it
        hooks = json.loads((Path(__file__).resolve().parents[1] / "hooks/hooks.json").read_text())["hooks"]
        groups = [
            group for group in hooks["PreToolUse"]
            if any("orca_placement_hook.py" in handler["command"] for handler in group["hooks"])
        ]

        # When / Then
        self.assertEqual([group["matcher"] for group in groups], ["^(Bash|EnterWorktree)$"])


if __name__ == "__main__":
    unittest.main()
