#!/usr/bin/env python3
"""A stand-in `codex` that makes every reviewer run fail on purpose, without a model call.

Put a copy or symlink named `codex` on PATH. It answers `mcp list` and the hook check of `app-server` like a
ready Codex, and every `exec` run prints FAKE_CODEX_MESSAGE to the stream named by FAKE_CODEX_STREAM
(`stderr` by default, or `stdout`) and exits with FAKE_CODEX_EXIT (1 by default). When FAKE_CODEX_LOG names a
file, each call appends its arguments there as one JSON line.
"""
import json
import os
import sys

DEFAULT_MESSAGE = "You have reached your usage limit. Try again later."
GUARD_COMMAND = 'sh "/abs/plugin/root/scripts/hook_python.sh" approval_guard.py'


def log_call(argv):
    path = os.environ.get("FAKE_CODEX_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(argv) + "\n")


def guard_hook():
    return {
        "key": "plugin@market:hooks/hooks.json:pre_tool_use:1:0", "eventName": "preToolUse",
        "handlerType": "command", "command": GUARD_COMMAND, "async": False, "matcher": "^(Bash|Read|Edit|Write)$",
        "timeoutSec": 10, "source": "plugin", "pluginId": "plugin@market", "enabled": True, "isManaged": False,
        "currentHash": "sha256:x", "trustStatus": "trusted",
    }


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


def main(argv):
    log_call(argv)
    if argv[:2] == ["mcp", "list"]:
        print("[]")
        return 0
    if argv[:1] == ["app-server"]:
        serve_hooks()
        return 0
    sys.stdin.read()
    stream = sys.stdout if os.environ.get("FAKE_CODEX_STREAM") == "stdout" else sys.stderr
    stream.write(os.environ.get("FAKE_CODEX_MESSAGE", DEFAULT_MESSAGE) + "\n")
    return int(os.environ.get("FAKE_CODEX_EXIT", "1"))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
