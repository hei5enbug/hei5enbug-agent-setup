"""Run the agent subprocess in its own process group with a wall-clock limit and staged termination."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

EXEC_FAILURE_CODE = 127


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    timed_out: bool
    wall_seconds: float
    started_at: datetime
    ended_at: datetime
    error: str | None = None


def _signal_group(pid: int, signum: int) -> None:
    try:
        os.killpg(pid, signum)
    except (ProcessLookupError, PermissionError):
        pass


def _wait(process: subprocess.Popen, seconds: float) -> bool:
    try:
        process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        return False
    return True


def terminate(process: subprocess.Popen, sigint_grace: float, sigterm_grace: float) -> None:
    """SIGINT, then SIGTERM, then SIGKILL the whole group, waiting a grace period after each signal."""
    for signum, grace in ((signal.SIGINT, sigint_grace), (signal.SIGTERM, sigterm_grace)):
        _signal_group(process.pid, signum)
        if _wait(process, grace):
            break
    _signal_group(process.pid, signal.SIGKILL)
    process.wait()


def run_agent(
    command: Sequence[str], cwd: Path, env: Mapping[str, str], stream_path: Path, stderr_path: Path,
    wall_seconds: float, sigint_grace: float, sigterm_grace: float,
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
        timed_out = not _wait(process, wall_seconds)
        if timed_out:
            terminate(process, sigint_grace, sigterm_grace)
    return ProcessResult(process.returncode, timed_out, time.monotonic() - begin, started_at, datetime.now(timezone.utc))
