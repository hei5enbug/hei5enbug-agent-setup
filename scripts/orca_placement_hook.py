"""PreToolUse hook: deny a command that creates a top-level Orca worktree or starts an agent session on low memory.

It denies `orca worktree create` with `--no-parent` and `orca orchestration worker-start` with `--worktree
new-top-level`, also inside a command substitution; a here-document body is checked only for command
substitutions, since Bash never runs it as a command. It also denies a command that starts an agent session through
Orca when the available memory is below the `session_memory_min_mb` option. The input is parsed only when its raw
text contains orca and a word one of those rules needs.
"""

from __future__ import annotations

import json
import os
import re
import sys

import plugin_toggles
import session_memory
from required_checks_hook import ASSIGNMENT, WRAPPERS, command_of, segments_of

ORCA_PROGRAMS = frozenset({"orca", "orca-dev", "orca-ide"})
HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
MAX_TEXTS = 64
DEFAULT_MIN_MB = 2048
MEMORY_OFF_VALUES = frozenset({"0", "off", "false", "no"})
AGENT_PROGRAMS = frozenset({"claude", "codex"})
PREFILTER_WORDS = ("no-parent", "new-top-level", "--agent", "worker-start", "--command")
REASON = (
    "Blocked: this command creates a top-level Orca worktree. Put a new worktree under an existing workspace so "
    "every worktree of one ticket stays in one group: use `--parent-worktree active` in this repository, "
    "`--parent-worktree id:<repoId>::<clone path>` for another repository's workspace, or the group root's id for a "
    "task that changes several repositories; with orchestration, use `--worktree new-child` or an existing "
    "worktree. Only when Orca lists no workspace for the repository, or the user asked for a top-level worktree in "
    "this conversation, create it with a parent and then run `orca worktree set --worktree <id> --no-parent "
    "--json`."
)
MEMORY_REASON = (
    "Blocked: {available} MB of memory is available, below the {threshold} MB this plugin keeps free before "
    "starting another agent session. Do not retry now. Record the session as waiting for memory, in the root's "
    "status table when it belongs to a group, and continue work that needs no new session. Start it after a "
    "running session or worker of this task finishes or is cleaned up; never poll memory. When nothing of this "
    "task is running, tell the user in one line and suggest the session-triage skill to free memory. The user can "
    "lower `session_memory_min_mb`."
)


def orca_arguments(tokens: list[str]) -> list[str] | None:
    index = 0
    while index < len(tokens) and (ASSIGNMENT.match(tokens[index]) or tokens[index] in WRAPPERS):
        index += 1
    if index >= len(tokens) or os.path.basename(tokens[index]) not in ORCA_PROGRAMS:
        return None
    return tokens[index + 1 :]


def creates_top_level_worktree(tokens: list[str]) -> bool:
    arguments = orca_arguments(tokens)
    if arguments is None:
        return False
    pair = [token for token in arguments if not token.startswith("-")][:2]
    if pair == ["worktree", "create"]:
        return "--no-parent" in arguments
    if pair == ["orchestration", "worker-start"]:
        if "--worktree=new-top-level" in arguments:
            return True
        return any(
            token == "--worktree" and following == "new-top-level"
            for token, following in zip(arguments, arguments[1:])
        )
    return False


def option_after(arguments: list[str], name: str) -> str | None:
    """Return the value of `--name value` or `--name=value`, or None when it is absent or has no value."""
    for token, following in zip(arguments, [*arguments[1:], None]):
        if token == name and following is not None:
            return following
        if token.startswith(name + "=") and len(token) > len(name) + 1:
            return token[len(name) + 1 :]
    return None


def starts_agent_session(tokens: list[str]) -> bool:
    arguments = orca_arguments(tokens)
    if arguments is None:
        return False
    pair = [token for token in arguments if not token.startswith("-")][:2]
    if pair == ["worktree", "create"]:
        return option_after(arguments, "--agent") is not None
    if pair == ["orchestration", "worker-start"] or pair == ["agent", "launch"]:
        return True
    if pair == ["terminal", "create"]:
        command = option_after(arguments, "--command")
        return bool(command) and any(runs_agent_program(words) for words in segments_of(command))
    return False


