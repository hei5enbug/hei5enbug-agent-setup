"""Per-run measures of the independent text review loop, read from a run's saved records: the reviewer runs, the main-session
turns from the first review to the end of the session, and the main session's tokens."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import codex_calls, collect, transcript
from .codex_host import session_start
from .matrix import read_json

REVIEW_COMMAND = re.compile(r"text_review\.py[\"']?(?:\s+-\S+)*\s+review\b")
REVIEW_STAGE = re.compile(r'\\?"stage\\?"\s*:\s*\\?"review\\?"')
TOKEN_FIELDS = ("input", "output", "cache_read", "cache_write")
CLAUDE_MAIN = "main"
CODEX_MAIN = "codex:main"


def run_calls(result_dir: Path) -> list[Mapping[str, Any]]:
    """Every tool call of the run: the view's calls and those of the Claude role runner sessions, which the view leaves out."""
    calls = list((read_json(result_dir / "view.json", {}) or {}).get("tool_calls") or [])
    for record in collect.load_runner_transcripts(result_dir / "transcripts" / "runner"):
        calls.extend(transcript.collect_calls(record["events"], {}).values())
    return calls


def review_runs(calls: Sequence[Mapping[str, Any]]) -> int:
    """The `text_review.py review` runs that reached the reviewer: a run that stopped at the text check does not count."""
    return sum(1 for call in calls if call.get("name") == "Bash" and REVIEW_COMMAND.search(str((call.get("input") or {}).get("command", "")))
               and REVIEW_STAGE.search(str(call.get("result_text", ""))))


def claude_main_turns(events: Sequence[Mapping[str, Any]]) -> int:
    """The main-session assistant messages from the one that ran the first review to the last; 0 when none ran a review."""
    order: list[str] = []
    first: int | None = None
    for event in events:
        if event.get("type") != "assistant" or event.get("parent_tool_use_id") is not None:
            continue
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        key = str(message.get("id") or event.get("uuid"))
        if key not in order:
            order.append(key)
        if first is None and any(block.get("type") == "tool_use" and block.get("name") == "Bash"
                                 and REVIEW_COMMAND.search(str((block.get("input") or {}).get("command", "")))
                                 for block in transcript.content_blocks(dict(event))):
            first = order.index(key)
    return 0 if first is None else len(order) - first


def codex_main_turns(events: Sequence[Mapping[str, Any]]) -> int:
    """The main session's model requests from the one that ran the first review to the last; 0 when none ran a review."""
    requests, previous_total, before = 0, None, None
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event.get("type") == "response_item" and payload.get("type") in codex_calls.CALL_TYPES and before is None:
            if any(REVIEW_COMMAND.search(command) for command in codex_calls.commands_of(payload)):
                before = requests
        if event.get("type") != "event_msg" or payload.get("type") != "token_count":
            continue
        info = payload.get("info")
        if not isinstance(info, dict) or not isinstance(info.get("last_token_usage"), dict):
            continue
        total = info.get("total_token_usage")
        if total is not None and total == previous_total:
            continue
        previous_total = total
        requests += 1
    return 0 if before is None else requests - before


def main_tokens(metrics: Mapping[str, Any], host: str) -> int | None:
    """The main session's tokens over the whole run, cache reads and writes included; None when the metrics hold none."""
    report = (metrics.get("tokens") or {}).get("codex" if host == "codex" else "claude") or {}
    by_model = report.get("codex:main" if host == "codex" else CLAUDE_MAIN)
    if not isinstance(by_model, dict) or not by_model:
        return None
    return sum(int(usage.get(name, 0)) for usage in by_model.values() for name in TOKEN_FIELDS)


def main_turns(result_dir: Path, host: str) -> int:
    if host == "codex":
        rollouts = sorted(collect.load_rollouts(result_dir / "codex", {}), key=session_start)
        return codex_main_turns(rollouts[0]["events"]) if rollouts else 0
    return claude_main_turns(transcript.read_jsonl(result_dir / "stream.jsonl"))


def measures(result_dir: Path, host: str) -> dict[str, int | None]:
    """`review_runs`, `main_turns`, and `main_tokens` of one run."""
    metrics = read_json(result_dir / "metrics.json", {}) or {}
    return {"review_runs": review_runs(run_calls(result_dir)), "main_turns": main_turns(result_dir, host),
            "main_tokens": main_tokens(metrics, host)}
