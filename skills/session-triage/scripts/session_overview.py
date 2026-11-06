#!/usr/bin/env python3
"""Print one JSON overview that joins Orca's agent sessions with their memory and terminal handles.

Read-only: it runs `worktree ps --agent-wait`, `terminal list`, and `diagnostics memory` once each and writes nothing.
`worktrees_without_agent` lists every non-main worktree that no agent session runs in, with or without a terminal, and a
main worktree only while it still has a live terminal.
Exit 0 on success, 2 with a one-line stderr reason when Orca is unreachable or a required read fails.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from typing import Callable, Sequence

MESSAGE_LIMIT = 400
PROMPT_LIMIT = 160
READ_TIMEOUT_SECONDS = 60
MIB = 1024 * 1024

Runner = Callable[[Sequence[str]], "tuple[int, str, str]"]


class OverviewError(Exception):
    """A required Orca read failed."""


def subprocess_runner(argv: Sequence[str]) -> tuple[int, str, str]:
    try:
        done = subprocess.run(
            list(argv), capture_output=True, text=True, timeout=READ_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL, check=False
        )
    except FileNotFoundError:
        return 127, "", f"`{argv[0]}` was not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"`{' '.join(argv[1:3])}` timed out"
    except OSError as error:
        return 126, "", f"`{argv[0]}` could not start: {error.strerror or error}"
    return done.returncode, done.stdout, done.stderr


def orca_command(env: dict[str, str]) -> list[str]:
    configured = env.get("ORCA_CLI_COMMAND")
    return [configured] if configured else ["orca"]


def read_result(runner: Runner, command: list[str], args: list[str]) -> dict:
    label = " ".join(args[:2])
    code, stdout, stderr = runner([*command, *args, "--json"])
    if code != 0:
        reason = (stderr or "").strip().splitlines()
        raise OverviewError(f"orca {label} failed: {reason[0] if reason else f'exit {code}'}")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise OverviewError(f"orca {label} returned unreadable JSON") from error
    if not isinstance(payload, dict) or payload.get("ok") is False:
        raise OverviewError(f"orca {label} was rejected")
    result = payload.get("result", payload)
    if not isinstance(result, dict):
        raise OverviewError(f"orca {label} returned an unsupported result")
    return result


def squash(text: object) -> str:
    return re.sub(r"\s+", " ", text).strip() if isinstance(text, str) else ""


def keep_tail(text: object, limit: int) -> str:
    """A final message ends with what it asks, so keep its end."""
    text = squash(text)
    return text if len(text) <= limit else "…" + text[-(limit - 1) :]


def keep_head(text: object, limit: int) -> str:
    text = squash(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def branch_name(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value.removeprefix("refs/heads/")


def megabytes(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(value / MIB)


def minutes_since(started_ms: object, now_ms: int) -> int | None:
    if isinstance(started_ms, bool) or not isinstance(started_ms, (int, float)):
        return None
    return max(0, int((now_ms - started_ms) // 60000))


def memory_by_pane(result: dict | None) -> dict[str, int]:
    found: dict[str, int] = {}
    for worktree in (result or {}).get("worktrees") or []:
        for session in worktree.get("sessions") or []:
            pane, memory = session.get("paneKey"), session.get("memory")
            if isinstance(pane, str) and isinstance(memory, (int, float)) and not isinstance(memory, bool):
                found[pane] = int(memory)
    return found


def handles_by_pane(terminals: list[dict]) -> dict[str, str]:
    found: dict[str, str] = {}
    for terminal in terminals:
        tab, leaf, handle = terminal.get("tabId"), terminal.get("leafId"), terminal.get("handle")
        if isinstance(tab, str) and isinstance(leaf, str) and isinstance(handle, str):
            found[f"{tab}:{leaf}"] = handle
    return found


def build_overview(runner: Runner, now_ms: int, env: dict[str, str]) -> dict:
    command = orca_command(env)
    current = env.get("ORCA_TERMINAL_HANDLE") or None
    warnings: list[str] = []

    ps = read_result(runner, command, ["worktree", "ps", "--agent-wait"])
    worktrees = ps.get("worktrees")
    if not isinstance(worktrees, list):
        raise OverviewError("orca worktree ps returned an unsupported worktree list")
    if ps.get("truncated") is True:
        warnings.append("worktree list was truncated, so some sessions are missing")

    terminal_result = read_result(runner, command, ["terminal", "list"])
    terminals = terminal_result.get("terminals")
    if not isinstance(terminals, list):
        raise OverviewError("orca terminal list returned an unsupported terminal list")
    if terminal_result.get("truncated") is True:
        warnings.append("terminal list was truncated, so some terminal handles may be missing")
    handles = handles_by_pane([t for t in terminals if isinstance(t, dict)])

    memory_result: dict | None = None
    try:
        memory_result = read_result(runner, command, ["diagnostics", "memory"])
    except OverviewError as error:
        warnings.append(f"memory is unknown: {error}")
    memory = memory_by_pane(memory_result)
    host = (memory_result or {}).get("host") or {}

    sessions: list[dict] = []
    without_agent: list[dict] = []
    for worktree in worktrees:
        if not isinstance(worktree, dict):
            continue
        agents = [a for a in worktree.get("agents") or [] if isinstance(a, dict)]
        base = {
            "worktree_id": worktree.get("worktreeId"),
            "repo": worktree.get("repo"),
            "display_name": worktree.get("displayName"),
            "branch": branch_name(worktree.get("branch")),
            "path": worktree.get("path"),
            "board_status": worktree.get("workspaceStatus"),
            "comment": worktree.get("comment") or "",
            "is_main_worktree": bool(worktree.get("isMainWorktree")),
        }
        if not agents:
            live = worktree.get("liveTerminalCount")
            live = live if isinstance(live, int) and not isinstance(live, bool) and live > 0 else 0
            if worktree.get("isArchived") is True or (base["is_main_worktree"] and live == 0):
                continue
            own = [t.get("handle") for t in terminals if isinstance(t, dict) and t.get("worktreeId") == worktree.get("worktreeId")]
            without_agent.append(
                {
                    **base,
                    "parent_worktree_id": worktree.get("parentWorktreeId"),
                    "child_count": len(worktree.get("childWorktreeIds") or []),
                    "live_terminals": live,
                    "terminal_handles": [h for h in own if isinstance(h, str)],
                }
            )
            continue
        for agent in agents:
            pane = agent.get("paneKey")
            handle = handles.get(pane) if isinstance(pane, str) else None
            used = memory.get(pane) if isinstance(pane, str) else None
            if used is None and memory_result is not None:
                warnings.append(f"memory not matched for {base['display_name'] or base['repo']} ({pane})")
            sessions.append(
                {
                    **base,
                    "parent_worktree_id": worktree.get("parentWorktreeId"),
                    "child_count": len(worktree.get("childWorktreeIds") or []),
                    "pane_key": pane,
                    "agent_type": agent.get("agentType"),
                    "conversation_name": agent.get("conversationName"),
                    "state": agent.get("state"),
                    "minutes_in_state": minutes_since(agent.get("stateStartedAt"), now_ms),
                    "interrupted": bool(agent.get("interrupted")),
                    "last_assistant_message": keep_tail(agent.get("lastAssistantMessage"), MESSAGE_LIMIT),
                    "prompt": keep_head(agent.get("prompt"), PROMPT_LIMIT),
                    "memory_mb": megabytes(used),
                    "terminal_handle": handle,
                    "is_current": current is not None and handle == current,
                }
            )
            if handle is None:
                warnings.append(f"no terminal matched {base['display_name'] or base['repo']} ({pane})")

    return {
        "host_total_mb": megabytes(host.get("totalMemory")),
        "host_available_mb": megabytes(host.get("availableMemory")),
        "current_terminal_handle": current,
        "sessions": sessions,
        "worktrees_without_agent": without_agent,
        "warnings": warnings,
    }


def main(
    argv: Sequence[str] | None = None,
    runner: Runner = subprocess_runner,
    now_ms: int | None = None,
    env: dict[str, str] | None = None,
) -> int:
    if list(argv if argv is not None else sys.argv[1:]):
        print("session_overview.py takes no arguments", file=sys.stderr)
        return 2
    try:
        overview = build_overview(runner, int(time.time() * 1000) if now_ms is None else now_ms, dict(os.environ if env is None else env))
    except OverviewError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(overview, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
