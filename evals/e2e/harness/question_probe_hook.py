#!/usr/bin/env python3
"""The hook of the question hook probe: append the PreToolUse event it receives to a log file, and optionally deny it.

Usage: question_probe_hook.py <log file> <label> [--deny <reason>]. Each log line is a JSON object with the label, the
time, and the event the host sent on stdin. With `--deny` the hook prints a PreToolUse deny decision that holds the reason."""

from __future__ import annotations

import json
import sys
import time


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return 0
    log, label = argv[0], argv[1]
    reason = argv[argv.index("--deny") + 1] if "--deny" in argv[2:-1] else None
    try:
        event = json.load(sys.stdin)
    except ValueError:
        event = {"unreadable": True}
    with open(log, "a", encoding="utf-8") as stream:
        stream.write(json.dumps({"label": label, "at": time.time(), "event": event}, ensure_ascii=False) + "\n")
    if reason is not None:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                   "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
