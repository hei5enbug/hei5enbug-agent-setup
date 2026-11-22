"""Stdio MCP server for `--permission-prompt-tool`: stands in for the user, allowing Bash, in-folder file work, and reads inside read roots, logging all."""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scripted_user  # noqa: E402

TOOL_NAME = "approve"
SERVER_INFO = {"name": "eval-approver", "version": "1.0.0"}
DEFAULT_PROTOCOL = "2025-06-18"
FILE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
PATH_KEYS = ("file_path", "notebook_path")
BASH_TOOL = "Bash"
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
    message = f"{tool_name} path {path!r} is outside the run folder {run_folder}; only files inside the run folder may be changed, and only the run folder and the loaded plugin folder may be read"
    return {"behavior": "deny", "message": message}


def decision(
    arguments: dict[str, Any], run_folder: str | None = None, cwd: str | None = None, read_roots: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Deny a request outside the run folder; a read, which is any tool not in FILE_TOOLS, may also lie inside a read root."""
    tool_input = arguments.get("input")
    if run_folder:
        folders = (run_folder, *read_roots) if arguments.get("tool_name") not in FILE_TOOLS else (run_folder,)
        paths = requested_paths(arguments)
        outside = next((path for path in paths if not path or not any(inside(folder, path, cwd or run_folder) for folder in folders)), None)
        if outside is not None:
            return deny(arguments.get("tool_name"), outside, run_folder)
    return {"behavior": "allow", "updatedInput": tool_input if isinstance(tool_input, dict) else {}}


def stream_events(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    events = []
    try:
        with open(path, encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if isinstance(item, dict):
                    events.append(item)
    except OSError:
        pass
    return events


def user_decision(arguments: dict[str, Any], user: dict[str, Any], cwd: str | None) -> dict[str, Any]:
    """Answer an `AskUserQuestion` call from the answer sheet; the text a request for approval is judged on is the assistant
    text of the stream since the previous question."""
    tool_use_id = arguments.get("tool_use_id")
    specification = scripted_user.assistant_text_since_last_question(stream_events(user.get("stream")), tool_use_id)
    return scripted_user.answer_tool_input(
        user["sheet"], arguments.get("input") or {}, user.get("log"), specification or None, cwd, tool_use_id)


def log_request(path: str | None, arguments: dict[str, Any], verdict: str) -> None:
    if not path:
        return
    record = {"at": time.time(), "tool_name": arguments.get("tool_name"), "tool_use_id": arguments.get("tool_use_id"),
              "input": arguments.get("input"), "decision": verdict}
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def handle(
    message: dict[str, Any], log_path: str | None, run_folder: str | None = None, cwd: str | None = None,
    read_roots: tuple[str, ...] = (),
    user: dict[str, Any] | None = None,
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
            asks = user is not None and arguments.get("tool_name") == scripted_user.QUESTION_TOOL
            verdict = user_decision(arguments, user, cwd) if asks else decision(arguments, run_folder, cwd, read_roots)
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
    read_roots = tuple(root for root in os.environ.get("EVAL_READ_ROOTS", "").split(os.pathsep) if root)
    sheet_path = os.environ.get("EVAL_ANSWER_SHEET")
    user = ({"sheet": scripted_user.load_sheet(sheet_path), "log": os.environ.get("EVAL_USER_LOG"),
             "stream": os.environ.get("EVAL_STREAM")} if sheet_path else None)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        reply = handle(message, log_path, run_folder, cwd, read_roots, user) if isinstance(message, dict) else None
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
