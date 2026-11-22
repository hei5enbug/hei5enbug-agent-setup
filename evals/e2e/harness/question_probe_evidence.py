"""Read the evidence of the question hook probe: the hook log and the rollouts of the probe session.

The probe asks whether a Codex `PreToolUse` hook receives a `request_user_input` call. The rollout shows whether the
model called the tool and what the tool returned; the hook log, written by the probe hooks, shows which tool names
the hooks received. A hook that denies with a sentinel reason makes the rollout show whether the host honored it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .transcript import read_jsonl

QUESTION_TOOL = "request_user_input"
GUARD_LABEL = "guard"
CONTROL_LABEL = "control"
DELIVERED_DENIED = "delivered-and-denied"
DELIVERED = "delivered"
NOT_DELIVERED = "not-delivered"
HOOKS_INACTIVE = "hooks-inactive"
NOT_CALLED = "not-called"
CONCLUSIVE = frozenset({DELIVERED_DENIED, DELIVERED, NOT_DELIVERED})


def hook_entries(log: Path) -> list[dict[str, Any]]:
    """The log lines that hold an event, each as label, time, and event."""
    return [entry for entry in read_jsonl(log) if isinstance(entry.get("event"), dict)]


def tool_names(entries: list[dict[str, Any]], label: str | None = None) -> list[str]:
    return [str(entry["event"].get("tool_name")) for entry in entries
            if (label is None or entry.get("label") == label) and entry["event"].get("tool_name")]


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    return event.get("payload") if isinstance(event.get("payload"), dict) else {}


def _text(output: Any) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        return "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in output)
    return "" if output is None else str(output)


def question_calls(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each `request_user_input` function call of one rollout with the text its output returned."""
    outputs = {str(_payload(event).get("call_id")): _text(_payload(event).get("output")) for event in events
               if event.get("type") == "response_item" and str(_payload(event).get("type", "")).endswith("_output")}
    return [{"call_id": str(_payload(event).get("call_id")), "arguments": _payload(event).get("arguments"),
             "output": outputs.get(str(_payload(event).get("call_id")), "")}
            for event in events
            if event.get("type") == "response_item" and _payload(event).get("type") == "function_call"
            and _payload(event).get("name") == QUESTION_TOOL]


def hook_events(events: list[dict[str, Any]]) -> list[str]:
    """The type names of rollout events that mention a hook, in order."""
    found: list[str] = []
    for event in events:
        kind = str(_payload(event).get("type") or event.get("type") or "")
        if "hook" in kind.lower():
            found = [*found, kind]
    return found


def verdict(called: bool, entries: list[dict[str, Any]], denied_in_rollout: bool) -> str:
    """The probe's conclusion from whether the tool was called, what the hooks logged, and whether the rollout shows the denial."""
    if not called:
        return NOT_CALLED
    if QUESTION_TOOL in tool_names(entries, GUARD_LABEL):
        return DELIVERED_DENIED if denied_in_rollout else DELIVERED
    return NOT_DELIVERED if entries else HOOKS_INACTIVE


def collect_evidence(trial: Path, log_name: str, rollout_root: Path, sentinel: str) -> dict[str, Any]:
    """The evidence record of one probe trial: counts, tool names, the received event's keys, and the verdict."""
    entries = hook_entries(trial / log_name)
    rollouts = sorted(rollout_root.rglob("rollout-*.jsonl"))
    events = [event for path in rollouts for event in read_jsonl(path)]
    calls = question_calls(events)
    received = next((entry["event"] for entry in entries
                     if entry.get("label") == GUARD_LABEL and entry["event"].get("tool_name") == QUESTION_TOOL), None)
    denied = any(sentinel in call["output"] for call in calls)
    tool_input = received.get("tool_input") if isinstance(received, dict) else None
    return {
        "verdict": verdict(bool(calls), entries, denied),
        "rollouts": [path.name for path in rollouts],
        "question_calls": len(calls),
        "denial_in_rollout": denied,
        "hook_entries": len(entries),
        "guard_tool_names": tool_names(entries, GUARD_LABEL),
        "control_tool_names": tool_names(entries, CONTROL_LABEL),
        "received_event_keys": sorted(received) if isinstance(received, dict) else None,
        "received_tool_input_keys": sorted(tool_input) if isinstance(tool_input, dict) else None,
        "rollout_hook_events": hook_events(events),
    }
