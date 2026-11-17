#!/usr/bin/env python3
"""A fake `orca` command for the T81 evaluation: terminals, screens, idle waits, sends, and an empty orchestration inbox.

The state file named by FAKE_ORCA_STATE holds the terminals. Every call is appended to `calls.jsonl` beside it. The
terminals disappear `vanish_after_seconds` after the first `terminal list`, as if their tabs were closed, so the
refresh script's detached helper ends a minute or so after the run instead of waiting out its hour. A
`/reload-plugins` sent to a Claude Code terminal appends the host's reload result to that terminal's transcript, the way
the real session would. All data is fictional.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

STATE = Path(os.environ.get("FAKE_ORCA_STATE", "orca-state/state.json"))
CALLS = STATE.parent / "calls.jsonl"
VALUE_OPTIONS = frozenset({"--terminal", "--for", "--timeout-ms", "--text", "--limit", "--cursor", "--id", "--run"})
RELOADED = "<local-command-stdout>Reloaded: 7 plugins · 28 skills</local-command-stdout>"


def load() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8"))


def save(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def parse(argv: list[str]) -> tuple[list[str], dict[str, str], set[str]]:
    words: list[str] = []
    options: dict[str, str] = {}
    flags: set[str] = set()
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in VALUE_OPTIONS and index + 1 < len(argv):
            options[token] = argv[index + 1]
            index += 1
        elif token.startswith("--"):
            flags.add(token)
        else:
            words.append(token)
        index += 1
    return words, options, flags


def find(state: dict, handle: str | None) -> dict:
    for item in state["terminals"]:
        if item["handle"] == handle:
            return item
    raise LookupError(handle or "")


def answer(result: dict) -> dict:
    return {"ok": True, "result": result}


def failure(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


def view(item: dict) -> dict:
    return {key: item[key] for key in ("handle", "agentIdentity", "connected", "writable", "orphaned", "title", "worktreePath")}


def append_reload(item: dict) -> None:
    path = item.get("transcript")
    if not path:
        return
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    records = [{"type": "user", "message": {"role": "user", "content": "<command-name>/reload-plugins</command-name>"}, "timestamp": stamp},
               {"type": "system", "subtype": "local_command", "content": RELOADED, "timestamp": stamp}]
    with open(path, "a", encoding="utf-8") as stream:
        stream.write("".join(json.dumps(record) + "\n" for record in records))


def vanished(state: dict) -> bool:
    first = state.setdefault("first_list_at", time.time())
    return time.time() - first > state.get("vanish_after_seconds", 75)


def run(words: list[str], options: dict[str, str], flags: set[str], state: dict) -> dict:
    if words[:1] == ["orchestration"]:
        if words[1:2] == ["inbox"]:
            return answer({"messages": []})
        return failure("invalid_argument", "Unknown command")
    if words[:2] == ["terminal", "list"]:
        terminals = [] if vanished(state) else [view(item) for item in state["terminals"]]
        return answer({"terminals": terminals, "totalCount": len(terminals), "truncated": False})
    if words[:2] not in (["terminal", "read"], ["terminal", "wait"], ["terminal", "send"], ["terminal", "close"]):
        return failure("invalid_argument", f"Unknown command: {' '.join(words[:2])}")
    try:
        item = find(state, options.get("--terminal"))
    except LookupError:
        return failure("terminal_not_found", "No such terminal")
    if words[1] == "read":
        return answer({"terminal": {"handle": item["handle"], "tail": item["screen"], "draft": item.get("draft")}})
    if words[1] == "wait":
        if item.get("idle"):
            return answer({"wait": {"satisfied": True}})
        return failure("timeout", "The terminal did not become idle")
    if words[1] == "close":
        return answer({"close": {"closed": True}})
    item.setdefault("received", []).append(options.get("--text", ""))
    if "--enter" in flags and options.get("--text") == "/reload-plugins" and item["agentIdentity"] == "claude":
        append_reload(item)
        item["screen"] = [*item["screen"][:-4], "❯ /reload-plugins", "  ⎿  Reloaded: 7 plugins · 28 skills", *item["screen"][-4:]]
    return answer({"send": {"accepted": True}})


def log(argv: list[str], ok: bool) -> None:
    with open(CALLS, "a", encoding="utf-8") as stream:
        stream.write(json.dumps({"argv": argv, "ok": ok}) + "\n")


def main(argv: list[str]) -> int:
    words, options, flags = parse(argv)
    state = load()
    payload = run(words, options, flags, state)
    save(state)
    log(argv, payload["ok"])
    sys.stdout.write(json.dumps(payload) + "\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
