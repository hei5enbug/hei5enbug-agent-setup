"""Run the agent subprocess in its own process group with a wall-clock limit and staged termination.

Delegated runners start their own sessions, so signalling the agent's group is not enough: the descendants of the
agent are tracked while it runs and are signalled as well, and the call returns only when none of them remain."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

EXEC_FAILURE_CODE = 127
TREE_POLL_SECONDS = 2.0
GONE_POLL_SECONDS = 0.05
KILL_CONFIRM_SECONDS = 5.0
LEFTOVER_TERM_GRACE_SECONDS = 2.0
ZOMBIE_STATE = "Z"

#: pid -> (ppid, pgid, state)
ProcessTable = dict[int, tuple[int, int, str]]
TableReader = Callable[[], ProcessTable]


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    timed_out: bool
    wall_seconds: float
    started_at: datetime
    ended_at: datetime
    error: str | None = None
    orphans_killed: int = 0
    leftover_killed: int = 0


def read_process_table() -> ProcessTable:
    """Every process as pid -> (ppid, pgid, state), from `ps`; empty when `ps` cannot run."""
    try:
        completed = subprocess.run(
            ["ps", "-A", "-o", "pid=,ppid=,pgid=,stat="], capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    table: ProcessTable = {}
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 4 and all(item.isdigit() for item in fields[:3]):
            table[int(fields[0])] = (int(fields[1]), int(fields[2]), fields[3])
    return table


def find_descendants(table: ProcessTable, roots: Iterable[int]) -> dict[int, int]:
    """pid -> pgid of every process below any root pid (the roots themselves are not included)."""
    children: dict[int, list[int]] = {}
    for pid, (ppid, _, _) in table.items():
        children.setdefault(ppid, []).append(pid)
    found: dict[int, int] = {}
    pending = list(roots)
    while pending:
        for child in children.get(pending.pop(), []):
            if child not in found:
                found[child] = table[child][1]
                pending.append(child)
    return found


class DescendantTracker:
    """Remembers every descendant of one root pid seen so far, so they can be signalled after the root is gone."""

    def __init__(self, root_pid: int, reader: TableReader = read_process_table):
        self.root_pid = root_pid
        self._reader = reader
        self.known: dict[int, int] = {}

    def refresh(self) -> None:
        table = self._reader()
        found = find_descendants(table, {self.root_pid, *self.known})
        self.known = {**self.known, **found}

    def alive(self) -> dict[int, int]:
        """The remembered descendants that still run in the same process group they were seen in."""
        table = self._reader()
        return {
            pid: pgid for pid, pgid in self.known.items()
            if pid in table and table[pid][1] == pgid and table[pid][2][:1] != ZOMBIE_STATE
        }


def _signal_group(pgid: int, signum: int) -> None:
    if pgid <= 1 or pgid == os.getpgrp():
        return
    try:
        os.killpg(pgid, signum)
    except (ProcessLookupError, PermissionError):
        pass


def _signal_pid(pid: int, signum: int) -> None:
    try:
        os.kill(pid, signum)
    except (ProcessLookupError, PermissionError):
        pass


def _signal_tracked(process: subprocess.Popen, tracker: DescendantTracker, signum: int) -> set[int]:
    """Signal the agent group and every tracked descendant group and pid still alive; return the descendant pids hit."""
    tracker.refresh()
    alive = tracker.alive()
    if process.poll() is None:
        _signal_group(process.pid, signum)
    for pgid in set(alive.values()):
        _signal_group(pgid, signum)
    for pid in alive:
        _signal_pid(pid, signum)
    return set(alive)


def _all_gone(process: subprocess.Popen, tracker: DescendantTracker) -> bool:
    return process.poll() is not None and not tracker.alive()


def _wait_gone(process: subprocess.Popen, tracker: DescendantTracker, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        if _all_gone(process, tracker):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(GONE_POLL_SECONDS)


def _wait(process: subprocess.Popen, seconds: float) -> bool:
    try:
        process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        return False
    return True


def terminate(
    process: subprocess.Popen, tracker: DescendantTracker, sigint_grace: float, sigterm_grace: float,
) -> tuple[int, list[int]]:
    """SIGINT the agent group; then SIGTERM and SIGKILL the group and every tracked descendant still alive.

    Returns the number of descendants that needed SIGTERM or SIGKILL and the pids that survived SIGKILL."""
    tracker.refresh()
    _signal_group(process.pid, signal.SIGINT)
    forced: set[int] = set()
    if not _wait_gone(process, tracker, sigint_grace):
        forced |= _signal_tracked(process, tracker, signal.SIGTERM)
        if not _wait_gone(process, tracker, sigterm_grace):
            forced |= _signal_tracked(process, tracker, signal.SIGKILL)
            _wait_gone(process, tracker, KILL_CONFIRM_SECONDS)
    process.wait()
    return len(forced), sorted(tracker.alive())


def reap_leftovers(process: subprocess.Popen, tracker: DescendantTracker) -> int:
    """After a normal exit, kill tracked descendants of this run that still run; return how many."""
    if not tracker.alive():
        return 0
    killed = _signal_tracked(process, tracker, signal.SIGTERM)
    if not _wait_gone(process, tracker, LEFTOVER_TERM_GRACE_SECONDS):
        killed |= _signal_tracked(process, tracker, signal.SIGKILL)
        _wait_gone(process, tracker, KILL_CONFIRM_SECONDS)
    return len(killed)


def _wait_tracking(process: subprocess.Popen, tracker: DescendantTracker, seconds: float, poll: float) -> bool:
    """Wait for the agent to exit within `seconds`, refreshing the descendant snapshot every `poll` seconds."""
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return process.poll() is not None
        if _wait(process, min(poll, remaining)):
            return True
        tracker.refresh()


def run_agent(
    command: Sequence[str], cwd: Path, env: Mapping[str, str], stream_path: Path, stderr_path: Path,
    wall_seconds: float, sigint_grace: float, sigterm_grace: float, poll_seconds: float = TREE_POLL_SECONDS,
) -> ProcessResult:
    started_at, begin = datetime.now(timezone.utc), time.monotonic()
    stream_path.parent.mkdir(parents=True, exist_ok=True)
    with stream_path.open("wb") as stream, stderr_path.open("wb") as errors:
        try:
            process = subprocess.Popen(
                list(command), cwd=cwd, env=dict(env), stdin=subprocess.DEVNULL, stdout=stream, stderr=errors,
                start_new_session=True,
            )
        except OSError as error:
            return ProcessResult(EXEC_FAILURE_CODE, False, 0.0, started_at, datetime.now(timezone.utc), f"cannot start: {error}")
        tracker = DescendantTracker(process.pid)
        tracker.refresh()
        timed_out = not _wait_tracking(process, tracker, wall_seconds, poll_seconds)
        orphans, leftovers, survivors = 0, 0, []
        if timed_out:
            orphans, survivors = terminate(process, tracker, sigint_grace, sigterm_grace)
        else:
            leftovers = reap_leftovers(process, tracker)
            survivors = sorted(tracker.alive())
    error = f"processes survived SIGKILL: {survivors}" if survivors else None
    return ProcessResult(
        process.returncode, timed_out, time.monotonic() - begin, started_at, datetime.now(timezone.utc), error,
        orphans, leftovers,
    )
