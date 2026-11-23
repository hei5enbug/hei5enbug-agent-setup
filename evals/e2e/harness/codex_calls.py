"""Turn the shell, patch, and question calls in copied Codex rollouts into tool calls the graders can see."""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

CALL_TYPES = frozenset({"function_call", "local_shell_call", "custom_tool_call"})
OUTPUT_TYPES = frozenset({"function_call_output", "local_shell_call_output", "custom_tool_call_output"})
NATIVE_AGENT_TOOL = "spawn_agent"
QUESTION_TOOL = "request_user_input"
FINAL_ANSWER_HEADER = re.compile(r"\AMessage Type: FINAL_ANSWER\s*\nTask name: [^\n]*\nSender: (/root/[^\n]+)\nPayload:\n?(.*)\Z", re.S)
CHILD_ERROR_PREFIX = "Agent errored:"
SHELL_WRAPPERS = frozenset({"bash", "sh", "zsh"})
JS_COMMAND = re.compile(r"""\bcmd\s*:\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|`((?:[^`\\]|\\.)*)`)""", re.S)
JS_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
TOOL_STATEMENT = re.compile(r"\btools\.(\w+)\s*\(")
SESSION_ARGUMENT = re.compile(r"\bsession_id\s*:\s*(\d+)")
SCRIPT_HEADER = "Script "
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


def _final_answers(events: list[dict[str, Any]]) -> list[tuple[int, str, str]]:
    """(event index, sender path, payload) of every child final result a rollout received as an `agent_message`."""
    found: list[tuple[int, str, str]] = []
    for index, event in enumerate(events):
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event.get("type") != "response_item" or payload.get("type") != "agent_message":
            continue
        parts = payload.get("content") if isinstance(payload.get("content"), list) else []
        text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
        match = FINAL_ANSWER_HEADER.match(text)
        if match:
            found.append((index, match.group(1), match.group(2).strip()))
    return found


def _child_path(arguments: dict[str, Any], acknowledgement: str) -> str:
    """The path `/root/<task_name>` that names the child: the one the spawn acknowledgement reports, else the call's own."""
    try:
        reported = json.loads(acknowledgement).get("task_name")
    except (ValueError, AttributeError):
        reported = None
    name = reported if isinstance(reported, str) and reported else str(arguments.get("task_name") or "")
    return name if name.startswith("/") else f"/root/{name}"


def _native_agent_call(
    call_id: str, payload: dict[str, Any], acknowledgement: str, is_error: bool, source: str, final: str | None,
) -> dict[str, Any]:
    """A native subagent call (`spawn_agent`) shaped like a Claude `Agent` call, so delegation metrics see the role it names.
    Its result is the child's final result; the spawn acknowledgement alone leaves the result empty, so the call is not complete."""
    arguments = _arguments(payload)
    tool_input = {"subagent_type": str(arguments.get("agent_type") or "general-purpose"),
                  "prompt": str(arguments.get("message") or ""), "task_name": arguments.get("task_name"),
                  "model": arguments.get("model"), "reasoning_effort": arguments.get("reasoning_effort")}
    spawned = _spawn_succeeded(acknowledgement)
    failed = is_error or not spawned or (final or "").startswith(CHILD_ERROR_PREFIX)
    return _call(f"codex:{call_id}", NATIVE_AGENT_TOOL, tool_input, final or "", failed, source)


def _spawn_succeeded(acknowledgement: str) -> bool:
    try:
        body = json.loads(acknowledgement)
    except ValueError:
        return False
    return isinstance(body, dict) and bool(body.get("task_name"))


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


def tool_statements(source: str) -> list[tuple[str, str | None]]:
    """(tool name, session id its arguments name) of every `tools.<name>(` statement of a script, in source order."""
    matches = list(TOOL_STATEMENT.finditer(source))
    ends = [match.start() for match in matches[1:]] + [len(source)]
    statements: list[tuple[str, str | None]] = []
    for match, end in zip(matches, ends):
        session = SESSION_ARGUMENT.search(source, match.end(), end)
        statements.append((match.group(1), session.group(1) if session else None))
    return statements


def exec_items(output: Any) -> list[str] | None:
    """The texts of an exec output after its `Script ...` header item, or None when the output has no such header."""
    if not isinstance(output, list):
        return None
    texts = [str(item.get("text", "")) for item in output if isinstance(item, dict)]
    return texts[1:] if texts and texts[0].startswith(SCRIPT_HEADER) else None


def chunk_of(text: str) -> dict[str, Any]:
    """The JSON object an exec_command or write_stdin item holds, or {} when the item is plain text."""
    try:
        body = json.loads(text)
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def chunk_output(text: str, chunk: dict[str, Any]) -> str:
    return chunk["output"] if isinstance(chunk.get("output"), str) else text


def chunk_code(chunk: dict[str, Any]) -> int | None:
    code = chunk.get("exit_code")
    return code if isinstance(code, int) and not isinstance(code, bool) else None


def _extend(calls: list[dict[str, Any]], position: int, output: str, code: int | None) -> list[dict[str, Any]]:
    call = calls[position]
    updated = {**call, "result_text": call["result_text"] + output, "is_error": bool(call["is_error"] or code)}
    return [*calls[:position], updated, *calls[position + 1:]]


