#!/usr/bin/env python3
"""A fake `claude` or `codex` command for the T81 evaluation, chosen by the name it is installed under.

`claude plugin list --json` names the plugin copy under FAKE_PLUGIN_STATE and `claude --version` a release; `codex plugin
list --json` lists no plugin. Every call is appended to `plugin-calls.jsonl` beside the state. All data is fictional.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

STATE = Path(os.environ.get("FAKE_PLUGIN_STATE", "plugin-state/state.json"))
CALLS = STATE.parent / "plugin-calls.jsonl"


def main(argv: list[str]) -> int:
    program = Path(sys.argv[0]).name
    state = json.loads(STATE.read_text(encoding="utf-8"))
    with open(CALLS, "a", encoding="utf-8") as stream:
        stream.write(json.dumps({"program": program, "argv": argv}) + "\n")
    if argv[:3] == ["plugin", "list", "--json"]:
        if program == "claude":
            print(json.dumps([state["claude_record"]]))
        else:
            print(json.dumps({"installed": []}))
        return 0
    if argv[:1] == ["--version"]:
        print(f"{state['release']} (Claude Code)" if program == "claude" else "codex-cli 0.0.0")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
