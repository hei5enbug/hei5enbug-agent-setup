from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import codex_hook_trust
from role_runner_child import child_environment
from role_runner_config import EXIT_RUN, GUARD_COMMAND, SHELL_TOOL, RunnerError


def read_reply(stream, message_id: int) -> dict | None:
    """Read JSON lines until the message with this id, ignoring messages without it; None when the stream ends first."""
    for line in iter(stream.readline, ""):
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            raise RunnerError(EXIT_RUN, "The Codex app-server wrote a line that is not JSON") from error
        if isinstance(message, dict) and message.get("id") == message_id:
            return message
    return None


def send_line(child: subprocess.Popen, message: dict) -> None:
    child.stdin.write(json.dumps(message) + "\n")
    child.stdin.flush()


def exchange_hooks(child: subprocess.Popen, cwd: str) -> tuple[str, dict | None]:
    """Initialize the app-server and ask for the folder's hooks; return the last method sent and its reply."""
    send_line(child, {"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "role_runner", "version": "1"}}})
    reply = read_reply(child.stdout, 1)
    if reply is None or "error" in reply:
        return "initialize", reply
    send_line(child, {"method": "initialized"})
    send_line(child, {"id": 2, "method": "hooks/list", "params": {"cwds": [cwd]}})
    return "hooks/list", read_reply(child.stdout, 2)


def hooks_for_cwd(result: object, cwd: str) -> list:
    """Return the hook list of the entry for this folder in a hooks/list result."""
    data = result.get("data") if isinstance(result, dict) else None
    wanted = Path(cwd).resolve()
    for entry in data if isinstance(data, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("cwd"), str) and Path(entry["cwd"]).resolve() == wanted:
            hooks = entry.get("hooks")
            return hooks if isinstance(hooks, list) else []
    raise RunnerError(EXIT_RUN, f"codex app-server listed no hooks entry for {cwd}")


def covers_shell(matcher: object) -> bool:
    """Whether a hook matcher selects the shell tool; an empty matcher selects every tool and an invalid regex none."""
    if matcher is None or matcher in ("", "*"):
        return True
    if not isinstance(matcher, str):
        return False
    try:
        return re.search(matcher, SHELL_TOOL) is not None
    except re.error:
        return False


def is_guard_hook(hook: object) -> bool:
    return (
        isinstance(hook, dict) and hook.get("eventName") == "preToolUse"
        and isinstance(hook.get("command"), str) and GUARD_COMMAND.fullmatch(hook["command"]) is not None
    )


def guard_hook_ready(hook: dict) -> bool:
    """Whether a guard PreToolUse hook runs before every shell call: a sync command hook, enabled, trusted or managed."""
    return (
        hook.get("handlerType") == "command" and hook.get("enabled") is True and hook.get("async") is False
        and (hook.get("trustStatus") == "trusted" or hook.get("isManaged") is True) and covers_shell(hook.get("matcher"))
    )


def guard_ready(listed: list) -> bool:
    return any(guard_hook_ready(hook) for hook in listed if is_guard_hook(hook))


def heal_hooks(marker: str, mcp_off: list[str], cwd: str, timeout: int, listed: list) -> tuple[list, str | None]:
    """Re-trust this plugin's hooks that a release left untrusted, from a verified official copy only; return the hooks
    Codex lists afterwards, or the unchanged list and the reason nothing was trusted."""
    if not codex_hook_trust.candidates(listed):
        return listed, None
    try:
        healed = codex_hook_trust.heal(listed, ["codex", "app-server", *mcp_off], child_environment(marker), cwd, timeout)
    except codex_hook_trust.TrustError as error:
        return listed, str(error)
    return healed, None
