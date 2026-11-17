"""Stdio MCP server for `--permission-prompt-tool`: stands in for the user, allowing Bash, in-folder file work, and reads of the plugin folder, logging all."""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

TOOL_NAME = "approve"
SERVER_INFO = {"name": "eval-approver", "version": "1.0.0"}
DEFAULT_PROTOCOL = "2025-06-18"
FILE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
PATH_KEYS = ("file_path", "notebook_path")
READ_TOOLS = frozenset({"Read", "Grep", "Glob"})
SEARCH_TOOLS = frozenset({"Grep", "Glob"})
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
    keys = (*PATH_KEYS, "path") if arguments.get("tool_name") in SEARCH_TOOLS else PATH_KEYS
    paths = [tool_input[key] for key in keys if isinstance(tool_input.get(key), str) and tool_input[key]]
    if arguments.get("tool_name") in FILE_TOOLS and not paths:
        return [""]
    return paths


def inside(folder: str, path: str, cwd: str | None = None) -> bool:
    """True when `path` lies in `folder` after resolving `..` and symlinks; relative paths start in `cwd` or `folder`."""
    root = os.path.realpath(folder)
    target = os.path.realpath(path if os.path.isabs(path) else os.path.join(cwd or root, path))
    return os.path.commonpath([root, target]) == root


def deny(tool_name: Any, path: str, run_folder: str, read_root: str | None = None) -> dict[str, Any]:
    message = f"{tool_name} path {path!r} is outside the run folder {run_folder}; only files inside the run folder may be changed"
    if read_root:
        message += f", and only Read, Grep, and Glob may reach the plugin folder {read_root}"
    return {"behavior": "deny", "message": message}


def decision(
    arguments: dict[str, Any], run_folder: str | None = None, cwd: str | None = None, read_root: str | None = None,
) -> dict[str, Any]:
    """Allow a file path inside `run_folder`; a read-only tool may also reach `read_root`, the run's exported plugin."""
    tool_input = arguments.get("input")
    if run_folder:
        reads = arguments.get("tool_name") in READ_TOOLS and bool(read_root)
        paths = requested_paths(arguments)
        outside = next((path for path in paths if not path or not (
            inside(run_folder, path, cwd) or (reads and inside(read_root or "", path, cwd)))), None)
        if outside is not None:
            return deny(arguments.get("tool_name"), outside, run_folder, read_root)
    return {"behavior": "allow", "updatedInput": tool_input if isinstance(tool_input, dict) else {}}


def log_request(path: str | None, arguments: dict[str, Any], verdict: str) -> None:
    if not path:
        return
    record = {"at": time.time(), "tool_name": arguments.get("tool_name"), "tool_use_id": arguments.get("tool_use_id"),
              "input": arguments.get("input"), "decision": verdict}
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def handle(
    message: dict[str, Any], log_path: str | None, run_folder: str | None = None, cwd: str | None = None,
    read_root: str | None = None,
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
            verdict = decision(arguments, run_folder, cwd, read_root)
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
    read_root = os.environ.get("EVAL_READ_ROOT")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        reply = handle(message, log_path, run_folder, cwd, read_root) if isinstance(message, dict) else None
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
