"""PreToolUse hook: before a git commit or push, remind the agent to list the checks its instructions require.

It only adds context and never blocks. The input is parsed only when its raw text contains git and a commit or push
word.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys

SEPARATORS = "();<>|&\n"
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
    """Split a command into simple commands, keeping quoted separators inside their words."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=SEPARATORS)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    segments: list[list[str]] = [[]]
    try:
        for token in lexer:
            if token and all(char in SEPARATORS for char in token):
                segments.append([])
            else:
                segments[-1].append(token)
    except ValueError:
        return [segment.split() for segment in FALLBACK_SPLIT.split(command)]
    return [segment for segment in segments if segment]


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
    sys.exit(main())
