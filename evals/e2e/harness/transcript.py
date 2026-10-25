"""Parse stream-json and subagent transcripts into the TranscriptView the graders consume."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from .config import USAGE_LIMIT_PATTERN

AGENT_TOOLS = frozenset({"Agent", "Task"})
ROLE_RUNNER_CALL = re.compile(r"role_runner\.py\s+((?!-)[\w-]+)")
ASSIGNMENT_FLAG = re.compile(r"--assignment\s+(\S+)")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1\n(.*?)\n\s*\2(?=\s|$)", re.S)
EXIT_CODE_PREFIX = re.compile(r"^Exit code (\d+)")
EXIT_MARKER = re.compile(r"\bexit=(\d+)")
AGENT_CLASSES = {
    "worker": "implementation", "sonnet-worker": "implementation", "scout": "investigation",
    "researcher": "investigation", "explore": "investigation", "reviewer": "review", "designer": "design",
}
ROLE_CLASSES = {
    "worker": "implementation", "implementation": "implementation", "scout": "investigation",
    "researcher": "investigation", "investigation": "investigation", "reviewer": "review", "review": "review",
    "design": "design", "designer": "design",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSON-lines file, skipping blank and malformed lines."""
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def content_blocks(event: dict[str, Any]) -> list[dict[str, Any]]:
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict) and item.get("type") == "text")
    return "" if content is None else str(content)


def bare_agent_type(agent_type: str) -> str:
    return agent_type.rsplit(":", 1)[-1].lower()


def classify_agent(agent_type: str) -> str:
    return AGENT_CLASSES.get(bare_agent_type(agent_type), "other")


def classify_role(role: str) -> str:
    return ROLE_CLASSES.get(role.lower(), "other")


