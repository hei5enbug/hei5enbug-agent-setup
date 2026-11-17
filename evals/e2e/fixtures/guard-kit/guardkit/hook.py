"""Read one hook payload and print the decision as JSON; print nothing when the call is allowed."""

from __future__ import annotations

import json
import sys
from typing import Callable

from .decision import Decision
from .protect import decide_write

PROTECTED = ["/opt/guardkit/plugins"]


def evaluate(payload: dict) -> Decision:
    return decide_write(payload["tool_input"]["command"], payload.get("cwd", "."), PROTECTED)


def main(stdin_text: str, evaluate: Callable[[dict], Decision] = evaluate) -> str:
    payload = json.loads(stdin_text)
    decision = evaluate(payload)
    if decision.action == "allow":
        return ""
    return json.dumps({"decision": decision.action, "reason": decision.reason})


if __name__ == "__main__":
    output = main(sys.stdin.read())
    if output:
        print(output)
