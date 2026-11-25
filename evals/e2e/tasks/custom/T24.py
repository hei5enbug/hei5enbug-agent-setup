"""Custom check for T24: the second draft says the cache runs once before it is deleted."""

from __future__ import annotations

import re
from pathlib import Path

OUT = "out/comment-draft.txt"
ONCE = re.compile(r"한\s*(?:번|차례)|1\s*(?:회|번)|단\s*한|once|one time", re.I)
RUN = re.compile(r"실행|작동|구동|\bruns?\b|execut(?:e|ion)", re.I)
DELETE = re.compile(r"삭제|지[웁운워우]|정리|제거|delet|remov|clear", re.I)
AFTER = re.compile(r"뒤|후|이어서|다음|이어|then|after|later", re.I)
RUN_FIRST = re.compile(r"(?:실행|작동|구동)\S*\s*(?:되기\s*)?전|\bbefore\b[^.]*\b(?:run|execut)", re.I)


def read(ctx):
    path = Path(ctx.repo) / OUT
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None


def sentences(text):
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def runs_before_delete(line):
    run = RUN.search(line)
    if not (ONCE.search(line) and run):
        return False
    deletion = DELETE.search(line)
    if deletion is None:
        return False
    if re.search(r"(?:삭제|제거|정리)\S*\s*(?:되기\s*)?전|지우기\s*전|\bbefore\b[^.]*\b(?:delet|remov)", line, re.I):
        return True
    return run.start() < deletion.start() and not RUN_FIRST.search(line)


def run_before_delete_stated(ctx):
    text = read(ctx)
    if text is None:
        return False, f"{OUT} is missing", {}
    lines = sentences(text)
    for index, line in enumerate(lines):
        if runs_before_delete(line):
            return True, "the cache is said to run once before it is deleted", {}
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if ONCE.search(line) and RUN.search(line) and DELETE.search(following) and AFTER.search(following):
            return True, "the cache is said to run once, then to be deleted", {}
    return False, "no text says the cache runs once before it is deleted", {}
