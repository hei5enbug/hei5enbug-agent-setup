"""Decide whether a tool call needs an approval the session does not hold."""

from __future__ import annotations

import json
import os
import sys

from .grants import GrantStore


def ask(reason: str) -> str:
    return json.dumps({"decision": "ask", "reason": reason})


def main(stdin_text: str, store=None) -> str:
    try:
        payload = json.loads(stdin_text)
        session, key = payload["session"], payload["key"]
    except (ValueError, KeyError, TypeError):
        return ask("approval needed: unreadable hook input")
    try:
        if store is None:
            path = os.environ.get("JOBQ_GRANTS")
            store = GrantStore(path) if path else None
        if store is not None and store.has(session, key):
            return ""
    except Exception:
        return ask("approval needed: grant store unreadable")
    return ask(f"approval needed for {key}")


if __name__ == "__main__":
    print(main(sys.stdin.read()))