def _polled(
    calls: list[dict[str, Any]], pending: dict[str, int], session: str | None, text: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Append the output of a write_stdin poll to the call that session started; a chunk with an exit code ends it."""
    chunk = chunk_of(text)
    position = pending.get(session or "")
    if position is None:
        return calls, pending
    code = chunk_code(chunk)
    rest = pending if code is None else {key: value for key, value in pending.items() if key != session}
    return _extend(calls, position, chunk_output(text, chunk), code), rest


def _started(
    calls: list[dict[str, Any]], pending: dict[str, int], call_id: str, index: int, command: str, text: str, source: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Add the Bash call of one exec_command statement; a chunk with a session id and no exit code stays pending."""
    chunk = chunk_of(text)
    code = chunk_code(chunk)
    call = _call(f"codex:{call_id}:{index}", "Bash", {"command": command}, chunk_output(text, chunk), bool(code), source)
    waiting = code is None and chunk.get("session_id") is not None
    rest = {**pending, str(chunk["session_id"]): len(calls)} if waiting else pending
    return [*calls, call], rest


def _exec_calls(
    payload: dict[str, Any], call_id: str, output: Any, source: str, calls: list[dict[str, Any]], pending: dict[str, int],
) -> tuple[list[dict[str, Any]], dict[str, int]] | None:
    """The calls and pending sessions after an exec script whose output items pair with its statements one to one;
    None when they do not pair."""
    statements, items, commands = tool_statements(payload["input"]), exec_items(output), commands_of(payload)
    if items is None or len(items) != len(statements) or sum(name == "exec_command" for name, _ in statements) != len(commands):
        return None
    index = 0
    for (name, session), text in zip(statements, items):
        if name == "exec_command":
            calls, pending = _started(calls, pending, call_id, index, commands[index], text, source)
            index += 1
        elif name == "write_stdin":
            calls, pending = _polled(calls, pending, session, text)
    return calls, pending


def _joined_calls(
    payload: dict[str, Any], call_id: str, text: str, code: int | None, source: str, calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """One call per command; the whole output goes to the first of them."""
    added = [_call(f"codex:{call_id}:{index}", "Bash", {"command": command}, text if index == 0 else "",
                   bool(code) and index == 0, source) for index, command in enumerate(commands_of(payload))]
    return [*calls, *added]


def rollout_tool_calls(events: list[dict[str, Any]], role: str, rollout_name: str) -> list[dict[str, Any]]:
    """Bash, apply_patch, `request_user_input`, and native `spawn_agent` calls of one rollout. A script with several commands gives one call per command. When the
    output items of an exec script pair one to one with its `tools.<name>(` statements, each command gets its own
    result and a later `write_stdin` poll extends the call of its session; otherwise the script's whole output is
    attached to the first of its commands."""
    outputs = _outputs(events)
    finals = _final_answers(events)
    claimed: set[int] = set()
    source = f"codex:{role or 'unknown'}"
    calls: list[dict[str, Any]] = []
    pending: dict[str, int] = {}
    for position, event in enumerate(events):
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event.get("type") != "response_item" or payload.get("type") not in CALL_TYPES:
            continue
        call_id = str(payload.get("call_id") or payload.get("id") or f"{rollout_name}:{len(calls)}")
        done = outputs.get(call_id, {})
        text, code = output_text(done.get("output")), exit_code(done.get("output"))
        if payload.get("type") == "function_call" and payload.get("name") == NATIVE_AGENT_TOOL:
            path = _child_path(_arguments(payload), text)
            answer = next(((index, body) for index, sender, body in finals
                           if index > position and sender == path and index not in claimed), None)
            claimed = claimed | {answer[0]} if answer else claimed
            calls = [*calls, _native_agent_call(call_id, payload, text, bool(code), source, answer[1] if answer else None)]
            continue
        if payload.get("type") == "function_call" and payload.get("name") == QUESTION_TOOL:
            calls = [*calls, _call(f"codex:{call_id}", QUESTION_TOOL, _arguments(payload), text, bool(code), source)]
            continue
        patch = _patch_text(payload)
        if patch is not None:
            calls = [*calls, _call(f"codex:{call_id}", "apply_patch", {"patch": patch}, text, bool(code), source)]
            continue
        paired = None
        if payload.get("type") == "custom_tool_call" and payload.get("name") == "exec" and isinstance(payload.get("input"), str):
            paired = _exec_calls(payload, call_id, done.get("output"), source, calls, pending)
        if paired is not None:
            calls, pending = paired
        else:
            calls = _joined_calls(payload, call_id, text, code, source, calls)
    return calls


def codex_tool_calls(rollouts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tool calls of every loaded rollout ({role, name, events}), tagged with source `codex:<role>`."""
    calls: list[dict[str, Any]] = []
    for rollout in rollouts:
        calls += rollout_tool_calls(rollout.get("events", []), str(rollout.get("role") or "unknown"), str(rollout.get("name", "")))
    return calls
