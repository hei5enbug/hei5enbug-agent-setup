"""One agent conversation with the scripted user: the first turn, then a resumed turn for each plain-text question that ends a turn.

A question asked through the question tool is answered inside the turn by the approver server. A turn that ends with a question
in plain text is answered here: the text of the turn is read from the stream, `scripted_user.respond` picks the reply, and the
session is resumed with it. Every turn appends to the same stream and stderr files. The run stops when a turn does not end with
a question, when the sheet gives no reply, when the agent or the harness stopped a turn, or at the sheet's exchange limit."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import scripted_user, transcript
from .config import HOST_CODEX
from .process import ProcessResult, run_agent

ResumeArgv = Callable[[str, str], list[str]]
TurnRunner = Callable[..., ProcessResult]


def new_events(path: Path, offset: int) -> tuple[list[dict[str, Any]], int]:
    """The stream events written after byte `offset`, and the new end of the file."""
    try:
        data = path.read_bytes()
    except OSError:
        return [], offset
    events = []
    for line in data[offset:].decode("utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events, len(data)


def codex_messages(events: Sequence[Mapping[str, Any]]) -> list[str]:
    found = []
    for event in events:
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, Mapping) and item.get("type") == "agent_message":
            if str(item.get("text", "")).strip():
                found.append(str(item["text"]))
    return found


def turn_texts(events: list[dict[str, Any]], host: str) -> list[str]:
    return codex_messages(events) if host == HOST_CODEX else transcript.assistant_texts(events)


def final_text(events: list[dict[str, Any]], host: str) -> str:
    """The answer the turn ended with: the last agent message of Codex, or the result of a Claude Code turn."""
    if host == HOST_CODEX:
        texts = codex_messages(events)
        return texts[-1] if texts else ""
    result = transcript.result_event(events) or {}
    answer = result.get("result")
    return answer if isinstance(answer, str) else ""


def session_id(events: Sequence[Mapping[str, Any]], host: str) -> str | None:
    key, kind = ("thread_id", "thread.started") if host == HOST_CODEX else ("session_id", None)
    for event in events:
        if (kind is None or event.get("type") == kind) and isinstance(event.get(key), str) and event[key]:
            return str(event[key])
    return None


def turn_failed(events: Sequence[Mapping[str, Any]], host: str) -> bool:
    if host == HOST_CODEX:
        return any(event.get("type") in ("turn.failed", "error") for event in events)
    result = transcript.result_event(list(events)) or {}
    return not result or bool(result.get("is_error"))


def merge(results: Sequence[ProcessResult]) -> ProcessResult:
    """One result for the whole conversation: the first start, the last end, the summed time, the last exit code."""
    first, last = results[0], results[-1]
    errors = [item.error for item in results if item.error]
    return ProcessResult(
        last.returncode, any(item.timed_out for item in results), sum(item.wall_seconds for item in results),
        first.started_at, last.ended_at, "; ".join(errors) or None, sum(item.orphans_killed for item in results),
        sum(item.leftover_killed for item in results), any(item.interrupted for item in results),
    )


def run_conversation(
    *, first_argv: Sequence[str], resume_argv: ResumeArgv, host: str, cwd: Path, env: Mapping[str, str], stream_path: Path,
    stderr_path: Path, wall_seconds: float, sigint_grace: float, sigterm_grace: float, sheet: scripted_user.Sheet,
    log_path: Path, interrupt: threading.Event | None = None, run_turn: TurnRunner = run_agent,
) -> ProcessResult:
    """Run the first turn and every resumed turn; return the merged result. The wall-clock limit covers all turns."""
    results: list[ProcessResult] = []
    argv, offset, begin = list(first_argv), 0, time.monotonic()
    while True:
        remaining = wall_seconds - (time.monotonic() - begin)
        proc = run_turn(argv, cwd, env, stream_path, stderr_path, max(remaining, 1.0), sigint_grace, sigterm_grace,
                        interrupt=interrupt, append=bool(results))
        results.append(proc)
        events, offset = new_events(stream_path, offset)
        if proc.timed_out or proc.interrupted or proc.returncode != 0 or turn_failed(events, host):
            break
        answer = final_text(events, host)
        session = session_id(events, host) or session_id(new_events(stream_path, 0)[0], host)
        asked = scripted_user.load_log(log_path)
        if not session or not scripted_user.ends_with_question(answer) or len(asked) >= sheet.max_exchanges:
            break
        specification = "\n\n".join(turn_texts(events, host)) or answer
        exchange = scripted_user.respond(sheet, answer, scripted_user.KIND_TEXT, specification,
                                         scripted_user.approved_before(asked))
        scripted_user.log_exchange(log_path, exchange, specification if exchange.approval else None, cwd)
        if exchange.reply is None:
            break
        argv = resume_argv(session, exchange.reply)
    return merge(results)


def claude_resume(first_argv: Sequence[str]) -> ResumeArgv:
    """Resume a Claude Code session with the same flags: the prompt after `--` is replaced and `--resume` names the session."""
    flags = list(first_argv[:-2])
    return lambda session, reply: [*flags, "--resume", session, "--", reply]
