"""PreToolUse hook: before a git commit or push, remind the agent to list the checks its instructions require.

It only adds context and never blocks. The input is parsed only when its raw text contains git and a commit or push
word.
"""

from __future__ import annotations

import json
import os
import re
import sys

SEPARATORS = "();<>|&\n"
WHITESPACE = " \t\r"
QUOTES = "'\""
CONTROL_WORDS = frozenset({"if", "then", "else", "elif", "do", "while", "until", "!", "{"})
FALLBACK_SPLIT = re.compile(r"&&|\|\||[;|&()\n]")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
WRAPPERS = frozenset({"env", "command", "time", "exec", "nohup"})
OPTIONS_WITH_VALUE = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix"})
REQUIRED_SUBCOMMANDS = frozenset({"commit", "push"})
MESSAGE = (
    "Before a commit or push, the reply lists each check that the project instructions or a changed skill "
    "require for this change, such as an evaluation, a test run, or a final review, as done or as not done with "
    "its reason. A required check is never waived by judging the change small or reference-only, and a commit or "
    "push with a check not done waits until the user agrees after seeing that list."
)


def segments_of(command: str) -> list[list[str]]:
    """Split a command into simple commands; quoted or escaped separators stay inside their words."""
    try:
        return split_segments(command)
    except ValueError:
        return [segment.split() for segment in FALLBACK_SPLIT.split(command)]


def split_segments(command: str) -> list[list[str]]:
    segments: list[list[str]] = [[]]
    word: list[str] = []
    in_word = False
    quote = ""
    escaped = False

    def end_word() -> None:
        nonlocal in_word
        if in_word:
            segments[-1].append("".join(word))
            word.clear()
            in_word = False

    for char in command:
        if escaped:
            if char != "\n":
                word.append(char)
            escaped = False
        elif quote:
            if char == quote:
                quote = ""
            elif char == "\\" and quote == '"':
                escaped = True
            else:
                word.append(char)
        elif char == "\\":
            escaped, in_word = True, True
        elif char in QUOTES:
            quote, in_word = char, True
        elif char in SEPARATORS:
            end_word()
            segments.append([])
        elif char in WHITESPACE:
            end_word()
        else:
            word.append(char)
            in_word = True
    if quote or escaped:
        raise ValueError("unterminated quote or escape")
    end_word()
    return [without_control_words(segment) for segment in segments if segment]


def without_control_words(tokens: list[str]) -> list[str]:
    index = 0
    while index < len(tokens) and tokens[index] in CONTROL_WORDS:
        index += 1
    return tokens[index:]


def git_subcommand(tokens: list[str]) -> str | None:
    index = 0
    while index < len(tokens) and (ASSIGNMENT.match(tokens[index]) or tokens[index] in WRAPPERS):
        index += 1
    if index >= len(tokens) or os.path.basename(tokens[index]) != "git":
        return None
    index += 1
    while index < len(tokens) and tokens[index].startswith("-"):
        index += 2 if tokens[index] in OPTIONS_WITH_VALUE else 1
    return tokens[index] if index < len(tokens) else None


def runs_commit_or_push(command: str) -> bool:
    return any(git_subcommand(tokens) in REQUIRED_SUBCOMMANDS for tokens in segments_of(command))


def command_of(raw: str) -> str | None:
    try:
        event = json.loads(raw)
    except ValueError:
        return None
    tool_input = event.get("tool_input") if isinstance(event, dict) else None
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    return command if isinstance(command, str) else None


def main() -> int:
    raw = sys.stdin.read()
    if "git" not in raw or ("commit" not in raw and "push" not in raw):
        return 0
    command = command_of(raw)
    if command is not None and runs_commit_or_push(command):
        output = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": MESSAGE}}
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    import hook_runtime

    sys.exit(hook_runtime.run("required_checks_hook.py", main))
