"""PreToolUse hook: deny a command that creates a top-level Orca worktree.

It denies `orca worktree create` with `--no-parent` and `orca orchestration worker-start` with `--worktree
new-top-level`, also inside a command substitution; a here-document body is checked only for command
substitutions, since Bash never runs it as a command. The input is parsed only when its raw text contains orca and
one of those flags.
"""

from __future__ import annotations

import json
import os
import re
import sys

from required_checks_hook import ASSIGNMENT, WRAPPERS, command_of, segments_of

ORCA_PROGRAMS = frozenset({"orca", "orca-dev", "orca-ide"})
HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
MAX_TEXTS = 64
REASON = (
    "Blocked: this command creates a top-level Orca worktree. Put a new worktree under an existing workspace so "
    "every worktree of one ticket stays in one group: use `--parent-worktree active` in this repository, "
    "`--parent-worktree id:<repoId>::<clone path>` for another repository's workspace, or the group root's id for a "
    "task that changes several repositories; with orchestration, use `--worktree new-child` or an existing "
    "worktree. Only when Orca lists no workspace for the repository, or the user asked for a top-level worktree in "
    "this conversation, create it with a parent and then run `orca worktree set --worktree <id> --no-parent "
    "--json`."
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


def substitutions(text: str) -> list[str]:
    """Return the contents of each outermost `$(...)` and backtick command substitution."""
    found: list[str] = []
    index = 0
    while index < len(text):
        if text.startswith("$(", index) and not text.startswith("$((", index):
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
            pending.extend(substitutions(body))
    return checked


def main() -> int:
    raw = sys.stdin.read()
    if "orca" not in raw or ("no-parent" not in raw and "new-top-level" not in raw):
        return 0
    command = command_of(raw)
    if command is not None and any(
        creates_top_level_worktree(tokens) for text in texts_to_check(command) for tokens in segments_of(text)
    ):
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": REASON,
            }
        }
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
