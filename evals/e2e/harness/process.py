"""Run the agent subprocess in its own process group with a wall-clock limit and staged termination.

Delegated runners start their own sessions, so signalling the agent's group is not enough: the descendants of the
agent are tracked while it runs and are signalled as well, and the call returns only when none of them remain."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

EXEC_FAILURE_CODE = 127
TREE_POLL_SECONDS = 2.0
GONE_POLL_SECONDS = 0.05
KILL_CONFIRM_SECONDS = 5.0
LEFTOVER_TERM_GRACE_SECONDS = 2.0
TERMINATE_GRACE_SECONDS = 5.0
DRAIN_SECONDS = 5.0
ZOMBIE_STATE = "Z"

#: pid -> (ppid, pgid, state)
ProcessTable = dict[int, tuple[int, int, str]]
TableReader = Callable[[], ProcessTable]


class GradingInterrupted(Exception):
    """Grading stopped because the harness was interrupted; the grader and its descendants were ended.

    `no_verdict` lets a check that raises it stop grading instead of being recorded as a failed check."""

    no_verdict = True


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
    interrupted: bool = False


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


def _wait_tracking(
    process: subprocess.Popen, tracker: DescendantTracker, seconds: float, poll: float,
    interrupt: threading.Event | None = None,
) -> bool:
    """Wait for the agent to exit within `seconds` and until `interrupt` is set, refreshing the descendant
    snapshot every `poll` seconds; True only when the agent exited."""
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or (interrupt is not None and interrupt.is_set()):
            return process.poll() is not None
        if _wait(process, min(poll, remaining)):
            return True
        tracker.refresh()


def run_agent(
    command: Sequence[str], cwd: Path, env: Mapping[str, str], stream_path: Path, stderr_path: Path,
    wall_seconds: float, sigint_grace: float, sigterm_grace: float, poll_seconds: float = TREE_POLL_SECONDS,
    interrupt: threading.Event | None = None, append: bool = False,
) -> ProcessResult:
    started_at, begin = datetime.now(timezone.utc), time.monotonic()
    stream_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "ab" if append else "wb"
    with stream_path.open(mode) as stream, stderr_path.open(mode) as errors:
        try:
            process = subprocess.Popen(
                list(command), cwd=cwd, env=dict(env), stdin=subprocess.DEVNULL, stdout=stream, stderr=errors,
                start_new_session=True,
            )
        except OSError as error:
            return ProcessResult(EXEC_FAILURE_CODE, False, 0.0, started_at, datetime.now(timezone.utc), f"cannot start: {error}")
        tracker = DescendantTracker(process.pid)
        tracker.refresh()
        stopped = not _wait_tracking(process, tracker, wall_seconds, poll_seconds, interrupt)
        interrupted = stopped and interrupt is not None and interrupt.is_set()
        timed_out = stopped and not interrupted
        orphans, leftovers, survivors = 0, 0, []
        if stopped:
            orphans, survivors = terminate(process, tracker, sigint_grace, sigterm_grace)
        else:
            leftovers = reap_leftovers(process, tracker)
            survivors = sorted(tracker.alive())
    error = f"processes survived SIGKILL: {survivors}" if survivors else None
    return ProcessResult(
        process.returncode, timed_out, time.monotonic() - begin, started_at, datetime.now(timezone.utc), error,
        orphans, leftovers, interrupted,
    )


def run_cleaning_tree(
    command: list[str], *, timeout: float, poll_seconds: float = TREE_POLL_SECONDS, input: str | None = None,
    cwd: Path | None = None, env: Mapping[str, str] | None = None, encoding: str | None = None, errors: str | None = None,
    interrupt: threading.Event | None = None, **_: Any,
) -> subprocess.CompletedProcess:
    """Run `command` capturing text output; on timeout end it and every descendant, even in other sessions, then raise.

    When `interrupt` is set the same cleanup runs and GradingInterrupted is raised, without waiting for the timeout."""
    process = subprocess.Popen(
        command, cwd=cwd, env=None if env is None else dict(env), stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding=encoding, errors=errors, start_new_session=True,
    )
    tracker = DescendantTracker(process.pid)
    deadline, pending = time.monotonic() + timeout, input
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or (interrupt is not None and interrupt.is_set()):
            break
        try:
            stdout, stderr = process.communicate(pending, timeout=min(poll_seconds, remaining))
        except subprocess.TimeoutExpired:
            pending = None
            tracker.refresh()
            continue
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    terminate(process, tracker, TERMINATE_GRACE_SECONDS, TERMINATE_GRACE_SECONDS)
    try:
        process.communicate(timeout=DRAIN_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    if interrupt is not None and interrupt.is_set():
        raise GradingInterrupted("grading stopped by a harness interrupt")
    raise subprocess.TimeoutExpired(command, timeout)
