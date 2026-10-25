"""Turn the shell and patch calls in copied Codex rollouts into tool calls the graders can see."""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

CALL_TYPES = frozenset({"function_call", "local_shell_call", "custom_tool_call"})
OUTPUT_TYPES = frozenset({"function_call_output", "local_shell_call_output", "custom_tool_call_output"})
SHELL_WRAPPERS = frozenset({"bash", "sh", "zsh"})
JS_COMMAND = re.compile(r"""\bcmd\s*:\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|`((?:[^`\\]|\\.)*)`)""", re.S)
JS_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
ESCAPE = re.compile(r"\\(?:u\{([0-9a-fA-F]+)\}|u([0-9a-fA-F]{4})|x([0-9a-fA-F]{2})|(.))", re.S)


def unescape_js(text: str) -> str:
    """Decode the escapes of a JavaScript string literal body."""
    def decode(match: re.Match[str]) -> str:
        code = match.group(1) or match.group(2) or match.group(3)
        return chr(int(code, 16)) if code else JS_ESCAPES.get(match.group(4), match.group(4))

    return ESCAPE.sub(decode, text)


def js_commands(source: str) -> list[str]:
    """Every `cmd: "<literal>"` string in a JavaScript snippet, unescaped, in source order."""
    return [unescape_js(next(part for part in match.groups() if part is not None)) for match in JS_COMMAND.finditer(source)]


def command_text(command: Any) -> str | None:
    """A shell command from a string or an argv list (`bash -lc <script>` unwraps to the script)."""
    if isinstance(command, str):
        return command
    if isinstance(command, list) and command and all(isinstance(part, str) for part in command):
        if len(command) >= 3 and command[0].rsplit("/", 1)[-1] in SHELL_WRAPPERS and command[1] in ("-c", "-lc", "-ic"):
            return command[2]
        return " ".join(command)
    return None


def output_text(output: Any) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        return "\n".join(str(item.get("text", "")) for item in output if isinstance(item, dict))
    if isinstance(output, dict):
        return str(output.get("output") or output.get("text") or json.dumps(output, ensure_ascii=False))
    return "" if output is None else str(output)


def exit_code(output: Any) -> int | None:
    """The exit code a function_call_output reports in its JSON body, when it has one."""
    if not isinstance(output, str):
        return None
    try:
        body = json.loads(output)
    except ValueError:
        return None
    metadata = body.get("metadata") if isinstance(body, dict) else None
    code = metadata.get("exit_code") if isinstance(metadata, dict) else None
    return code if isinstance(code, int) else None


def _arguments(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("arguments")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _patch_text(payload: dict[str, Any]) -> str | None:
    if payload.get("name") != "apply_patch":
        return None
    arguments = _arguments(payload)
    value = payload.get("input") if isinstance(payload.get("input"), str) else arguments.get("input") or arguments.get("patch")
    return str(value) if value else None


def commands_of(payload: dict[str, Any]) -> list[str]:
    """The shell commands one call item runs."""
    kind = payload.get("type")
    if kind == "local_shell_call":
        action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
        text = command_text(action.get("command"))
        return [text] if text else []
    if kind == "function_call":
        arguments = _arguments(payload)
        text = command_text(arguments.get("cmd") if "cmd" in arguments else arguments.get("command"))
        return [text] if text else []
    if kind == "custom_tool_call" and payload.get("name") == "exec" and isinstance(payload.get("input"), str):
        return js_commands(payload["input"])
    return []


def _outputs(events: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event.get("type") == "response_item" and payload.get("type") in OUTPUT_TYPES and payload.get("call_id"):
            found.setdefault(str(payload["call_id"]), payload)
    return found


def _call(call_id: str, name: str, tool_input: dict[str, Any], result: str, is_error: bool, source: str) -> dict[str, Any]:
    return {"id": call_id, "name": name, "input": tool_input, "result_text": result, "is_error": is_error,
            "parent": None, "source": source}


def rollout_tool_calls(events: list[dict[str, Any]], role: str, rollout_name: str) -> list[dict[str, Any]]:
    """Bash and apply_patch calls of one rollout. A script with several commands gives one call per command; the
    script's whole output is attached to the first of them."""
    outputs = _outputs(events)
    source = f"codex:{role or 'unknown'}"
    calls: list[dict[str, Any]] = []
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event.get("type") != "response_item" or payload.get("type") not in CALL_TYPES:
            continue
        call_id = str(payload.get("call_id") or payload.get("id") or f"{rollout_name}:{len(calls)}")
        done = outputs.get(call_id, {})
        text, code = output_text(done.get("output")), exit_code(done.get("output"))
        patch = _patch_text(payload)
        if patch is not None:
            calls.append(_call(f"codex:{call_id}", "apply_patch", {"patch": patch}, text, bool(code), source))
            continue
        for index, command in enumerate(commands_of(payload)):
            calls.append(_call(f"codex:{call_id}:{index}", "Bash", {"command": command}, text if index == 0 else "",
                               bool(code) and index == 0, source))
    return calls


def codex_tool_calls(rollouts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tool calls of every loaded rollout ({role, name, events}), tagged with source `codex:<role>`."""
    calls: list[dict[str, Any]] = []
    for rollout in rollouts:
        calls += rollout_tool_calls(rollout.get("events", []), str(rollout.get("role") or "unknown"), str(rollout.get("name", "")))
    return calls
