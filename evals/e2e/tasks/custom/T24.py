"""Custom check for T24: the second draft says the cache runs once before it is deleted."""

from __future__ import annotations

import re
from pathlib import Path

OUT = "out/comment-draft.txt"
ONCE = re.compile(r"한 번|1회|한 차례")
DELETE = re.compile(r"삭제|지웁|지운|지워")
AFTER = re.compile(r"뒤|후|이어서|다음")
RUN_FIRST = re.compile(r"실행\S*\s*(되기\s*)?전")


def read(ctx):
    path = Path(ctx.repo) / OUT
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None


def sentences(text):
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def runs_before_delete(line):
    if not (ONCE.search(line) and "실행" in line):
        return False
    deletion = DELETE.search(line)
    if deletion is None:
        return False
    if re.search(r"삭제\S*\s*(되기\s*)?전|지우기\s*전", line):
        return True
    return line.index("실행") < deletion.start() and not RUN_FIRST.search(line)


def run_before_delete_stated(ctx):
    text = read(ctx)
    if text is None:
        return False, f"{OUT} is missing", {}
    lines = sentences(text)
    for index, line in enumerate(lines):
        if runs_before_delete(line):
            return True, "the cache is said to run once before it is deleted", {}
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if ONCE.search(line) and "실행" in line and DELETE.search(following) and AFTER.search(following):
            return True, "the cache is said to run once, then to be deleted", {}
    return False, "no text says the cache runs once before it is deleted", {}
