from __future__ import annotations

import json
import os
from pathlib import Path

from role_runner_config import EXIT_EVIDENCE, SYNTHETIC_MODEL, RunnerError


def state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state").expanduser()


def require_heartbeat(host: str, session_id: str, message: str) -> None:
    """Require a Codex PreToolUse heartbeat, or a Claude prompt or legacy heartbeat."""
    plain = state_home() / "hei5enbug-agent-setup" / "heartbeats" / f"{host}-{session_id}"
    event_name = "PreToolUse" if host == "codex" else "UserPromptSubmit"
    heartbeat = plain.with_name(plain.name + "." + event_name)
    present = heartbeat.is_file() or (host == "claude" and plain.is_file())
    if "/" in session_id or not present:
        raise RunnerError(EXIT_EVIDENCE, message, {"heartbeat": heartbeat.as_posix(), "session": session_id})


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()


def thread_id_from(stdout: str) -> str | None:
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "thread.started":
            thread_id = event.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                return thread_id
    return None


def json_lines(path: Path):
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            yield entry


def count_tool_calls(rollout: Path) -> int:
    """Count the rollout entries that record a tool call, not counting web searches."""
    count = 0
    for entry in json_lines(rollout):
        payload = entry.get("payload")
        kind = payload.get("type") if isinstance(payload, dict) else None
        if isinstance(kind, str) and kind.endswith("_call") and kind != "web_search_call":
            count += 1
    return count


def verify_codex(stdout: str, model: str, effort: str, sandbox: str) -> dict:
    thread_id = thread_id_from(stdout)
    if thread_id is None:
        raise RunnerError(EXIT_EVIDENCE, "No thread.started event with a thread_id in the Codex output")
    sessions = codex_home() / "sessions"
    rollouts = sorted(sessions.glob(f"**/rollout-*{thread_id}.jsonl")) if sessions.is_dir() else []
    if not rollouts:
        raise RunnerError(EXIT_EVIDENCE, f"No rollout file for thread {thread_id} under {sessions}")
    rollout = rollouts[-1]
    turns = []
    for entry in json_lines(rollout):
        if entry.get("type") == "turn_context":
            payload = entry.get("payload")
            turns.append(payload if isinstance(payload, dict) else {})
    if not turns:
        raise RunnerError(EXIT_EVIDENCE, f"No turn_context entry in {rollout}", {"rollout": rollout.as_posix()})
    for turn in turns:
        if turn.get("model") != model or turn.get("effort") != effort:
            raise RunnerError(
                EXIT_EVIDENCE,
                f"turn_context names {turn.get('model')!r} with {turn.get('effort')!r}, expected {model!r} with {effort!r}",
                {"rollout": rollout.as_posix(), "turns": len(turns)},
            )
        policy = turn.get("sandbox_policy")
        sandbox_type = policy.get("type") if isinstance(policy, dict) else None
        if sandbox_type != sandbox:
            raise RunnerError(
                EXIT_EVIDENCE,
                f"turn_context names sandbox {sandbox_type!r}, expected {sandbox!r}",
                {"rollout": rollout.as_posix(), "turns": len(turns)},
            )
    return {"rollout": rollout.as_posix(), "turns": len(turns), "session": thread_id, "tool_calls": count_tool_calls(rollout)}


def claude_result(stdout: str) -> dict:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise RunnerError(EXIT_EVIDENCE, "The Claude output is not JSON") from error
    if isinstance(parsed, list):
        parsed = next((item for item in parsed if isinstance(item, dict) and item.get("type") == "result"), None)
    if not isinstance(parsed, dict):
        raise RunnerError(EXIT_EVIDENCE, "The Claude output has no result object")
    return parsed


def is_synthetic(entry: dict) -> bool:
    message = entry.get("message")
    return isinstance(message, dict) and message.get("model") == SYNTHETIC_MODEL


def verify_claude(result: dict, model: str, effort: str) -> dict:
    usage = result.get("modelUsage")
    if not isinstance(usage, dict) or set(usage) != {model}:
        found = sorted(usage) if isinstance(usage, dict) else usage
        raise RunnerError(EXIT_EVIDENCE, f"modelUsage names {found!r}, expected only {model!r}")
    session_id = result.get("session_id")
    if not isinstance(session_id, str) or not session_id or "/" in session_id:
        raise RunnerError(EXIT_EVIDENCE, "The Claude result has no usable session_id")
    projects = claude_home() / "projects"
    transcripts = sorted(projects.glob(f"*/{session_id}.jsonl")) if projects.is_dir() else []
    if not transcripts:
        raise RunnerError(EXIT_EVIDENCE, f"No transcript for session {session_id} under {projects}")
    transcript = transcripts[-1]
    assistants = [entry for entry in json_lines(transcript) if entry.get("type") == "assistant"]
    if not assistants:
        raise RunnerError(EXIT_EVIDENCE, f"No assistant entry in {transcript}", {"transcript": transcript.as_posix()})
    assistants = [entry for entry in assistants if not is_synthetic(entry)]
    if not assistants:
        raise RunnerError(
            EXIT_EVIDENCE, f"No assistant entry from a real model in {transcript}", {"transcript": transcript.as_posix()},
        )
    for entry in assistants:
        message = entry.get("message")
        entry_model = message.get("model") if isinstance(message, dict) else None
        if entry_model != model or entry.get("effort") != effort:
            raise RunnerError(
                EXIT_EVIDENCE,
                f"assistant entry names {entry_model!r} with {entry.get('effort')!r}, expected {model!r} with {effort!r}",
                {"transcript": transcript.as_posix(), "entries": len(assistants)},
            )
    return {"transcript": transcript.as_posix(), "entries": len(assistants), "session": session_id}
