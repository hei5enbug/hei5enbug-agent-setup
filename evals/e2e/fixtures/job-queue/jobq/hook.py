"""Decide whether a tool call needs an approval the session does not hold."""

from __future__ import annotations

import json
import sys


def main(stdin_text: str) -> str:
    payload = json.loads(stdin_text)
    return json.dumps({"decision": "ask", "reason": f"approval needed for {payload['key']}"})


if __name__ == "__main__":
    print(main(sys.stdin.read()))
