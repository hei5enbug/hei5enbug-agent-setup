"""Find the command substitutions in a word and say which files they read, so a body built by one can be scanned."""

from __future__ import annotations

import re
import shlex

import boundary_shell

HEREDOC_CAT = re.compile(r"\s*cat\s+<<-?\s*(['\"]?)([A-Za-z0-9_]+)\1[ \t]*\n")
UNRESOLVED = re.compile(r"[$`]")
READERS = frozenset({"cat"})
LITERAL_PRODUCERS = frozenset({"echo", "printf"})


def _closing_parenthesis(text: str, start: int) -> int | None:
    """The index of the `)` that closes a `$(` whose inner text begins at `start`."""
    heredoc = HEREDOC_CAT.match(text, start)
    if heredoc:
        delimiter = re.escape(heredoc.group(2))
        end = re.compile(rf"\n\t*{delimiter}[ \t]*(?:\n[ \t]*)?\)").search(text, heredoc.end() - 1)
        return end.end() - 1 if end else None
    depth, quote, index = 1, "", start
    while index < len(text):
        char = text[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _closing_backtick(text: str, start: int) -> int | None:
    index = start
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == "`":
            return index
        index += 1
    return None


def _spans(text: str) -> list[tuple[str, bool]] | None:
    """Each substitution's inner text, and whether it is a heredoc whose body the caller already holds; None if unbalanced."""
    spans: list[tuple[str, bool]] = []
    index = 0
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text.startswith("$(", index):
            end = _closing_parenthesis(text, index + 2)
            if end is None:
                return None
            spans.append((text[index + 2 : end], HEREDOC_CAT.match(text, index + 2) is not None))
            index = end + 1
        elif text[index] == "`":
            end = _closing_backtick(text, index + 1)
            if end is None:
                return None
            spans.append((text[index + 1 : end], False))
            index = end + 1
        else:
            index += 1
    return spans


def _files_read(inner: str) -> list[str] | None:
    """The files a `cat` or the literal text an `echo` or `printf` produces, or None when the output is not known."""
    try:
        words = shlex.split(inner)
    except ValueError:
        return None
    words = boundary_shell.strip_prefix(words)
    if not words or UNRESOLVED.search(inner):
        return None
    name = words[0]
    if name in LITERAL_PRODUCERS:
        return []
    if name not in READERS:
        return None
    files = [*(boundary_shell.producer_files(words) or ()), *boundary_shell.redirect_files(words)]
    return files or None


def substitution_files(text: str) -> list[str] | None:
    """The files every command substitution in `text` reads; None when one produces output that cannot be known.

    A heredoc substitution is complete in the text itself, so it names no file.
    """
    spans = _spans(text)
    if spans is None:
        return None
    files: list[str] = []
    for inner, heredoc in spans:
        if heredoc:
            continue
        read = _files_read(inner)
        if read is None:
            return None
        files.extend(read)
    return files
