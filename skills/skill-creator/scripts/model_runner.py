"""Vendor-neutral subprocess runner for model-backed skill tooling.

The configured command must accept a prompt on stdin and write only the model
response to stdout. Commands are parsed with ``shlex`` and executed without a
shell. Use ``{model}`` in an argument when the command needs a model ID.
"""

from __future__ import annotations

import os
import shlex
import subprocess


RUNNER_ENV_VAR = "SKILL_CREATOR_RUNNER_COMMAND"


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
        result = subprocess.run(
            rendered,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RunnerError(f"Runner executable not found: {rendered[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RunnerError(f"Runner timed out after {timeout} seconds") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()
        detail = f"\nstderr: {stderr}" if stderr else ""
        raise RunnerError(
            f"Runner exited with status {result.returncode}: {' '.join(rendered)}{detail}"
        )

    return result.stdout
