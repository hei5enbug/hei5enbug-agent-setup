from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plugin_toggles import detect_host, enabled  # noqa: E402


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


def denial(event: dict) -> str | None:
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    name = tool_input.get("agent_type") or "default"
    cwd = Path(event.get("cwd") or os.getcwd())
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    allowed = defined_codex_roles([home / "agents", cwd / ".codex" / "agents"]) - CODEX_BUILT_INS
    if name in allowed:
        return None
    return (
        f"The built-in `{name}` agent is disabled while hei5enbug-agent-setup is installed. "
        "Use `scout` or `worker`, another defined agent, or the main session."
    )


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (OSError, ValueError):
        return 0
    if not isinstance(event, dict) or event.get("hook_event_name") != "PreToolUse":
        return 0
    if detect_host() != "codex" or not enabled("agent_guard"):
        return 0
    reason = denial(event)
    if reason:
        output = {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}
        print(json.dumps({"hookSpecificOutput": output}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
