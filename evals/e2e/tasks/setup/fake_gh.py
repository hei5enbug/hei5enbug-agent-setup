#!/usr/bin/env python3
"""A fake `gh` command for the T79 evaluation: it answers only from the seed file named by FAKE_GH_STATE and logs every call.

The seed lists the repositories it knows, with their issues. A call it has no seeded answer for prints a refusal on
stderr and exits 2; it never runs another `gh`, so a trial cannot reach GitHub. All data is fictional.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

STATE = Path(os.environ.get("FAKE_GH_STATE", "gh-state/seed.json"))
CALLS = STATE.parent / "calls.jsonl"


def log(argv: list[str], answered: bool) -> None:
    CALLS.parent.mkdir(parents=True, exist_ok=True)
    with CALLS.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"time": time.time(), "cwd": os.getcwd(), "argv": argv, "answered": answered}) + "\n")


def option(argv: list[str], name: str) -> str | None:
    for token, following in zip(argv, [*argv[1:], None]):
        if token == name and following is not None:
            return following
        if token.startswith(name + "="):
            return token[len(name) + 1 :]
    return None


def answer(argv: list[str]) -> str | None:
    if argv == ["--version"]:
        return "gh version 0.0.0 (fake)"
    if argv[:2] == ["auth", "status"]:
        return "Logged in to github.com as demo-user (fake)"
    if argv[:2] == ["issue", "list"]:
        repo = option(argv, "--repo")
        try:
            seed = json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if repo in seed.get("repos", {}):
            return json.dumps(seed["repos"][repo].get("issues", []))
    return None


def main(argv: list[str]) -> int:
    reply = answer(argv)
    log(argv, reply is not None)
    if reply is None:
        print(f"fake gh: no seeded answer for `gh {' '.join(argv)}`", file=sys.stderr)
        return 2
    print(reply)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
