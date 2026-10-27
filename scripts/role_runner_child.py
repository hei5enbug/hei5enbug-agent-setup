from __future__ import annotations

import json
import os
import signal
import subprocess

from role_runner_config import ASSIGNED_ROLE_ENV, EXIT_RUN, MCP_SERVER_NAME, PARENT_SESSION_ENV, RunnerError


def parent_session(environ) -> str | None:
    """Return the session the approval guard treats as the child's parent: the inherited value, else this session's own."""
    existing = environ.get(PARENT_SESSION_ENV)
    if existing:
        return existing
    claude_id = environ.get("CLAUDE_CODE_SESSION_ID")
    if environ.get("CLAUDECODE") and claude_id:
        return f"claude:{claude_id}"
    codex_id = environ.get("CODEX_SESSION_ID") or environ.get("CODEX_THREAD_ID")
    if codex_id:
        return f"codex:{codex_id}"
    return None


def child_environment(marker: str) -> dict:
    environment = dict(os.environ)
    environment[ASSIGNED_ROLE_ENV] = marker
    parent = parent_session(environment)
    if parent is not None:
        environment[PARENT_SESSION_ENV] = parent
    return environment


def kill_group(pid: int) -> None:
    """Kill the process group the runner started for a child; one that already exited, even unreaped, is left alone."""
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_child(marker: str, command: list[str], prompt: str, cwd: str, timeout: int) -> str:
    environment = child_environment(marker)
    try:
        child = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", cwd=cwd, env=environment, start_new_session=True,
        )
    except OSError as error:
        raise RunnerError(EXIT_RUN, f"Cannot start {command[0]}: {error}") from error
    try:
        stdout, stderr = child.communicate(prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_group(child.pid)
        child.communicate()
        raise RunnerError(EXIT_RUN, f"{command[0]} exceeded the {timeout} second timeout") from None
    if child.returncode != 0:
        tail = (stderr or "").strip()[-2000:]
        raise RunnerError(EXIT_RUN, f"{command[0]} exited with {child.returncode}: {tail}")
    return stdout


def codex_mcp_off(marker: str, cwd: str, timeout: int) -> list[str]:
    """List the configured Codex MCP servers with the child's environment and return one disabling override for each."""
    try:
        listing = run_child(marker, ["codex", "mcp", "list", "--json"], "", cwd, timeout)
        servers = json.loads(listing)
    except RunnerError as error:
        raise RunnerError(EXIT_RUN, f"Cannot list the Codex MCP servers to turn them off: {error}") from error
    except json.JSONDecodeError as error:
        raise RunnerError(EXIT_RUN, "The Codex MCP server list is not JSON, so the servers cannot be turned off") from error
    if not isinstance(servers, list):
        raise RunnerError(EXIT_RUN, "The Codex MCP server list is not a list, so the servers cannot be turned off")
    names = [server.get("name") if isinstance(server, dict) else None for server in servers]
    for name in names:
        if not isinstance(name, str) or not MCP_SERVER_NAME.fullmatch(name):
            raise RunnerError(EXIT_RUN, f"The Codex MCP server name {name!r} cannot be turned off safely")
    flags: list[str] = []
    for name in names:
        flags += ["-c", f"mcp_servers.{name}.enabled=false"]
    return flags
