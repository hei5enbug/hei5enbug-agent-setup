"""One ordered timeline of a conversation with the scripted user: the agent's texts, its calls, and each exchange.

A grader reads the timeline to decide what happened before an approval or between two answers. A question asked through the
question tool sits at the call that asked it. A plain-text question sits where its turn ended: a Claude Code stream ends each
turn with a `result` event and a Codex rollout with a `task_complete` event, and the k-th turn end carries the k-th plain-text
exchange of the log.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from . import codex_calls
from .edit_scope import real, shell_writes_inside, tool_writes_inside
from .scripted_user import KIND_TEXT, KIND_TOOL
from .transcript import content_blocks

ASK_TOOL = "AskUserQuestion"
EDIT_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch"})
WRITING_COMMAND = re.compile(
    r"(?<![<>&\d])>>?(?![>&])(?!\s*/dev/null)|\btee\b|\bsed\s+(?:-\w*i|--in-place)|\bgit\s+(?:apply|mv|rm|restore|checkout\s+--)\b"
    r"|\b(?:mv|cp|rm|touch|patch|truncate)\s|\bwrite_text\b|\.write\(|\bopen\([^)]*[\"'][wax+]")
ITEM_TEXT, ITEM_CALL, ITEM_EXCHANGE = "text", "call", "exchange"


def is_edit_call(call: Mapping[str, Any], repo: str | None = None) -> bool:
    """A call that changes a file of the work: a file-editing tool, or a shell command that writes, moves, or removes one.
    A call the timeline already classified against the repository keeps that verdict in `edit`. With `repo`, only a change to
    a path inside the repository counts, so a write to a temporary folder is not an edit; without it, any write counts."""
    if "edit" in call:
        return bool(call["edit"])
    if call.get("name") in EDIT_TOOLS:
        return repo is None or tool_writes_inside(call, real(repo))
    command = str((call.get("input") or {}).get("command", "")) if call.get("name") == "Bash" else ""
    if not WRITING_COMMAND.search(command):
        return False
    return repo is None or shell_writes_inside(command, real(repo))


def call_item(call: Mapping[str, Any], repo: str | None) -> dict[str, Any]:
    item = {"type": ITEM_CALL, "id": str(call["id"]), "name": str(call["name"]), "input": call.get("input") or {}}
    if repo is not None:
        item["edit"] = is_edit_call(item, repo)
    return item


def exchange_item(exchange: Mapping[str, Any]) -> dict[str, Any]:
    return {"type": ITEM_EXCHANGE, **exchange}


def claude_timeline(
    events: Sequence[Mapping[str, Any]], exchanges: Sequence[Mapping[str, Any]], repo: str | None = None,
) -> list[dict[str, Any]]:
    """The main session's texts and calls in stream order, with each exchange after the call or the turn end that raised it.
    With `repo`, each call carries `edit`, whether it changes a path inside the repository."""
    by_call = {str(item.get("tool_use_id")): item for item in exchanges if item.get("kind") == KIND_TOOL and item.get("tool_use_id")}
    plain = [item for item in exchanges if item.get("kind") == KIND_TEXT]
    items: list[dict[str, Any]] = []
    seen_texts: set[tuple[str, str]] = set()
    seen_calls: set[str] = set()
    turns = 0
    for event in events:
        if event.get("type") == "result":
            if turns < len(plain):
                items.append(exchange_item(plain[turns]))
            turns += 1
            continue
        if event.get("type") != "assistant" or event.get("parent_tool_use_id") is not None:
            continue
        message_id = str((event.get("message") or {}).get("id"))
        for block in content_blocks(event):
            if block.get("type") == "text" and str(block.get("text", "")).strip():
                key = (message_id, str(block.get("text")))
                if key not in seen_texts:
                    seen_texts.add(key)
                    items.append({"type": ITEM_TEXT, "text": str(block.get("text"))})
            elif block.get("type") == "tool_use" and str(block.get("id")) not in seen_calls:
                seen_calls.add(str(block.get("id")))
                items.append(call_item(block, repo))
                if str(block.get("id")) in by_call:
                    items.append(exchange_item(by_call[str(block.get("id"))]))
    return items


def codex_timeline(
    events: Sequence[Mapping[str, Any]], exchanges: Sequence[Mapping[str, Any]], repo: str | None = None,
) -> list[dict[str, Any]]:
    """The main rollout's assistant messages and calls in order, with each plain-text exchange after the turn end it answers."""
    plain = [item for item in exchanges if item.get("kind") == KIND_TEXT]
    items: list[dict[str, Any]] = []
    turns = 0
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event.get("type") == "event_msg" and payload.get("type") == "task_complete":
            if turns < len(plain):
                items.append(exchange_item(plain[turns]))
            turns += 1
        elif event.get("type") == "response_item" and payload.get("type") == "message" and payload.get("role") == "assistant":
            text = "".join(str(part.get("text", "")) for part in payload.get("content") or [] if isinstance(part, dict)).strip()
            if text:
                items.append({"type": ITEM_TEXT, "text": text})
        elif event.get("type") == "response_item" and payload.get("type") in codex_calls.CALL_TYPES:
            items += [call_item(call, repo) for call in codex_calls.rollout_tool_calls([event], "main", "main")]
    return items


def exchanges_of(timeline: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [item for item in timeline if item["type"] == ITEM_EXCHANGE]


def first_edit(timeline: Sequence[Mapping[str, Any]], after: int = 0) -> int | None:
    """The position of the first edit call at or after position `after`, or None."""
    return next((index for index, item in enumerate(timeline) if index >= after and item["type"] == ITEM_CALL and is_edit_call(item)), None)


def position_of(timeline: Sequence[Mapping[str, Any]], exchange_index: int) -> int | None:
    """The position of the exchange with this 1-based index in the log, or None."""
    return next((index for index, item in enumerate(timeline)
                 if item["type"] == ITEM_EXCHANGE and item.get("index") == exchange_index), None)


def texts_between(timeline: Sequence[Mapping[str, Any]], start: int, end: int) -> list[str]:
    """Texts of the agent strictly between two positions."""
    return [item["text"] for item in timeline[start + 1:end] if item["type"] == ITEM_TEXT]
