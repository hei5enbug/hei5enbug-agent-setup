"""Stdio MCP server for `--permission-prompt-tool`: stands in for the user, allowing Bash and in-folder file work, logging all."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

try:
    from .scripted_user import KIND_TOOL, ScriptedUser, load_sheet, read_log
except ImportError:
    from scripted_user import KIND_TOOL, ScriptedUser, load_sheet, read_log  # type: ignore[no-redef]

TOOL_NAME = "approve"
SERVER_INFO = {"name": "eval-approver", "version": "1.0.0"}
DEFAULT_PROTOCOL = "2025-06-18"
FILE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
PATH_KEYS = ("file_path", "notebook_path")
BASH_TOOL = "Bash"
ASK_TOOL = "AskUserQuestion"
UNAVAILABLE = "The user is not available to answer; the conversation has ended."
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "tool_name": {"type": "string"},
        "input": {"type": "object"},
        "tool_use_id": {"type": "string"},
    },
    "required": ["tool_name", "input"],
}


def requested_paths(arguments: dict[str, Any]) -> list[str]:
    """The file paths a request touches: file-tool requests and any request with a file or notebook path."""
    tool_input = arguments.get("input")
    if arguments.get("tool_name") == BASH_TOOL or not isinstance(tool_input, dict):
        return []
    paths = [tool_input[key] for key in PATH_KEYS if isinstance(tool_input.get(key), str) and tool_input[key]]
    if arguments.get("tool_name") in FILE_TOOLS and not paths:
        return [""]
    return paths


def inside(folder: str, path: str, cwd: str | None = None) -> bool:
    """True when `path` lies in `folder` after resolving `..` and symlinks; relative paths start in `cwd` or `folder`."""
    root = os.path.realpath(folder)
    target = os.path.realpath(path if os.path.isabs(path) else os.path.join(cwd or root, path))
    return os.path.commonpath([root, target]) == root


def deny(tool_name: Any, path: str, run_folder: str) -> dict[str, Any]:
    message = f"{tool_name} path {path!r} is outside the run folder {run_folder}; only files inside the run folder may be changed"
    return {"behavior": "deny", "message": message}


def decision(
    arguments: dict[str, Any], run_folder: str | None = None, cwd: str | None = None,
    scripted: tuple[str, str | None, str | None] | None = None,
) -> dict[str, Any]:
    tool_input = arguments.get("input")
    if scripted and arguments.get("tool_name") == ASK_TOOL:
        return scripted_decision(arguments, *scripted)
    if run_folder:
        paths = requested_paths(arguments)
        outside = next((path for path in paths if not path or not inside(run_folder, path, cwd)), None)
        if outside is not None:
            return deny(arguments.get("tool_name"), outside, run_folder)
    return {"behavior": "allow", "updatedInput": tool_input if isinstance(tool_input, dict) else {}}


def stream_events(path: str | None) -> list[dict[str, Any]]:
    """Events of the agent's stream file so far; blank and partial lines are skipped."""
    if not path or not Path(path).is_file():
        return []
    found = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            found.append(item)
    return found


def texts_after(events: list[dict[str, Any]], offset: int) -> str:
    """The main session's text blocks in the stream events after the first `offset` events."""
    texts = []
    for event in events[offset:]:
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if event.get("type") == "assistant" and event.get("parent_tool_use_id") is None and isinstance(content, list):
            texts += [str(block.get("text", "")) for block in content if isinstance(block, dict) and block.get("type") == "text"]
    return "\n\n".join(text for text in texts if text.strip())


def scripted_decision(arguments: dict[str, Any], sheet_path: str, log_path: str | None, stream_path: str | None) -> dict[str, Any]:
    """Answer a question asked through the question tool from the answer sheet, in the tool's free-form field: each question
    of the call gets the answer of its exchange. A call the sheet ends is denied, so the run ends with the question unanswered."""
    tool_input = arguments.get("input") if isinstance(arguments.get("input"), dict) else {}
    questions = [item for item in tool_input.get("questions") or [] if isinstance(item, dict) and isinstance(item.get("question"), str)]
    user = ScriptedUser(load_sheet(Path(sheet_path)), Path(log_path) if log_path else None)
    answers: dict[str, str] = {}
    for item in questions:
        events = stream_events(stream_path)
        earlier = read_log(Path(log_path) if log_path else None)
        offset = int(earlier[-1].get("stream_offset") or 0) if earlier else 0
        shown = texts_after(events, offset)
        specification = f"{shown}\n\n{item['question']}" if shown else item["question"]
        exchange = user.answer(item["question"], KIND_TOOL, specification, arguments.get("tool_use_id"), len(events))
        if exchange.answer is None:
            return {"behavior": "deny", "message": UNAVAILABLE}
        answers[item["question"]] = exchange.answer
    return {"behavior": "allow", "updatedInput": {**tool_input, "questions": tool_input.get("questions"), "answers": answers}}


def log_request(path: str | None, arguments: dict[str, Any], verdict: str) -> None:
    if not path:
        return
    record = {"at": time.time(), "tool_name": arguments.get("tool_name"), "tool_use_id": arguments.get("tool_use_id"),
              "input": arguments.get("input"), "decision": verdict}
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def handle(
    message: dict[str, Any], log_path: str | None, run_folder: str | None = None, cwd: str | None = None,
    scripted: tuple[str, str | None, str | None] | None = None,
) -> dict[str, Any] | None:
    method = message.get("method")
    if "id" not in message:
        return None
    reply: dict[str, Any] = {"jsonrpc": "2.0", "id": message["id"]}
    if method == "initialize":
        params = message.get("params") or {}
        reply["result"] = {
            "protocolVersion": params.get("protocolVersion") or DEFAULT_PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }
    elif method == "tools/list":
        reply["result"] = {"tools": [{"name": TOOL_NAME, "description": "Approve a permission request.",
                                      "inputSchema": TOOL_SCHEMA}]}
    elif method == "tools/call":
        params = message.get("params") or {}
        arguments = params.get("arguments") or {}
        if params.get("name") != TOOL_NAME or not isinstance(arguments, dict):
            reply["error"] = {"code": -32602, "message": "unknown tool or arguments"}
        else:
            verdict = decision(arguments, run_folder, cwd, scripted)
            log_request(log_path, arguments, verdict["behavior"])
            reply["result"] = {"content": [{"type": "text", "text": json.dumps(verdict)}]}
    elif method == "ping":
        reply["result"] = {}
    else:
        reply["error"] = {"code": -32601, "message": f"method not found: {method}"}
    return reply


def main() -> int:
    log_path = os.environ.get("EVAL_APPROVAL_LOG")
    run_folder = os.environ.get("EVAL_RUN_FOLDER")
    cwd = os.environ.get("EVAL_RUN_CWD")
    sheet = os.environ.get("EVAL_SHEET")
    scripted = (sheet, os.environ.get("EVAL_SCRIPTED_LOG"), os.environ.get("EVAL_STREAM")) if sheet else None
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        reply = handle(message, log_path, run_folder, cwd, scripted) if isinstance(message, dict) else None
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
