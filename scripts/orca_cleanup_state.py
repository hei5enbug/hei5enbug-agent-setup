"""What the Orca status hook remembers about worktrees its session created, and the run that removes them.

The hook records `orca worktree create`, `orca terminal create`, and `orca orchestration worker-start` commands from the
tool input, starts the detached run in `orca_cleanup_run.py` at a prompt or the end of a turn, and shows what the run
decided. This module holds the command parsing, the result file the run writes, the run lock, and the notice texts. It
never calls Orca or Git.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from orca_placement_hook import orca_arguments
from required_checks_hook import segments_of

HOST_PROGRAMS = frozenset({"claude", "codex", "opencode", "gemini"})
NEW_WORKTREES = frozenset({"new-child", "new-top-level"})
OWN_WORKTREES = frozenset({"current", "active"})
SLACK_SECONDS = 2.0
FALLBACK_WINDOW_SECONDS = 120.0
MAX_RECORDS = 50
DEFAULT_RUN_SECONDS = 120.0
LOCK_GRACE_SECONDS = 30.0
CLAIM_SECONDS = 30
RUN_SCRIPT = Path(__file__).with_name("orca_cleanup_run.py")
DONE_STATES = frozenset({"removed", "none", "gone"})


def run_seconds() -> float:
    """The time after which a detached run ends itself and everything it started, `HEI5ENBUG_CLEANUP_RUN_SECONDS`."""
    try:
        value = float(os.environ.get("HEI5ENBUG_CLEANUP_RUN_SECONDS", DEFAULT_RUN_SECONDS))
    except ValueError:
        return DEFAULT_RUN_SECONDS
    return value if value > 0 else DEFAULT_RUN_SECONDS


def option_values(arguments: list[str], name: str) -> list[str]:
    """Return the value of each `name` option in `arguments`, written as `name value` or `name=value`."""
    values = []
    for index, token in enumerate(arguments):
        if token == name and index + 1 < len(arguments):
            values.append(arguments[index + 1])
        elif token.startswith(f"{name}="):
            values.append(token[len(name) + 1 :])
    return values


def has_option(arguments: list[str], *names: str) -> bool:
    return any(token in names or token.startswith(tuple(f"{name}=" for name in names)) for token in arguments)


def last_value(arguments: list[str], name: str) -> str | None:
    values = option_values(arguments, name)
    return values[-1] if values else None


def literal(value: str | None) -> str | None:
    return value if value and "$" not in value and "`" not in value else None


def starts_agent(command: str | None) -> bool:
    words = command.strip().split("&&")[-1].split() if command else []
    return bool(words) and os.path.basename(words[0]) in HOST_PROGRAMS


def parse_command(command: str) -> tuple[list[dict], list[dict]]:
    """Return the worktrees a command creates and the agent sessions it starts in a named worktree.

    A created worktree is `{repo, agent, worker}`; an agent start is `{selector, worker}`. The output of the command
    is never read, and a repository or worktree selector that holds a variable or a substitution is dropped.
    """
    creates: list[dict] = []
    agents: list[dict] = []
    for tokens in segments_of(command):
        arguments = orca_arguments(tokens)
        if arguments is None:
            continue
        words = [token for token in arguments if not token.startswith("-")][:2]
        target = literal(last_value(arguments, "--worktree"))
        if words == ["worktree", "create"]:
            creates.append({"repo": literal(last_value(arguments, "--repo")), "agent": has_option(arguments, "--agent"),
                            "worker": False})
        elif words == ["orchestration", "worker-start"]:
            if target in NEW_WORKTREES:
                creates.append({"repo": literal(last_value(arguments, "--repo")), "agent": True, "worker": True})
            elif target and target not in OWN_WORKTREES and has_option(arguments, "--agent", "--terminal"):
                agents.append({"selector": target, "worker": True})
        elif words == ["terminal", "create"]:
            if target and target not in OWN_WORKTREES and starts_agent(last_value(arguments, "--command")):
                agents.append({"selector": target, "worker": False})
    return creates, agents


def window_of(now: float, duration_ms: object) -> tuple[float, float]:
    """The time a command ran in: its reported duration, else a fixed span before the end, widened by a short slack."""
    if isinstance(duration_ms, (int, float)) and not isinstance(duration_ms, bool) and duration_ms >= 0:
        start = now - duration_ms / 1000
    else:
        start = now - FALLBACK_WINDOW_SECONDS
    return start - SLACK_SECONDS, now + SLACK_SECONDS


def result_path(state_path: Path) -> Path:
    return state_path.with_name(f"{state_path.stem}.cleanup.json")


def lock_path(state_path: Path) -> Path:
    return state_path.with_name(f"{state_path.stem}.cleanup.lock")


def read_results(path: Path) -> dict:
    """The run's result file, or an empty result when it is missing or unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    data = data if isinstance(data, dict) else {}
    entries = data.get("entries") if isinstance(data.get("entries"), dict) else {}
    notices = data.get("notices") if isinstance(data.get("notices"), list) else []
    removed = data.get("removed") if isinstance(data.get("removed"), list) else []
    return {"entries": entries, "notices": notices, "removed": removed}


def write_results(path: Path, results: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".orca-cleanup-", dir=path.parent)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(results, stream, ensure_ascii=False)
    os.replace(temporary, path)


def lock_is_live(path: Path) -> bool:
    """True while a run holds the lock: its process exists, or it was claimed moments ago and has not started."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - float(data["started"])
        pid = data.get("pid")
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if age > run_seconds() + LOCK_GRACE_SECONDS:
        return False
    if pid is None:
        return age < CLAIM_SECONDS
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


def run_active(state_path: Path) -> bool:
    return lock_is_live(lock_path(state_path))


def needs_run(creates: list[dict], agent_count: int, results: dict) -> bool:
    """True when a created worktree is neither removed nor kept for good, or an agent start may change a left one."""
    for create in creates:
        entry = results["entries"].get(str(create.get("seq")))
        if not isinstance(entry, dict):
            return True
        if entry.get("state") in DONE_STATES or entry.get("done") is True:
            continue
        if entry.get("state") == "left":
            if agent_count > int(entry.get("agents_seen") or 0):
                return True
            continue
        return True
    return False


def claim(lock: Path) -> bool:
    for _ in range(2):
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if lock_is_live(lock):
                return False
            lock.unlink(missing_ok=True)
            continue
        except OSError:
            return False
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"pid": None, "started": time.time()}, stream)
        return True
    return False


def start_run(state_path: Path) -> bool:
    """Start the detached run in a process session of its own, so it survives the closing of the session's terminal."""
    lock = lock_path(state_path)
    if not claim(lock):
        return False
    try:
        subprocess.Popen(
            [sys.executable, "-B", str(RUN_SCRIPT), str(state_path)],
            cwd=os.path.sep, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True, start_new_session=True,
        )
    except OSError:
        lock.unlink(missing_ok=True)
        return False
    return True


def unseen_notices(results: dict, seen: int) -> list[dict]:
    return [item for item in results["notices"]
            if isinstance(item, dict) and isinstance(item.get("seq"), int) and item["seq"] > seen
            and isinstance(item.get("text"), str)]


def notice_line(notices: list[dict]) -> str:
    return "Orca cleanup: " + " ".join(item["text"] for item in notices)
