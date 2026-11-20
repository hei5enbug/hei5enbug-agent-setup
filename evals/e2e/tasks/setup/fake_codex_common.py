"""Shared helper of the reviewer-failure setup scripts: a fake `gh` and a fake `codex` that fails every review run.

The fake `codex` lists one trusted approval-guard hook for `hooks/list`, so the role runner reaches its `exec` call, and
then prints the given message to standard error and exits with 1. Both stubs sit in `fake-bin/` beside the repository.
"""

from __future__ import annotations

import stat
from pathlib import Path

GH = '''#!/bin/sh
printf '%s\\n' "$*" >> "${FAKE_GH_LOG:-/dev/null}"
echo "https://example.com/pull/1"
'''

CODEX = '''#!/usr/bin/env python3
import json, os, sys

MESSAGE = __MESSAGE__
GUARD_COMMAND = 'sh "/abs/plugin/root/scripts/hook_python.sh" approval_guard.py'

def log(argv):
    path = os.environ.get("FAKE_CODEX_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(argv) + "\\n")

def guard_hook():
    return {"key": "plugin@market:hooks/hooks.json:pre_tool_use:1:0", "eventName": "preToolUse", "handlerType": "command",
            "command": GUARD_COMMAND, "async": False, "matcher": "^(Bash|Read|Edit|Write)$", "timeoutSec": 10,
            "source": "plugin", "pluginId": "plugin@market", "enabled": True, "isManaged": False,
            "currentHash": "sha256:x", "trustStatus": "trusted"}

def serve_hooks():
    for line in sys.stdin:
        request = json.loads(line)
        if request.get("method") == "initialize":
            print(json.dumps({"id": request["id"], "result": {"userAgent": "fake"}}), flush=True)
        elif request.get("method") == "hooks/list":
            cwd = request["params"]["cwds"][0]
            entry = {"cwd": cwd, "warnings": [], "errors": [], "hooks": [guard_hook()]}
            print(json.dumps({"id": request["id"], "result": {"data": [entry]}}), flush=True)
            return

argv = sys.argv[1:]
log(argv)
if argv[:2] == ["mcp", "list"]:
    print("[]")
    sys.exit(0)
if argv[:1] == ["app-server"]:
    serve_hooks()
    sys.exit(0)
sys.stdin.read()
sys.stderr.write(MESSAGE + "\\n")
sys.exit(1)
'''


def install(repo: Path, failure_message: str) -> None:
    """Write `fake-bin/gh` and `fake-bin/codex` beside the repository; the fake `codex` fails every `exec` with the message."""
    folder = repo.parent / "fake-bin"
    folder.mkdir(exist_ok=True)
    codex = CODEX.replace("__MESSAGE__", repr(failure_message))
    for name, text in (("gh", GH), ("codex", codex)):
        path = folder / name
        path.write_text(text, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
