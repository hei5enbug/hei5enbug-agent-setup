"""Find the paths a shell command writes to."""

from __future__ import annotations

import shlex

SEPARATORS = {";", "&&", "||", "|"}


def segments(command: str) -> list[list[str]]:
    result: list[list[str]] = [[]]
    for token in shlex.split(command):
        if token in SEPARATORS:
            result.append([])
        else:
            result[-1].append(token)
    return [segment for segment in result if segment]


def write_targets(command: str) -> list[str]:
    found: list[str] = []
    for tokens in segments(command):
        for index, token in enumerate(tokens):
            if token in (">", ">>") and index + 1 < len(tokens):
                found.append(tokens[index + 1])
            elif token.startswith(">>") and len(token) > 2:
                found.append(token[2:])
            elif token.startswith(">") and len(token) > 1 and not token.startswith(">&"):
                found.append(token[1:])
        name = tokens[0]
        arguments = [token for token in tokens[1:] if not token.startswith("-")]
        if name == "tee":
            found.extend(arguments)
        elif name in ("cp", "mv") and len(arguments) >= 2:
            found.append(arguments[-1])
    return found
