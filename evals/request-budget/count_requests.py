"""Count delegated runs and retries per user request in Claude Code and Codex session records.

A request runs from one user prompt to the next. A delegated run is an `Agent` or `spawn_agent` launch of an agent type
the plugin does not hide, or one assignment and result pair of a `role_runner.py` call. A retry is a launch of a key
after a run of that key ended in an error: an agent type whose launch returned an error, or a role runner role whose
status line shows a non-zero exit. The same counting rules the plugin applies at run time, `record_launch` and
`record_failure` of `scripts/request_budget.py`, decide each retry.

Only counts leave this script: the distribution of requests per count and the largest count. Role runner children and
Codex subagent threads are skipped, because they are not user requests, and so are sessions that ran in a temporary
folder, which are evaluation runs. A run a child started therefore counts for no request here.

    python3 evals/request-budget/count_requests.py --end 2026-11-17 --days 30 --out distribution.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import approval_state_store as store  # noqa: E402
import request_budget  # noqa: E402

ROLE_RUNNER = re.compile(r"role_runner\.py\s+((?!-)[\w-]+)")
AGENT_NAME = re.compile(r"--name(?:\s+|=)([\w:.-]+)")
ASSIGNMENT = re.compile(r"--assignment(?:\s|=)")
EXIT_FIELD = re.compile(r'\\*"exit\\*"\s*:\s*(\d+)')
ROLE_FIELD = re.compile(r'\\*"role\\*"\s*:\s*\\*"([\w-]+)')
CHILD_PROMPT = re.compile(r'under the \\*"Assigned workers\\*" rules|^You are Codex acting as a read-only')
SYSTEM_PROMPT = re.compile(r"^\s*<(command-|local-command|task-notification|system-reminder|bash-)")
TEMPORARY_CWD = re.compile(r"^(/private)?/(tmp|var/folders)/|/harness-eval/")
SPAWN_TOOLS = frozenset({"Agent", "Task", "spawn_agent"})
CALL_TYPES = frozenset({"function_call", "local_shell_call", "custom_tool_call"})
OUTPUT_TYPES = frozenset({"function_call_output", "local_shell_call_output", "custom_tool_call_output"})


def blocks(event: dict[str, Any]) -> list[dict[str, Any]]:
    content = (event.get("message") or {}).get("content")
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def result_text(content: Any) -> str:
    if isinstance(content, list):
        return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return "" if content is None else str(content)


def runner_launches(command: str) -> list[str]:
    """The keys of the runs a Bash command starts through `role_runner.py`: one per assignment pair."""
    found = ROLE_RUNNER.search(command)
    if found is None:
        return []
    role = found.group(1)
    if role == "agent":
        named = AGENT_NAME.search(command)
        role = named.group(1) if named else role
    return [role] * max(1, len(ASSIGNMENT.findall(command)))


def failed_roles(text: str) -> list[str]:
    """The roles of the role runner status lines in a result that show a non-zero exit."""
    roles = []
    for line in text.splitlines():
        exit_code, role = EXIT_FIELD.search(line), ROLE_FIELD.search(line)
        if exit_code and role and int(exit_code.group(1)) != 0:
            roles.append(role.group(1))
    return roles


class Tally:
    """The requests of one session: the counts of the open request and the closed ones."""

    def __init__(self) -> None:
        self.closed: list[tuple[int, int]] = []
        self.open: dict[str, Any] | None = None
        self.calls: dict[str, tuple[str, list[str]]] = {}

    def prompt(self, counted: bool) -> None:
        if self.open is not None and self.open["counted"]:
            self.closed.append((self.open["delegated"]["runs"], self.open["delegated"]["retries"]))
        self.open = {"delegated": store.fresh_delegated(), "counted": counted}

    def launch(self, call_id: str, kind: str, keys: list[str]) -> None:
        if self.open is None:
            return
        for key in keys:
            request_budget.record_launch(self.open["delegated"], key)
        self.calls[call_id] = (kind, keys)

    def result(self, call_id: str, text: str, is_error: bool) -> None:
        if self.open is None or call_id not in self.calls:
            return
        kind, keys = self.calls[call_id]
        if kind == "agent":
            failing = keys[:1] if is_error else []
        else:
            failing = failed_roles(text) or (keys[:1] if is_error else [])
        for key in failing:
            request_budget.record_failure(self.open["delegated"], key)

    def finish(self) -> list[tuple[int, int]]:
        self.prompt(False)
        return self.closed


def hidden(agent: str) -> bool:
    return request_budget.HIDDEN_AGENTS.match(agent) is not None


def claude_session(events: Iterable[dict[str, Any]], start: datetime, end: datetime) -> list[tuple[int, int]]:
    tally, first = Tally(), True
    for event in events:
        if event.get("isSidechain"):
            continue
        if TEMPORARY_CWD.search(str(event.get("cwd") or "")):
            return []
        if event.get("type") == "user" and event.get("isMeta") is not True:
            content = (event.get("message") or {}).get("content")
            text = content if isinstance(content, str) else "\n".join(
                str(block.get("text", "")) for block in blocks(event) if block.get("type") == "text"
            )
            if text.strip() and not SYSTEM_PROMPT.match(text):
                if first and CHILD_PROMPT.search(text):
                    return []
                first = False
                moment = moment_of(event.get("timestamp"))
                tally.prompt(moment is not None and start <= moment < end)
        for block in blocks(event):
            if event.get("type") == "assistant" and block.get("type") == "tool_use":
                name, tool_input, call_id = block.get("name"), block.get("input") or {}, str(block.get("id"))
                if name in SPAWN_TOOLS:
                    agent = request_budget.agent_key(tool_input)
                    if not hidden(agent):
                        tally.launch(call_id, "agent", [agent])
                elif name == "Bash":
                    keys = runner_launches(str(tool_input.get("command") or ""))
                    if keys:
                        tally.launch(call_id, "runner", keys)
            elif event.get("type") == "user" and block.get("type") == "tool_result":
                tally.result(str(block.get("tool_use_id")), result_text(block.get("content")), bool(block.get("is_error")))
    return tally.finish()


def moment_of(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def codex_session(events: Iterable[dict[str, Any]], start: datetime, end: datetime) -> list[tuple[int, int]]:
    tally = Tally()
    for index, event in enumerate(events):
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if index == 0:
            source, cwd = payload.get("thread_source"), str(payload.get("cwd") or "")
            if event.get("type") != "session_meta" or source != "user" or payload.get("source") == "exec":
                return []
            if TEMPORARY_CWD.search(cwd):
                return []
        item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
        if event.get("type") == "event_msg" and (payload.get("type") == "user_message" or item.get("type") == "UserMessage"):
            moment = moment_of(event.get("timestamp"))
            tally.prompt(moment is not None and start <= moment < end)
        elif event.get("type") == "response_item" and payload.get("type") in CALL_TYPES:
            call_id = str(payload.get("call_id"))
            if payload.get("name") == "spawn_agent":
                agent = codex_agent(payload)
                if not hidden(agent):
                    tally.launch(call_id, "agent", [agent])
            else:
                keys = runner_launches(json.dumps(payload, ensure_ascii=False))
                if keys:
                    tally.launch(call_id, "runner", keys)
        elif event.get("type") == "response_item" and payload.get("type") in OUTPUT_TYPES:
            text = result_text(payload.get("output"))
            tally.result(str(payload.get("call_id")), text, spawn_failed(tally, str(payload.get("call_id")), text))
    return tally.finish()


def codex_agent(payload: dict[str, Any]) -> str:
    try:
        arguments = json.loads(payload.get("arguments") or "{}")
    except ValueError:
        arguments = {}
    return request_budget.agent_key(arguments if isinstance(arguments, dict) else {})


def spawn_failed(tally: Tally, call_id: str, text: str) -> bool:
    """A native spawn whose acknowledgement names no task failed to start."""
    if tally.calls.get(call_id, ("", []))[0] != "agent":
        return False
    try:
        return not (isinstance(json.loads(text), dict) and json.loads(text).get("task_name"))
    except ValueError:
        return True


def read_events(path: Path) -> Iterator[dict[str, Any]]:
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


def session_files(claude_root: Path, codex_root: Path, start: datetime) -> Iterator[tuple[str, Path]]:
    cutoff = start.timestamp()
    for path in sorted(claude_root.glob("*/*.jsonl")):
        if path.stat().st_mtime >= cutoff:
            yield "claude", path
    for path in sorted(codex_root.glob("*/*/*/rollout-*.jsonl")):
        if path.stat().st_mtime >= cutoff:
            yield "codex", path


def distribution(requests: list[tuple[int, int]], start: datetime, end: datetime) -> dict[str, Any]:
    """The record: requests per count and the largest count, with no session content."""
    runs: dict[str, int] = {}
    retries: dict[str, int] = {}
    for run_count, retry_count in requests:
        runs[str(run_count)] = runs.get(str(run_count), 0) + 1
        retries[str(retry_count)] = retries.get(str(retry_count), 0) + 1
    return {
        "window": {"start": start.date().isoformat(), "end": end.date().isoformat()},
        "requests": len(requests),
        "requests_with_a_delegated_run": sum(1 for run_count, _ in requests if run_count > 0),
        "runs_per_request": dict(sorted(runs.items(), key=lambda item: int(item[0]))),
        "retries_per_request": dict(sorted(retries.items(), key=lambda item: int(item[0]))),
        "largest_runs": max((run_count for run_count, _ in requests), default=0),
        "largest_retries": max((retry_count for _, retry_count in requests), default=0),
    }


def default_caps(record: dict[str, Any]) -> tuple[int, int]:
    """The run cap and retry cap a distribution sets: both 0 when no request held a delegated run."""
    if record["requests_with_a_delegated_run"] == 0:
        return 0, 0
    runs = record["largest_runs"]
    return (runs // 10 + 1) * 10, record["largest_retries"] + 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--end", required=True, help="the day the window ends before, as YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--claude-root", default=str(Path.home() / ".claude" / "projects"))
    parser.add_argument("--codex-root", default=str(Path.home() / ".codex" / "sessions"))
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    start = end - timedelta(days=args.days)
    requests: list[tuple[int, int]] = []
    for host, path in session_files(Path(args.claude_root), Path(args.codex_root), start):
        counter = claude_session if host == "claude" else codex_session
        requests += counter(read_events(path), start, end)
    record = distribution(requests, start, end)
    text = json.dumps({**record, "run_cap": default_caps(record)[0], "retry_cap": default_caps(record)[1]}, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
