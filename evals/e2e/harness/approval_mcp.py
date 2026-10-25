"""Stdio MCP server for `--permission-prompt-tool`: approves every request and logs it, standing in for the user."""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

TOOL_NAME = "approve"
SERVER_INFO = {"name": "eval-approver", "version": "1.0.0"}
DEFAULT_PROTOCOL = "2025-06-18"
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "tool_name": {"type": "string"},
        "input": {"type": "object"},
        "tool_use_id": {"type": "string"},
    },
    "required": ["tool_name", "input"],
}


def decision(arguments: dict[str, Any]) -> dict[str, Any]:
    tool_input = arguments.get("input")
    return {"behavior": "allow", "updatedInput": tool_input if isinstance(tool_input, dict) else {}}


def log_request(path: str | None, arguments: dict[str, Any]) -> None:
    if not path:
        return
    record = {"at": time.time(), "tool_name": arguments.get("tool_name"), "tool_use_id": arguments.get("tool_use_id"),
              "input": arguments.get("input")}
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def handle(message: dict[str, Any], log_path: str | None) -> dict[str, Any] | None:
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
            log_request(log_path, arguments)
            reply["result"] = {"content": [{"type": "text", "text": json.dumps(decision(arguments))}]}
    elif method == "ping":
        reply["result"] = {}
    else:
        reply["error"] = {"code": -32601, "message": f"method not found: {method}"}
    return reply


def main() -> int:
    log_path = os.environ.get("EVAL_APPROVAL_LOG")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        reply = handle(message, log_path) if isinstance(message, dict) else None
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
