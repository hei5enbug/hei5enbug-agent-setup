"""Read one hook payload and print the decision as JSON; print nothing when the call is allowed."""

from __future__ import annotations

import json
import os
import sys
import threading
from typing import Callable

from .decision import Decision
from .protect import decide_write

PROTECTED = ["/opt/guardkit/plugins"]
PREFIX = "guardkit pre_write: "


def evaluate(payload: dict) -> Decision:
    return decide_write(payload["tool_input"]["command"], payload.get("cwd", "."), PROTECTED)


def deny(reason: str) -> str:
    return json.dumps({"decision": "deny", "reason": PREFIX + reason})


def main(stdin_text: str, evaluate: Callable[[dict], Decision] = evaluate, timeout_seconds: float = 10.0) -> str:
    try:
        payload = json.loads(stdin_text)
        command = payload["tool_input"]["command"]
        if not isinstance(command, str):
            raise TypeError("command")
    except (ValueError, KeyError, TypeError):
        return deny("unreadable hook input")
    box: dict = {}

    def work() -> None:
        try:
            box["decision"] = evaluate(payload)
        except Exception as error:
            box["error"] = error

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    budget = timeout_seconds / 2
    thread.join(budget)
    if thread.is_alive():
        return deny(f"timed out after {budget:g}s")
    if "error" in box:
        return deny(f"{type(box['error']).__name__}: {box['error']}")
    decision = box["decision"]
    if decision.action == "allow":
        return ""
    return json.dumps({"decision": decision.action, "reason": decision.reason})


if __name__ == "__main__":
    try:
        timeout = float(os.environ.get("GUARDKIT_HOOK_TIMEOUT", "10"))
    except ValueError:
        timeout = 10.0
    output = main(sys.stdin.read(), timeout_seconds=timeout)
    if output:
        print(output)
    sys.exit(0)
