#!/usr/bin/env python3
"""Run the clean-up checks of one worktree and print one JSON object with `pass`, `fail`, or `unreadable` per check.

`--worktree-id <id> --base-ref <ref>` checks a finished agent session's worktree. `--no-agent` checks a worktree no
agent runs in, and `--after-exit` adds the port and process checks that only make sense once the agent has exited.
Read-only except `git fetch` in `--no-agent` mode. Exit 0 when every check except `squash_possible` passes, 1 when
one fails, 3 when none fails but one is unreadable, 2 for a usage error or when the overview cannot be read.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import session_overview as overview  # noqa: E402

PASS, FAIL, UNREADABLE = "pass", "fail", "unreadable"
INFORMATIONAL = "squash_possible"
SHELLS = {"sh", "bash", "zsh", "fish", "dash", "ksh"}


def result(status: str, value: object = None) -> dict:
    return {"status": status, "value": value}


def verdict(condition: bool, value: object = None) -> dict:
    return result(PASS if condition else FAIL, value)


def git(runner: overview.Runner, path: str, *args: str) -> tuple[int, str, str]:
    return runner(["git", "--literal-pathspecs", "-C", path, *args])


def unreadable(label: str, code: int, err: str) -> dict:
    lines = (err or "").strip().splitlines()
    return result(UNREADABLE, f"{label} failed: {lines[0] if lines else f'exit {code}'}")


def orca_list(runner: overview.Runner, command: list[str], args: list[str], key: str) -> list | None:
    try:
        found = overview.read_result(runner, command, args).get(key)
    except overview.OverviewError:
        return None
    return found if isinstance(found, list) else None


def status_checks(runner: overview.Runner, path: str) -> tuple[dict, list[str]]:
    code, out, err = git(runner, path, "status", "--porcelain", "--ignored")
    if code != 0:
        return unreadable("git status", code, err), []
    lines = [line for line in out.splitlines() if line]
    changes = [line for line in lines if not line.startswith("!! ")]
    return verdict(not changes, changes), [line[3:] for line in lines if line.startswith("!! ")]


def merged_into_ref(runner: overview.Runner, path: str, ref: str) -> dict:
    code, _, err = git(runner, path, "merge-base", "--is-ancestor", "HEAD", ref)
    if code in (0, 1):
        return verdict(code == 0, f"HEAD is {'' if code == 0 else 'not '}an ancestor of {ref}")
    return unreadable("git merge-base", code, err)


def unpushed_commits(runner: overview.Runner, path: str) -> dict:
    code, _, err = git(runner, path, "fetch")
    if code != 0:
        return unreadable("git fetch", code, err)
    code, out, err = git(runner, path, "rev-list", "--count", "@{upstream}..HEAD")
    if code == 0 and out.strip().isdigit():
        return verdict(int(out) == 0, int(out))
    if "no upstream" in (err or "").lower():
        return result(FAIL, "no upstream branch")
    return unreadable("git rev-list", code, err)


def squash_possible(runner: overview.Runner, path: str, ref: str, merged: dict) -> dict:
    """Pass only when the branch is not an ancestor of the ref but every file it changed already has its content there."""
    if merged["status"] != FAIL:
        return result(FAIL, "not applicable")
    code, base, err = git(runner, path, "merge-base", ref, "HEAD")
    if code != 0:
        return unreadable("git merge-base", code, err)
    code, names, err = git(runner, path, "diff", "--name-only", "-z", base.strip(), "HEAD")
    if code != 0:
        return unreadable("git diff", code, err)
    files = [name for name in names.split("\0") if name]
    if not files:
        return result(PASS, 0)
    code, _, err = git(runner, path, "diff", "--quiet", ref, "HEAD", "--", *files)
    if code in (0, 1):
        return verdict(code == 0, len(files))
    return unreadable("git diff", code, err)


def lsof_processes(runner: overview.Runner) -> list[tuple[int, str]] | None:
    code, out, _ = runner(["lsof", "-d", "cwd", "-Fpn"])
    if not out.strip():
        return None
    found: list[tuple[int, str]] = []
    pid = None
    for line in out.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            found.append((pid, line[1:]))
    return found


def process_table(runner: overview.Runner) -> tuple[dict[int, str], set[int]] | None:
    code, out, _ = runner(["ps", "-A", "-o", "pid=,ppid=,args="])
    if code != 0 or not out.strip():
        return None
    args: dict[int, str] = {}
    parents: set[int] = set()
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            args[int(parts[0])] = parts[2] if len(parts) > 2 else ""
            parents.add(int(parts[1]))
    return args, parents


def idle_shell(command: str, pid: int, parents: set[int]) -> bool:
    """A shell with no child and no script or `-c` argument, which is the terminal's own shell at its prompt."""
    words = command.split()
    return bool(words) and os.path.basename(words[0]).lstrip("-") in SHELLS and pid not in parents and all(
        word.startswith("-") for word in words[1:]
    )


