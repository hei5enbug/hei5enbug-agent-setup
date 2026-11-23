#!/usr/bin/env python3
"""A fake `aside` command for the T160 evaluation: canned answers for the skill's recipes and a call log.

Every call is appended to the file named by FAKE_ASIDE_LOG. With FAKE_ASIDE_MODE=fail, `aside exec` fails and creates no
session. All data is fictional.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ANSWER = "Status: In Review. Source: https://example.com/tracker/ABC-123"
SESSION = "sess-demo-001"
TRACE_MARKER = "TRACE-NOISE"


def log(argv: list[str]) -> None:
    target = os.environ.get("FAKE_ASIDE_LOG")
    if target:
        with Path(target).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"argv": argv}) + "\n")


def run_exec() -> int:
    if os.environ.get("FAKE_ASIDE_MODE") == "fail":
        print("error | the Aside agent could not reach the page")
        return 1
    for step in range(40):
        print(f"[tool] {TRACE_MARKER} step {step}: navigate and read the tracker page")
    print(f"created new session: {SESSION}")
    return 0


def run_repl(code: str) -> int:
    if "sessions.messages" in code:
        print(ANSWER)
    elif "screenshot" in code:
        Path("shot.png").write_bytes(b"\x89PNG fake")
        print("saved", Path("shot.png").resolve())
    else:
        print("200 ABC-123 In Review")
    return 0


def main(argv: list[str]) -> int:
    log(argv)
    if argv[:1] == ["exec"]:
        return run_exec()
    if argv[:1] == ["repl"]:
        return run_repl(" ".join(argv[1:]))
    print("aside: unknown command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
