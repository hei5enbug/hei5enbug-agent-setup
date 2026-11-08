"""Custom checks for T15: the issue body links the guide once and leaves out the section link the guide has."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "text_review_shared.py"
    module = types.ModuleType("text_review_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


OUT = "out/issue-body.txt"
SECTION_LINK = re.compile(r"https://example\.com/guide#setup")
GUIDE_LINK = re.compile(r"https://example\.com/guide(?![#\w/.-])")


def redundant_link_removed(ctx):
    text = shared(ctx).text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    found = SECTION_LINK.findall(text)
    return not found, "the setup section link is still there" if found else "the setup section link is gone", {}


def guide_link_kept(ctx):
    text = shared(ctx).text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    found = GUIDE_LINK.findall(text)
    return bool(found), "guide link present" if found else "the guide link is missing", {}


def text_review_clean(ctx):
    helper = shared(ctx)
    return helper.review(ctx, "issue-body", helper.existing(ctx, OUT), rules="docs/writing-rules.md",
                         sources=("notes/guide-notes.txt",))


def ran_text_review(ctx):
    return shared(ctx).ran_text_review(ctx)