def role_runner_status(text: str) -> dict[str, Any] | None:
    """Return the JSON status line role_runner printed in a Bash result, when present."""
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{") and '"runner"' in line and '"role"' in line:
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def bash_exit_code(text: str, is_error: bool) -> int:
    status = role_runner_status(text)
    if status is not None and isinstance(status.get("exit"), int):
        return int(status["exit"])
    prefix = EXIT_CODE_PREFIX.match(text)
    if prefix:
        return int(prefix.group(1))
    marker = EXIT_MARKER.findall(text)
    if marker:
        return int(marker[-1])
    return 1 if is_error else 0


def assignment_text(command: str, assignments: dict[str, str]) -> str:
    bodies = [match.group(3) for match in HEREDOC.finditer(command)]
    if bodies:
        return "\n\n".join(bodies)
    for path in ASSIGNMENT_FLAG.findall(command):
        if path in assignments:
            return assignments[path]
    return ""


def collect_calls(events: Iterable[dict[str, Any]], source_of: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Gather tool calls keyed by id in first-seen order, attaching results from later user events."""
    calls: dict[str, dict[str, Any]] = {}
    for event in events:
        parent = event.get("parent_tool_use_id")
        for block in content_blocks(event):
            if event.get("type") == "assistant" and block.get("type") == "tool_use":
                call_id = str(block.get("id"))
                if call_id in calls:
                    continue
                source = "main" if parent is None else source_of.get(str(parent), f"subagent:{event.get('subagent_type', 'unknown')}")
                if parent is not None and event.get("subagent_type"):
                    source = f"subagent:{event['subagent_type']}"
                calls[call_id] = {
                    "id": call_id, "name": str(block.get("name")), "input": block.get("input") or {},
                    "result_text": "", "is_error": False, "parent": parent, "source": source,
                }
            elif event.get("type") == "user" and block.get("type") == "tool_result":
                call = calls.get(str(block.get("tool_use_id")))
                if call is not None and not call["result_text"]:
                    call["result_text"] = result_text(block.get("content"))
                    call["is_error"] = bool(block.get("is_error"))
    return calls


def agent_sources(events: list[dict[str, Any]], subagents: list[dict[str, Any]]) -> dict[str, str]:
    sources: dict[str, str] = {}
    for event in events:
        for block in content_blocks(event):
            if block.get("type") == "tool_use" and block.get("name") in AGENT_TOOLS:
                agent_type = (block.get("input") or {}).get("subagent_type") or "general-purpose"
                sources[str(block.get("id"))] = f"subagent:{agent_type}"
    for record in subagents:
        meta = record.get("meta") or {}
        if meta.get("toolUseId") and meta.get("agentType"):
            sources[str(meta["toolUseId"])] = f"subagent:{meta['agentType']}"
    return sources


def build_tool_calls(events: list[dict[str, Any]], subagents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_of = agent_sources(events, subagents)
    calls = collect_calls(events, source_of)
    for record in subagents:
        meta = record.get("meta") or {}
        parent = meta.get("toolUseId")
        source = f"subagent:{meta.get('agentType', 'unknown')}"
        for call_id, call in collect_calls(record.get("events", []), {}).items():
            if call_id not in calls:
                calls[call_id] = {**call, "parent": parent, "source": source}
            elif not calls[call_id]["result_text"]:
                calls[call_id] = {**calls[call_id], "result_text": call["result_text"], "is_error": call["is_error"]}
    return list(calls.values())


def build_delegations(calls: list[dict[str, Any]], assignments: dict[str, str]) -> list[dict[str, Any]]:
    delegations: list[dict[str, Any]] = []
    for order, call in enumerate(calls):
        if call["source"] != "main":
            continue
        if call["name"] in AGENT_TOOLS:
            agent_type = str(call["input"].get("subagent_type") or "general-purpose")
            delegations.append({
                "kind": "agent", "type": agent_type, "class": classify_agent(agent_type),
                "prompt": str(call["input"].get("prompt") or ""), "exit": None, "tool_use_id": call["id"], "order": order,
            })
        elif call["name"] == "Bash":
            command = str(call["input"].get("command") or "")
            match = ROLE_RUNNER_CALL.search(command)
            if match:
                delegations.append({
                    "kind": "role_runner", "type": match.group(1), "class": classify_role(match.group(1)),
                    "prompt": assignment_text(command, assignments),
                    "exit": bash_exit_code(call["result_text"], call["is_error"]), "tool_use_id": call["id"], "order": order,
                })
    return delegations


def assistant_texts(events: list[dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    seen: set[tuple[str, str]] = set()
    for event in events:
        if event.get("type") != "assistant" or event.get("parent_tool_use_id") is not None:
            continue
        message_id = str((event.get("message") or {}).get("id"))
        for block in content_blocks(event):
            key = (message_id, str(block.get("text")))
            if block.get("type") == "text" and key not in seen:
                seen.add(key)
                texts.append(str(block.get("text")))
    return texts


def result_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    results = [event for event in events if event.get("type") == "result"]
    return results[-1] if results else None


def build_view(
    events: list[dict[str, Any]],
    subagents: list[dict[str, Any]] | None = None,
    approvals: list[dict[str, Any]] | None = None,
    assignments: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the TranscriptView from stream events, subagent records ({meta, events}), and approval lines."""
    records = subagents or []
    calls = build_tool_calls(events, records)
    result = result_event(events) or {}
    denials = result.get("permission_denials")
    final = result.get("result")
    return {
        "final_answer": final if isinstance(final, str) else "",
        "assistant_texts": assistant_texts(events),
        "tool_calls": calls,
        "delegations": build_delegations(calls, assignments or {}),
        "approvals": list(approvals or []),
        "permission_denials": list(denials) if isinstance(denials, list) else [],
    }


def init_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in events:
        if event.get("type") == "system" and event.get("subtype") == "init":
            return event
    return None


def usage_limit_reason(events: list[dict[str, Any]]) -> str | None:
    """Return why the stream shows a usage or rate limit stop, or None."""
    result = result_event(events)
    if result and result.get("is_error") and USAGE_LIMIT_PATTERN.search(str(result.get("result") or "")):
        return "result: " + str(result.get("result"))[:200]
    for event in events:
        info = event.get("rate_limit_info")
        if event.get("type") == "rate_limit_event" and isinstance(info, dict) and info.get("status") == "rejected":
            return "rate_limit_event rejected"
    retry_at = [i for i, e in enumerate(events) if e.get("type") == "system" and e.get("subtype") == "api_retry" and e.get("error") == "rate_limit"]
    if retry_at:
        answered = any(e.get("type") == "assistant" and content_blocks(e) for e in events[retry_at[-1] + 1:])
        if not answered:
            return "api_retry rate_limit without a later assistant message"
    return None


def mod_marker_present(transcript_events: list[dict[str, Any]], marker: str) -> bool:
    for record in transcript_events:
        attachment = record.get("attachment")
        if isinstance(attachment, dict) and attachment.get("type") == "hook_additional_context":
            if marker in json.dumps(attachment.get("content"), ensure_ascii=False):
                return True
    return False
