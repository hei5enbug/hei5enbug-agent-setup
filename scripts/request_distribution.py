"""Count delegated runs and retries per user request from host session records and derive the default request caps.

A request runs from one user prompt to the next. A delegated run is a plugin agent launch or a role runner child run.
A retry is a launch of the same agent type after an error, or a role runner run of the same role after a non-zero exit.
The output holds only the distribution of the counts, never session content.

    python3 scripts/request_distribution.py --through 2026-11-16 --claude-dir <dir> --codex-home <dir> --out <file>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

WINDOW_DAYS = 30
AGENT_TOOLS = ("Agent", "Task")
ROLE_RUNNER = re.compile(r"role_runner\.py\s+([a-z]+)")
AGENT_NAME = re.compile(r"--name\s+([A-Za-z0-9_:.-]+)")
ASSIGNMENT_FLAG = re.compile(r"--assignment\b")
EXIT_NONZERO = re.compile(r'"exit":\s*[1-9]')
SYSTEM_PREFIXES = ("This session is being continued", "Stop hook feedback", "<task-notification", "<command-")
CODEX_CONTEXT_PREFIXES = ("# AGENTS.md", "<")
EXCLUDED_PATH_PARTS = ("e2e-runs",)

PROMPT = "prompt"
LAUNCH = "launch"
RESULT = "result"


def event_time(event: dict) -> datetime | None:
    stamp = event.get("timestamp")
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00")) if isinstance(stamp, str) else None
    except ValueError:
        return None
    return parsed if parsed is None or parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def text_of(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(block.get("text", "") for block in content if isinstance(block, dict) and isinstance(block.get("text"), str))
    return ""


def runner_launches(command: str, call_id: str) -> Iterator[tuple]:
    """One launch per assignment of a role runner command, keyed by role (and agent name for the agent target)."""
    match = ROLE_RUNNER.search(command)
    if not match:
        return
    role = match.group(1)
    name = AGENT_NAME.search(command) if role == "agent" else None
    kind = f"role:{role}" + (f":{name.group(1)}" if name else "")
    for index in range(max(1, len(ASSIGNMENT_FLAG.findall(command)))):
        yield LAUNCH, kind, f"{call_id}#{index}", None


def claude_prompt(event: dict) -> bool:
    if event.get("type") != "user" or event.get("isMeta") or event.get("isSidechain"):
        return False
    content = (event.get("message") or {}).get("content")
    if isinstance(content, list) and any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content):
        return False
    text = text_of(content).strip()
    if not text or text.startswith(SYSTEM_PREFIXES):
        return False
    origin = event.get("turnOrigin")
    return origin == "human" or (origin is None and event.get("promptSource") is None)


def claude_events(lines: Iterable[dict]) -> Iterator[tuple]:
    """Normalized (kind, name or id, id, error) tuples of a Claude Code session record."""
    runner_calls: dict[str, int] = {}
    for event in lines:
        at = event_time(event)
        if claude_prompt(event):
            yield PROMPT, None, at, None
            continue
        content = (event.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict) or event.get("isSidechain"):
                continue
            if event.get("type") == "assistant" and block.get("type") == "tool_use":
                call_id, tool_input = str(block.get("id")), block.get("input") or {}
                if block.get("name") in AGENT_TOOLS:
                    yield LAUNCH, str(tool_input.get("subagent_type") or "general-purpose"), call_id, None
                elif block.get("name") == "Bash":
                    launches = list(runner_launches(str(tool_input.get("command") or ""), call_id))
                    runner_calls[call_id] = len(launches)
                    yield from launches
            elif event.get("type") == "user" and block.get("type") == "tool_result":
                call_id = str(block.get("tool_use_id"))
                failed = bool(block.get("is_error")) or bool(EXIT_NONZERO.search(text_of(block.get("content"))))
                for index in range(runner_calls.get(call_id, 0)):
                    yield RESULT, None, f"{call_id}#{index}", failed
                if call_id not in runner_calls:
                    yield RESULT, None, call_id, failed


def codex_prompt(payload: dict) -> bool:
    if payload.get("type") != "message" or payload.get("role") != "user":
        return False
    text = text_of(payload.get("content")).strip()
    return bool(text) and not text.startswith(CODEX_CONTEXT_PREFIXES)


def codex_events(lines: Iterable[dict]) -> Iterator[tuple]:
    """Normalized tuples of a Codex rollout; a session started by `codex exec` is a role runner child, not a request."""
    runner_calls: dict[str, int] = {}
    for event in lines:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event.get("type") == "session_meta" and payload.get("source") == "exec":
            return
        if event.get("type") != "response_item":
            continue
        kind, call_id = payload.get("type"), str(payload.get("call_id"))
        if codex_prompt(payload):
            yield PROMPT, None, event_time(event), None
        elif kind == "function_call" and payload.get("name") == "spawn_agent":
            try:
                arguments = json.loads(payload.get("arguments") or "{}")
            except ValueError:
                arguments = {}
            agent = arguments.get("agent_type") if isinstance(arguments, dict) else None
            yield LAUNCH, str(agent or "default"), call_id, None
        elif kind in ("custom_tool_call", "function_call"):
            launches = list(runner_launches(str(payload.get("input") or payload.get("arguments") or ""), call_id))
            runner_calls[call_id] = len(launches)
            yield from launches
        elif kind in ("custom_tool_call_output", "function_call_output"):
            output = str(payload.get("output"))
            failed = bool(EXIT_NONZERO.search(output)) or '"error"' in output
            for index in range(runner_calls.get(call_id, 0)):
                yield RESULT, None, f"{call_id}#{index}", failed
            if call_id not in runner_calls:
                yield RESULT, None, call_id, failed


def count_requests(events: Iterable[tuple], since: datetime | None = None) -> list[dict]:
    """The runs and retries of each request in a normalized event stream; launches before the first prompt count nowhere."""
    requests: list[dict] = []
    current: dict | None = None
    for kind, name, ident, failed in events:
        if kind == PROMPT:
            if current is not None:
                requests.append(current)
            current = {"runs": 0, "retries": 0, "last": {}, "calls": {}, "in_window": since is None or ident is None or ident >= since}
        elif current is None:
            continue
        elif kind == LAUNCH:
            current["retries"] += 1 if current["last"].get(name) == "error" else 0
            current["runs"] += 1
            current["last"][name] = "running"
            current["calls"][ident] = name
        elif kind == RESULT and ident in current["calls"]:
            current["last"][current["calls"][ident]] = "error" if failed else "ok"
    if current is not None:
        requests.append(current)
    return [{"runs": item["runs"], "retries": item["retries"]} for item in requests if item["in_window"]]


def read_lines(path: Path) -> Iterator[dict]:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict):
                    yield event
    except OSError:
        return


def session_files(claude_dirs: Iterable[Path], codex_homes: Iterable[Path], since: datetime) -> Iterator[tuple[str, Path]]:
    cutoff = since.timestamp()
    pairs = [("claude", base / "projects", "*/*.jsonl") for base in claude_dirs]
    pairs += [("codex", base / "sessions", "*/*/*/*.jsonl") for base in codex_homes]
    for host, root, pattern in pairs:
        for path in sorted(root.glob(pattern)):
            if any(part in str(path.relative_to(root)) for part in EXCLUDED_PATH_PARTS):
                continue
            try:
                if path.stat().st_mtime >= cutoff:
                    yield host, path
            except OSError:
                continue


def distribution(requests: list[dict], through: date) -> dict:
    runs, retries = [item["runs"] for item in requests], [item["retries"] for item in requests]
    with_runs = sum(1 for count in runs if count > 0)
    record = {
        "window_days": WINDOW_DAYS,
        "through": through.isoformat(),
        "requests": len(requests),
        "requests_with_delegated_run": with_runs,
        "runs_per_request": histogram(runs),
        "retries_per_request": histogram(retries),
        "largest_runs": max(runs, default=0),
        "largest_retries": max(retries, default=0),
    }
    record.update(default_caps(record))
    return record


def histogram(counts: list[int]) -> dict[str, int]:
    return {str(value): counts.count(value) for value in sorted(set(counts))}


def default_caps(record: dict) -> dict:
    """The run cap is the smallest multiple of ten above the largest count and the retry cap is the largest count plus one; both are 0 without a delegated run."""
    if record["requests_with_delegated_run"] == 0:
        return {"run_cap_default": 0, "retry_cap_default": 0, "reason": "no request in the window held a delegated run"}
    return {"run_cap_default": (record["largest_runs"] // 10 + 1) * 10, "retry_cap_default": record["largest_retries"] + 1}


def collect(claude_dirs: Iterable[Path], codex_homes: Iterable[Path], through: date) -> tuple[list[dict], int]:
    since = datetime.combine(through - timedelta(days=WINDOW_DAYS), time.min, tzinfo=timezone.utc)
    requests: list[dict] = []
    sessions = 0
    for host, path in session_files(claude_dirs, codex_homes, since):
        events = claude_events(read_lines(path)) if host == "claude" else codex_events(read_lines(path))
        found = count_requests(events, since)
        sessions += 1 if found else 0
        requests.extend(found)
    return requests, sessions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--through", required=True, type=date.fromisoformat)
    parser.add_argument("--claude-dir", action="append", default=[], type=Path)
    parser.add_argument("--codex-home", action="append", default=[], type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    requests, sessions = collect(args.claude_dir, args.codex_home, args.through)
    record = {**distribution(requests, args.through), "sessions_with_requests": sessions}
    text = json.dumps(record, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
