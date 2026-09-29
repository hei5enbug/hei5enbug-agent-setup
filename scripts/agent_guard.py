from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


CODEX_BUILT_INS = {"default", "explorer"}
TOML_NAME = re.compile(r'^name\s*=\s*"([^"]+)"', re.MULTILINE)
MARKDOWN_NAME = re.compile(r"^name:\s*(.+?)\s*$", re.MULTILINE)


def toml_name(text: str) -> str | None:
    match = TOML_NAME.search(text)
    return match[1] if match else None


def markdown_name(text: str) -> str | None:
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    match = MARKDOWN_NAME.search(parts[1])
    return match[1].strip("\"'") if match else None


def defined_names(directories: list[Path], suffix: str, read_name) -> set[str]:
    names = set()
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.rglob(f"*{suffix}"):
            try:
                name = read_name(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            if name:
                names.add(name)
    return names


def denial(event: dict, host: str) -> str | None:
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    cwd = Path(event.get("cwd") or os.getcwd())
    if host == "codex":
        name = tool_input.get("agent_type") or "default"
        home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        defined = defined_names([home / "agents", cwd / ".codex" / "agents"], ".toml", toml_name)
        allowed = defined - CODEX_BUILT_INS
        substitute = "`scout` or `worker`"
    else:
        name = tool_input.get("subagent_type") or "general-purpose"
        if ":" in name:
            return None
        home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
        project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd)
        allowed = defined_names([home / "agents", project / ".claude" / "agents"], ".md", markdown_name)
        substitute = "`hei5enbug-agent-setup:scout` or `hei5enbug-agent-setup:worker`"
    if name in allowed:
        return None
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
