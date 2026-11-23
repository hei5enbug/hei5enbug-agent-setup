"""The shape of the independent text review loop in one run: reviewer runs, and main-session turns and tokens.

A reviewer run is a `text_review.py review` call whose result shows the reviewer stage; a call that stops at the
deterministic check never reaches the reviewer. The loop starts at the first main-session request that issues either a
`text_review.py review` call or a `role_runner.py language` call, which hands the loop to a worker. Main-session turns
count the main session's model requests from that request to the end of the run, the post included, and the tokens are
those requests' tokens next to the whole main session's.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from . import codex_calls, usage
from .transcript import content_blocks

REVIEW_COMMAND = re.compile(r"""text_review\.py["']?\s+review\b""")
LOOP_START = re.compile(r"""text_review\.py["']?\s+review\b|role_runner\.py["']?\s+language\b""")
REVIEWER_STAGE = re.compile(r'\\*"stage\\*"\s*:\s*\\*"review\\*"')
TOKEN_FIELDS = ("input", "output", "cache_read", "cache_write")
NOT_STARTED = {"loop_started": False, "main_turns": 0, "main_tokens_loop": dict.fromkeys(TOKEN_FIELDS, 0)}


def command_of(call: Mapping[str, Any]) -> str:
    return str((call.get("input") or {}).get("command") or "") if call.get("name") == "Bash" else ""


def reviewer_runs(calls: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Review calls of every session: those that reached the reviewer and those that stopped at the deterministic check."""
    reached = stopped = 0
    for call in calls:
        if not REVIEW_COMMAND.search(command_of(call)):
            continue
        if REVIEWER_STAGE.search(str(call.get("result_text") or "")):
            reached += 1
        else:
            stopped += 1
    return {"reviewer_runs": reached, "check_stops": stopped}


def cache_written(request: Mapping[str, Any]) -> int:
    """Tokens written to the cache: Claude splits them by lifetime, Codex reports one figure."""
    return int(request.get("cache_write", int(request.get("cache_write_5m", 0)) + int(request.get("cache_write_1h", 0))))


def token_sums(requests: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    sums = {name: sum(int(request.get(name, 0)) for request in requests) for name in TOKEN_FIELDS if name != "cache_write"}
    return {**sums, "cache_write": sum(cache_written(request) for request in requests)}


def claude_start(events: Sequence[Mapping[str, Any]]) -> int | None:
    """Index of the first main assistant event that issues a loop-starting Bash call, or None."""
    for index, event in enumerate(events):
        if event.get("type") != "assistant" or event.get("parent_tool_use_id") is not None:
            continue
        for block in content_blocks(dict(event)):
            if block.get("type") == "tool_use" and block.get("name") == "Bash" \
                    and LOOP_START.search(str((block.get("input") or {}).get("command") or "")):
                return index
    return None


def claude_main(events: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [event for event in events if event.get("type") != "assistant" or event.get("parent_tool_use_id") is None]


def codex_start(events: Sequence[Mapping[str, Any]]) -> int | None:
    """Index of the first main-rollout call item that runs a loop-starting command, or None."""
    for index, event in enumerate(events):
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event.get("type") == "response_item" and payload.get("type") in codex_calls.CALL_TYPES \
                and any(LOOP_START.search(command) for command in codex_calls.commands_of(payload)):
            return index
    return None


def main_figures(requests: Sequence[Mapping[str, Any]], from_start: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    figures: dict[str, Any] = {"main_requests": len(requests), "main_tokens": token_sums(requests)}
    if from_start is None:
        return {**figures, **NOT_STARTED}
    return {**figures, "loop_started": True, "main_turns": len(from_start), "main_tokens_loop": token_sums(from_start)}


def claude_main_figures(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    main = claude_main(events)
    start = claude_start(main)
    return main_figures(usage.claude_requests(main), None if start is None else usage.claude_requests(main[start:]))


def codex_main_figures(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    start = codex_start(events)
    requests = usage.codex_requests(events)
    return main_figures(requests, None if start is None else usage.codex_requests(events[start:]))


def review_loop(calls: Iterable[Mapping[str, Any]], main_events: Sequence[Mapping[str, Any]], host: str) -> dict[str, Any]:
    """The loop figures of one run: the review calls of every session and the main session's turns and tokens."""
    figures = claude_main_figures(main_events) if host == "claude" else codex_main_figures(main_events)
    return {**reviewer_runs(calls), **figures}
