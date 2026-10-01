from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path


CLAUDE_BUILT_INS = {"general-purpose", "explore", "plan", "claude", "fork"}
CODEX_BUILT_INS = {"default", "explorer"}


def toml_name(text: str) -> str | None:
    try:
        name = tomllib.loads(text).get("name")
    except tomllib.TOMLDecodeError:
        return None
    return name if isinstance(name, str) and name else None


def defined_codex_roles(directories: list[Path]) -> set[str]:
    names = set()
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.rglob("*.toml"):
            try:
                name = toml_name(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            if name:
                names.add(name)
    return names


def denial(event: dict, host: str) -> str | None:
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    if host == "codex":
        name = tool_input.get("agent_type") or "default"
        cwd = Path(event.get("cwd") or os.getcwd())
        home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        allowed = defined_codex_roles([home / "agents", cwd / ".codex" / "agents"]) - CODEX_BUILT_INS
        if name in allowed:
            return None
        substitute = "`scout` or `worker`"
    else:
        name = tool_input.get("subagent_type") or "general-purpose"
        if str(name).lower() not in CLAUDE_BUILT_INS:
            return None
        substitute = "`hei5enbug-agent-setup:scout` or `hei5enbug-agent-setup:worker`"
    return (
        f"The built-in `{name}` agent is disabled while hei5enbug-agent-setup is installed. "
        f"Use {substitute}, another defined agent, or the main session."
    )


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (OSError, ValueError):
        return 0
    if not isinstance(event, dict) or event.get("hook_event_name") != "PreToolUse":
        return 0
    root = Path(__file__).resolve().parents[1]
    codex_root = os.environ.get("PLUGIN_ROOT")
    host = "codex" if codex_root and Path(codex_root).resolve() == root else "claude"
    reason = denial(event, host)
    if reason:
        output = {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}
        print(json.dumps({"hookSpecificOutput": output}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
