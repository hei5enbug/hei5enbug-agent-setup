"""Whether a call changes a path inside the run's repository.

A write to a temporary folder or to any other path outside the repository is not an edit of the work. A file-editing tool
counts by the path it is given, and a shell command counts when one of the paths it writes resolves inside the repository.
A command's working folder starts at the repository and follows each `cd`. A path that cannot be resolved, such as one
behind a variable the command does not set, counts as inside, so an unreadable write is never taken for a harmless one.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Mapping

PATH_KEYS = ("file_path", "notebook_path", "path")
PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$", re.MULTILINE)
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n(.*?)\n[ \t]*\2[ \t]*(?=\n|$)", re.DOTALL)
SEGMENT_SPLIT = re.compile(r"&&|\|\||;|\n")
REDIRECT = re.compile(r"(?<![<>&\d])>>?(?![>&])\s*(\"[^\"]*\"|'[^']*'|[^\s;&|<>()]+)")
ASSIGNMENT = re.compile(r"(?:^|[\s;&|])([A-Za-z_]\w*)=(\$\(mktemp[^)]*\)|\"[^\"]*\"|'[^']*'|[^\s;&|]+)")
CD = re.compile(r"^\s*cd\s+(\"[^\"]*\"|'[^']*'|\S+)")
TEE = re.compile(r"\btee\b((?:\s+(?:-\w+|\"[^\"]*\"|'[^']*'|[^\s;&|<>()-][^\s;&|<>()]*))+)")
SED_INPLACE = re.compile(r"\bsed\s+(?:-\w*i\w*|--in-place)\b(.*)")
FILE_COMMAND = re.compile(r"\b(mv|cp|rm|touch|truncate|patch)\b((?:\s+(?:\"[^\"]*\"|'[^']*'|[^\s;&|<>()]+))*)")
GIT_WRITE = re.compile(r"\bgit\s+(?:apply|mv|rm|restore|checkout\s+--)\b")
PYTHON_WRITE = re.compile(r"\bwrite_text\b|\.write\(|\bopen\([^)]*[\"'][wax+]")
LITERAL = re.compile(r"[\"']([^\"'\n]+)[\"']")
PATH_LIKE = re.compile(r"[\w.~/-]+")


def unquote(token: str) -> str:
    token = token.strip()
    return token[1:-1] if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'" else token


def real(path: str | Path) -> str:
    return os.path.realpath(str(path))


def inside(path: str, repo: str) -> bool:
    return path == repo or path.startswith(repo + os.sep)


def resolve(token: str, cwd: str, assigned: Mapping[str, str]) -> str | None:
    """The absolute, normalized path a shell word names, or None when a variable keeps it unknown."""
    word = unquote(token)
    if word.startswith("~"):
        word = os.path.expanduser(word)
    variable = re.match(r"\$\{?(\w+)\}?(.*)", word)
    if variable:
        name, rest = variable.groups()
        value = assigned.get(name, os.environ.get(name) if name in ("HOME", "TMPDIR") else None)
        if value is None:
            return None
        word = value + rest
    if "$" in word or "`" in word:
        return None
    return real(os.path.join(cwd, word))


def assignments_of(shell: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for name, value in ASSIGNMENT.findall(shell):
        found[name] = "/tmp/mktemp" if value.startswith("$(mktemp") else unquote(value)
    return found


def targets_of(segment: str) -> list[str]:
    """The paths one shell segment writes, as words."""
    found = [unquote(match) for match in REDIRECT.findall(segment) if unquote(match) != "/dev/null"]
    for match in TEE.finditer(segment):
        found += [unquote(token) for token in re.findall(r"\"[^\"]*\"|'[^']*'|\S+", match.group(1)) if not token.startswith("-")]
    inplace = SED_INPLACE.search(segment)
    if inplace:
        words = [unquote(token) for token in re.findall(r"\"[^\"]*\"|'[^']*'|\S+", inplace.group(1))]
        found += [word for word in words[-1:] if not word.startswith("-")]
    for match in FILE_COMMAND.finditer(segment):
        words = [unquote(token) for token in re.findall(r"\"[^\"]*\"|'[^']*'|\S+", match.group(2)) if not token.startswith("-")]
        found += words[-1:] if match.group(1) in ("cp", "mv") and len(words) > 1 else words
    return found


def shell_writes_inside(command: str, repo: str) -> bool:
    """Whether a shell command writes a path inside `repo`."""
    bodies: list[str] = []

    def hide(match: re.Match[str]) -> str:
        bodies.append(match.group(3))
        return f"<<BODY{len(bodies) - 1}"

    shell = HEREDOC.sub(hide, command)
    assigned = assignments_of(shell)
    cwd = repo
    for segment in SEGMENT_SPLIT.split(shell):
        change = CD.match(segment)
        if change:
            moved = resolve(change.group(1), cwd, assigned)
            cwd = moved if moved is not None else cwd
            continue
        resolved = [resolve(target, cwd, assigned) for target in targets_of(segment)]
        if any(path is None or inside(path, repo) for path in resolved):
            return True
        if GIT_WRITE.search(segment) and inside(real(cwd), repo):
            return True
        owned = segment + "\n".join(bodies[int(index)] for index in re.findall(r"<<BODY(\d+)", segment))
        if PYTHON_WRITE.search(owned):
            literals = [text for text in LITERAL.findall(owned) if PATH_LIKE.fullmatch(text) and ("/" in text or "." in text)]
            paths = [resolve(text, cwd, assigned) for text in literals if not text.startswith(("http", "-"))]
            if any(path is None or inside(path, repo) for path in paths) or (not paths and inside(real(cwd), repo)):
                return True
    return False


def tool_writes_inside(call: Mapping[str, Any], repo: str) -> bool:
    """Whether a file-editing tool call names a path inside `repo`; a call that names none counts as inside."""
    arguments = call.get("input") if isinstance(call.get("input"), Mapping) else {}
    paths = [str(arguments[key]) for key in PATH_KEYS if arguments.get(key)]
    for value in arguments.values():
        if isinstance(value, str):
            paths += PATCH_FILE.findall(value)
    if not paths:
        return True
    return any(inside(real(os.path.join(repo, path)), repo) for path in paths)
