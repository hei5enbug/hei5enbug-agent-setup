"""Vendor-neutral subprocess runner for model-backed skill tooling.

The configured command must accept a prompt on stdin and write only the model
response to stdout. Commands are parsed with ``shlex`` and executed without a
shell. Use ``{model}`` in an argument when the command needs a model ID.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import time


RUNNER_ENV_VAR = "SKILL_BUILDER_RUNNER_COMMAND"
KILL_GRACE_SECONDS = 5.0


class RunnerError(RuntimeError):
    """Raised when a model runner is missing, invalid, or fails."""


def resolve_runner_command(command: str | None) -> str:
    """Return an explicit command or the environment-configured fallback."""
    resolved = command or os.environ.get(RUNNER_ENV_VAR)
    if not resolved:
        raise RunnerError(
            "No model runner configured. Pass --runner-command or set "
            f"{RUNNER_ENV_VAR}. The command must read the prompt from stdin "
            "and write the model response to stdout."
        )
    return resolved


def run_model(
    prompt: str,
    runner_command: str,
    model: str | None = None,
    timeout: int = 300,
) -> str:
    """Execute a model command using a portable stdin/stdout contract."""
    try:
        command = shlex.split(runner_command)
    except ValueError as exc:
        raise RunnerError(f"Invalid runner command: {exc}") from exc

    if not command:
        raise RunnerError("Runner command cannot be empty")

    rendered: list[str] = []
    for argument in command:
        if "{model}" in argument:
            if not model:
                raise RunnerError(
                    "Runner command contains {model}, but no --model value was provided"
                )
            argument = argument.replace("{model}", model)
        rendered.append(argument)

    try:
        process = subprocess.Popen(
            rendered,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise RunnerError(f"Runner executable not found: {rendered[0]}") from exc

    try:
        stdout, stderr = process.communicate(input=prompt, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        terminate_process_group(process)
        raise RunnerError(f"Runner timed out after {timeout} seconds") from exc
    except BaseException:
        terminate_process_group(process)
        raise

    if process.returncode != 0:
        stderr = stderr.strip()
        detail = f"\nstderr: {stderr}" if stderr else ""
        raise RunnerError(
            f"Runner exited with status {process.returncode}: {' '.join(rendered)}{detail}"
        )

    return stdout


def terminate_process_group(
    process: subprocess.Popen, grace_seconds: float = KILL_GRACE_SECONDS
) -> None:
    """SIGTERM the runner's whole process group, then SIGKILL whatever survives.

    The runner is started with ``start_new_session=True`` so its pid is the
    group id, which lets shell wrappers and their children be reaped too.
    macOS and Linux only.
    """
    _signal_group(process.pid, signal.SIGTERM)
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None and not _group_alive(process.pid):
            break
        time.sleep(0.05)
    _signal_group(process.pid, signal.SIGKILL)
    try:
        process.communicate(timeout=grace_seconds)
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass


def _signal_group(pgid: int, sig: signal.Signals) -> None:
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        pass


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
