"""Time every registered hook on a seeded input, compare its wall time with half its declared timeout, and check that
every timed run answers as the first, untimed run did.

Usage: python3 tests/tools/hook_timing.py --root <plugin tree> [--runs 5] [--path-python3]

Each hook runs through the launcher of the given tree on an input that reaches its main decision, N times, and the
table lists its maximum and median wall time next to half of the timeout it declares, and a decision column that is
"same" only when every timed run returned the status and output of the untimed run. The tree is only read; the
state folder, the project, and the stub programs live in a temporary folder. It is not collected by pytest.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LAUNCHER_COMMAND = re.compile(r'sh "\$\{CLAUDE_PLUGIN_ROOT\}/scripts/hook_python\.sh" ([a-z_]+\.py)')
PROJECT_FILES = (".claude/settings.json", ".codex/hooks.json")
GIT_WRITE = 'git commit -m "demo message"'
WORKTREE = {"id": "demo::/tmp/work/demo", "path": "/tmp/work/demo", "displayNameMode": "automatic", "isMainWorktree": False}
REPORT = "The change is done and the checks pass. " * 12
SQL_SOURCES = (
    '<?xml version="1.0"?><project version="4"><component name="DataSourceManagerImpl">'
    '<data-source source="LOCAL" name="demo-postgres" uuid="11111111-1111-4111-8111-111111111111">'
    "<driver-ref>postgresql</driver-ref></data-source></component></project>"
)


def registrations(root: Path) -> list[tuple[str, str, int, str]]:
    """Every (script, event, declared timeout, source file) the tree registers, project hooks included."""
    found = []
    for name in ("hooks.json", "codex-hooks.json", "claude-hooks.json"):
        path = root / "hooks" / name
        if not path.is_file():
            continue
        for event, groups in json.loads(path.read_text(encoding="utf-8"))["hooks"].items():
            for group in groups:
                for handler in group["hooks"]:
                    match = LAUNCHER_COMMAND.fullmatch(handler["command"])
                    if match:
                        found.append((match[1], event, handler["timeout"], name))
    for name in PROJECT_FILES:
        path = root / name
        if path.is_file():
            for event, groups in json.loads(path.read_text(encoding="utf-8"))["hooks"].items():
                for group in groups:
                    for handler in group["hooks"]:
                        found.append(("public_boundary.py agent-hook", event, handler["timeout"], name))
    return found


def seed(script: str, event: str, work: Path) -> dict:
    """The event a hook decides on: a pending write, an Orca terminal edit, a changed-file report, and so on."""
    base = {"hook_event_name": event, "session_id": "timing", "cwd": str(work), "tool_use_id": "t1"}
    bash = {"tool_name": "Bash", "tool_input": {"command": GIT_WRITE}}
    if script == "session_context.py":
        return {**base, "source": "startup", "prompt": "Continue"}
    if script == "approval_guard.py":
        if event == "UserPromptSubmit":
            return {**base, "prompt": "Continue"}
        return {**base, "tool_name": "Bash", "tool_input": {"command": "gh issue create --title demo --body demo"}}
    if script == "datagrip_guard.py":
        return {**base, "tool_name": "mcp__datagrip__execute_sql_query", "tool_input": {
            "projectPath": str(work), "connectionId": "11111111-1111-4111-8111-111111111111", "queryText": "SELECT 1"}}
    if script in ("public_boundary_hook.py", "public_boundary.py agent-hook"):
        return {**base, **bash}
    if script == "required_checks_hook.py":
        return {**base, "tool_name": "Bash", "tool_input": {"command": "git push origin demo-a"}}
    if script == "orca_placement_hook.py":
        return {**base, "tool_name": "Bash", "tool_input": {
            "command": "orca worktree set --worktree path:/tmp/work/demo --display-name demo-title"}}
    if script == "orca_status_hook.py":
        if event == "PostToolUse":
            return {**base, "tool_name": "Edit", "tool_input": {"file_path": "/tmp/work/demo/a.py"}}
        return {**base, "stop_hook_active": False, "last_assistant_message": "Done. Want more?",
                "transcript_path": str(work / "session.jsonl"), "prompt": "Continue"}
    if script == "language_guard.py":
        return {**base, "last_assistant_message": REPORT, "stop_hook_active": False,
                "transcript_path": str(work / "session.jsonl")}
    if script == "final_report_hook.py":
        return {**base, "last_assistant_message": REPORT, "stop_hook_active": False,
                "transcript_path": str(work / "session.jsonl")}
    if script == "agent_guard.py":
        return {**base, "tool_name": "Agent", "tool_input": {"agent_type": "default"}}
    return base


def write_transcript(path: Path) -> None:
    lines = [
        {"type": "user", "isSidechain": False, "message": {"role": "user", "content": "do the task"}},
        {"type": "assistant", "isSidechain": False, "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Edit", "input": {
                "file_path": "/tmp/work/a.py", "old_string": "a", "new_string": "b"}}]}},
        {"type": "assistant", "isSidechain": False, "message": {"role": "assistant", "content": [
            {"type": "text", "text": REPORT}]}},
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


def stub_orca(directory: Path) -> None:
    stub = directory / "orca"
    answer = json.dumps({"ok": True, "result": {"worktree": WORKTREE, "worktrees": [WORKTREE]}})
    stub.write_text(f"#!/bin/sh\necho '{answer}'\n", encoding="utf-8")
    stub.chmod(0o755)


def run_once(root: Path, script: str, event: dict, env: dict, work: Path) -> tuple[float, int, str]:
    if script == "public_boundary.py agent-hook":
        command = ["sh", str(root / ".githooks" / "agent_hook.sh")]
        if not (root / ".githooks" / "agent_hook.sh").is_file():
            command = [env["HEI5ENBUG_PYTHON"], str(root / ".githooks" / "public_boundary.py"), "agent-hook"]
    else:
        command = ["sh", str(root / "scripts" / "hook_python.sh"), script]
    start = time.monotonic()
    result = subprocess.run(command, input=json.dumps(event), text=True, capture_output=True, env=env, cwd=work,
                            timeout=120)
    return time.monotonic() - start, result.returncode, result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, type=Path, help="the plugin tree to time (only read)")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--path-python3", action="store_true", help="run python3 from PATH instead of this interpreter")
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        work = base / "work"
        (work / ".idea").mkdir(parents=True)
        (work / ".idea" / "dataSources.xml").write_text(SQL_SOURCES, encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(work)], check=True)
        write_transcript(work / "session.jsonl")
        stubs = base / "stubs"
        stubs.mkdir()
        stub_orca(stubs)
        system = os.environ["PATH"]
        env = {"PATH": f"{stubs}:{system}", "HOME": str(base / "home"), "XDG_STATE_HOME": str(base / "state"),
               "ORCA_TERMINAL_HANDLE": "term_timing",
               "HEI5ENBUG_MACHINE_COUNTERS_FOR_TESTS": "1,8,0.5,0.5"}
        if not arguments.path_python3:
            env["HEI5ENBUG_PYTHON"] = os.path.realpath(sys.executable)
        print(f"root: {root}")
        print(f"{'hook':32} {'event':20} {'half':>5} {'max':>7} {'median':>7}  {'within':6} decision")
        failures = 0
        for script, event, timeout, source in registrations(root):
            run_env = {**env, "PLUGIN_ROOT": str(root)} if source == "codex-hooks.json" else env
            seeded = seed(script, event, work)
            _, code, output = run_once(root, script, {**seeded, "session_id": "timing-expected"}, run_env, work)
            runs = [run_once(root, script, {**seeded, "session_id": f"timing-{index}"}, run_env, work)
                    for index in range(arguments.runs)]
            times = [seconds for seconds, _, _ in runs]
            half = timeout / 2
            inside = max(times) <= half
            same = all((run_code, run_output) == (code, output) for _, run_code, run_output in runs)
            failures += (not inside) + (not same)
            print(f"{script:32} {event:20} {half:>5g} {max(times):>7.3f} {statistics.median(times):>7.3f}  "
                  f"{'yes' if inside else 'NO':6} {'same' if same else 'DIFFERENT'}")
        shutil.rmtree(work, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