def no_processes(runner: overview.Runner, path: str) -> dict:
    processes, table = lsof_processes(runner), process_table(runner)
    if processes is None or table is None:
        return result(UNREADABLE, "lsof or ps returned nothing")
    args, parents = table
    root = os.path.realpath(path)
    inside = [pid for pid, cwd in processes if os.path.realpath(cwd) == root or os.path.realpath(cwd).startswith(root + os.sep)]
    running = [f"{pid} {args.get(pid, '?')}" for pid in dict.fromkeys(inside) if not idle_shell(args.get(pid, ""), pid, parents)]
    return verdict(not running, running)


def no_ports(runner: overview.Runner, command: list[str], worktree_id: str) -> dict:
    ports = orca_list(runner, command, ["ports", "--worktree", f"id:{worktree_id}"], "ports")
    return result(UNREADABLE, "orca ports could not be read") if ports is None else verdict(not ports, ports)


def candidate(data: dict, worktree_id: str, no_agent: bool) -> tuple[dict | None, list[dict]]:
    rows = [row for row in data["sessions"] if row["worktree_id"] == worktree_id]
    if no_agent:
        idle = [row for row in data["worktrees_without_agent"] if row["worktree_id"] == worktree_id]
        return (idle[0] if idle else None), rows
    return (rows[0] if rows else None), rows


def terminal_checks(runner: overview.Runner, command: list[str], data: dict, row: dict, sessions: list[dict], no_agent: bool) -> dict:
    current = data["current_terminal_handle"]
    checks = {"not_current": verdict(not any(session["is_current"] for session in sessions) and current not in row.get("terminal_handles", []))}
    if no_agent:
        checks["no_shared_worktree"] = verdict(not sessions, [session["terminal_handle"] for session in sessions])
        return checks
    handles = orca_list(runner, command, ["terminal", "list", "--worktree", f"id:{row['worktree_id']}"], "terminals")
    own = row["terminal_handle"]
    if handles is None or own is None:
        checks["only_terminal"] = result(UNREADABLE, "terminal handles could not be read")
    else:
        found = [item.get("handle") for item in handles if isinstance(item, dict)]
        checks["only_terminal"] = verdict(found == [own] and len(sessions) == 1, found)
    return checks


def run_checks(runner: overview.Runner, command: list[str], data: dict, worktree_id: str, ref: str, no_agent: bool, after_exit: bool) -> dict:
    row, sessions = candidate(data, worktree_id, no_agent)
    if row is None:
        raise overview.OverviewError(f"worktree {worktree_id} is not a {'worktree without an agent' if no_agent else 'session worktree'} in the overview")
    path = row["path"]
    status, ignored = status_checks(runner, path)
    merged = unpushed_commits(runner, path) if no_agent else merged_into_ref(runner, path, ref)
    checks = {
        "not_main": verdict(not row["is_main_worktree"], row["is_main_worktree"]),
        "no_children": verdict(row["child_count"] == 0, row["child_count"]),
        **terminal_checks(runner, command, data, row, sessions, no_agent),
        "status_clean": status,
        "base_merged": merged,
        INFORMATIONAL: squash_possible(runner, path, ref, merged),
    }
    if after_exit:
        checks.update(no_ports=no_ports(runner, command, worktree_id), no_processes=no_processes(runner, path))
    return {"worktree_id": worktree_id, "path": path, "checks": checks, "ignored": ignored}


def exit_code(checks: dict) -> int:
    statuses = [check["status"] for name, check in checks.items() if name != INFORMATIONAL]
    return 1 if FAIL in statuses else 3 if UNREADABLE in statuses else 0


def main(argv: Sequence[str] | None = None, runner: overview.Runner = overview.subprocess_runner, env: dict | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree-id", required=True)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--no-agent", action="store_true")
    parser.add_argument("--after-exit", action="store_true")
    args = parser.parse_args(argv)
    try:
        env = dict(os.environ if env is None else env)
        data = overview.build_overview(runner, 0, env)
        report = run_checks(runner, overview.orca_command(env), data, args.worktree_id, args.base_ref, args.no_agent, args.after_exit)
    except overview.OverviewError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return exit_code(report["checks"])


if __name__ == "__main__":
    sys.exit(main())