def runs_agent_program(tokens: list[str]) -> bool:
    index = 0
    while index < len(tokens) and (ASSIGNMENT.match(tokens[index]) or tokens[index] in WRAPPERS):
        index += 1
    return index < len(tokens) and os.path.basename(tokens[index]) in AGENT_PROGRAMS


def memory_threshold_mb() -> int:
    """Return the configured minimum free memory in MB, 0 when the gate is off."""
    value = plugin_toggles.option_value("session_memory_min_mb")
    if value in MEMORY_OFF_VALUES:
        return 0
    return int(value) if re.fullmatch(r"[0-9]+", value) else DEFAULT_MIN_MB


def memory_reason() -> str | None:
    threshold = memory_threshold_mb()
    if threshold == 0:
        return None
    available = session_memory.available_mb()
    if available is None or available >= threshold:
        return None
    return MEMORY_REASON.format(available=available, threshold=threshold)


def split_heredocs(text: str) -> tuple[str, list[str]]:
    """Return the text without here-document bodies, and the bodies whose delimiter is unquoted."""
    kept: list[str] = []
    expanded: list[str] = []
    pending: list[tuple[str, bool, bool]] = []
    body: list[str] = []
    for line in text.split("\n"):
        if pending:
            delimiter, strip_tabs, unquoted = pending[0]
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                pending.pop(0)
                if unquoted:
                    expanded.append("\n".join(body))
                body = []
            else:
                body.append(line)
            continue
        kept.append(line)
        pending = [(match[3], match[1] == "-", not match[2]) for match in HEREDOC.finditer(line)]
    if pending and pending[0][2]:
        expanded.append("\n".join(body))
    return "\n".join(kept), expanded


def substitutions(text: str, shell_quotes: bool = True) -> list[str]:
    """Return the contents of each outermost `$(...)` and backtick command substitution.

    With shell quoting, an escaped `$` or backtick and text inside single quotes stay literal; a here-document body
    has no such quoting, so it is scanned with `shell_quotes` off.
    """
    found: list[str] = []
    index = 0
    in_double = False
    while index < len(text):
        char = text[index]
        if shell_quotes and char == "\\":
            index += 2
        elif shell_quotes and char == "'" and not in_double:
            end = text.find("'", index + 1)
            index = len(text) if end < 0 else end + 1
        elif shell_quotes and char == '"':
            in_double = not in_double
            index += 1
        elif text.startswith("$(", index) and not text.startswith("$((", index):
            depth, end = 1, index + 2
            while end < len(text) and depth:
                depth += {"(": 1, ")": -1}.get(text[end], 0)
                end += 1
            found.append(text[index + 2 : end - 1] if depth == 0 else text[index + 2 :])
            index = end
        elif text[index] == "`":
            end = text.find("`", index + 1)
            found.append(text[index + 1 :] if end < 0 else text[index + 1 : end])
            index = len(text) if end < 0 else end + 1
        else:
            index += 1
    return found


def texts_to_check(command: str) -> list[str]:
    pending = [command]
    checked: list[str] = []
    while pending and len(checked) < MAX_TEXTS:
        kept, bodies = split_heredocs(pending.pop())
        checked.append(kept)
        pending.extend(substitutions(kept))
        for body in bodies:
            pending.extend(substitutions(body, shell_quotes=False))
    return checked


def deny(reason: str) -> None:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(output, ensure_ascii=False))


def main() -> int:
    raw = sys.stdin.read()
    if "orca" not in raw or not (
        any(word in raw for word in PREFILTER_WORDS) or ("agent" in raw and "launch" in raw)
    ):
        return 0
    command = command_of(raw)
    if command is None:
        return 0
    segments = [tokens for text in texts_to_check(command) for tokens in segments_of(text)]
    if any(creates_top_level_worktree(tokens) for tokens in segments):
        deny(REASON)
    elif any(starts_agent_session(tokens) for tokens in segments):
        reason = memory_reason()
        if reason:
            deny(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
