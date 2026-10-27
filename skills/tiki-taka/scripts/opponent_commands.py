from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from opponent_state import CLAUDE_MODEL, CODEX_MODEL, RunnerError, StatePaths, helper_path


def supervisor_command(
    provider: str,
    repo: Path,
    prompt: Path,
    output: Path,
    events: Path,
    log: Path,
    paths: StatePaths,
    exchange: int,
    maximum: int,
    model: str,
    args: argparse.Namespace,
    participant_command: list[str],
) -> list[str]:
    return [
        sys.executable,
        str(helper_path("stream_agent.py")),
        "--provider",
        provider,
        "--repo",
        str(repo),
        "--prompt-file",
        str(prompt),
        "--output-file",
        str(output),
        "--events-file",
        str(events),
        "--log-file",
        str(log),
        "--progress-file",
        str(paths.progress),
        "--uncertain-file",
        str(paths.uncertain),
        "--exchange",
        str(exchange),
        "--max-exchanges",
        str(maximum),
        "--model",
        model,
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--heartbeat-seconds",
        str(args.heartbeat_seconds),
        "--",
        *participant_command,
    ]


def show_failure_log(log: Path) -> None:
    try:
        data = log.read_bytes()[-4096:]
    except OSError:
        return
    if data:
        print(data.decode("utf-8", errors="replace"), file=sys.stderr, end="")


def run_supervised(
    command: list[str], log: Path, allow_failure: bool = False
) -> int:
    result = subprocess.run(command, check=False)
    if result.returncode != 0 and not allow_failure:
        show_failure_log(log)
        raise RunnerError(f"반대쪽 에이전트 호출이 실패했습니다({result.returncode}).")
    return result.returncode


MCP_SERVER_NAME = re.compile(r"[A-Za-z0-9_-]+")
MCP_LIST_TIMEOUT_SECONDS = 60


def codex_mcp_off(repo: Path) -> list[str]:
    """Codex가 설정한 MCP 서버마다 끄는 -c 설정을 만든다. 목록을 읽지 못하면 MCP를 켠 채 실행하지 않는다.

    목록 조회는 상대 응답이 아니므로 응답 제한 시간과 별개의 제한 시간을 쓴다."""
    try:
        completed = subprocess.run(
            ["codex", "mcp", "list", "--json"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=MCP_LIST_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RunnerError(f"Codex MCP 서버 목록을 읽지 못해 서버를 끌 수 없습니다: {error}") from error
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip()[-500:]
        raise RunnerError(
            f"Codex MCP 서버 목록을 읽지 못해 서버를 끌 수 없습니다({completed.returncode}): {detail}"
        )
    try:
        servers = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RunnerError("Codex MCP 서버 목록이 JSON이 아니어서 서버를 끌 수 없습니다.") from error
    if not isinstance(servers, list):
        raise RunnerError("Codex MCP 서버 목록이 목록 형식이 아니어서 서버를 끌 수 없습니다.")
    flags: list[str] = []
    for server in servers:
        name = server.get("name") if isinstance(server, dict) else None
        if not isinstance(name, str) or not MCP_SERVER_NAME.fullmatch(name):
            raise RunnerError(f"Codex MCP 서버 이름 {name!r}을 안전하게 끌 수 없습니다.")
        flags.extend(["-c", f"mcp_servers.{name}.enabled=false"])
    return flags


def codex_participant_command(
    repo: Path,
    output: Path,
    effort: str,
    session_id: str,
    mcp_off: list[str],
) -> list[str]:
    if not session_id:
        return [
            "codex",
            "exec",
            "-m",
            CODEX_MODEL,
            "-c",
            f"model_reasoning_effort={effort}",
            "-s",
            "read-only",
            "-C",
            str(repo),
            *mcp_off,
            "--json",
            "-o",
            str(output),
            "-",
        ]
    return [
        "codex",
        "exec",
        "resume",
        "-m",
        CODEX_MODEL,
        "-c",
        f"model_reasoning_effort={effort}",
        "-c",
        'sandbox_mode="read-only"',
        *mcp_off,
        "--json",
        "-o",
        str(output),
        session_id,
        "-",
    ]


def claude_participant_command(
    effort: str,
    session_id: str,
    active_model: str,
    first_call: bool,
) -> list[str]:
    command = ["claude", "-p"]
    if first_call:
        command.extend(["--session-id", session_id, "--model", CLAUDE_MODEL])
    else:
        command.extend(["--resume", session_id, "--model", active_model])
    command.extend(
        [
            "--effort",
            effort,
            "--permission-mode",
            "plan",
            "--output-format",
            "stream-json",
            "--verbose",
            "--strict-mcp-config",
        ]
    )
    return command
