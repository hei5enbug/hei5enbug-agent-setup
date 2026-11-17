"""Custom checks for T63: the dialog that asks whether to delete two checklist lines of an issue draft."""

from __future__ import annotations

import types
from pathlib import Path

FLAGGED = ("빈 보고서", "형식 목록")
ALL_LINES = ("열 이름", "빈 보고서", "종료 코드 2", "쉼표", "형식 목록")
BANNED = ("acceptance criteria", "regression", "criterion", "reviewer")


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "question_shared.py"
    module = types.ModuleType("question_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def asked(ctx):
    return shared(ctx).asked(ctx)


def flagged_lines_named(ctx):
    return shared(ctx).names_all(ctx, FLAGGED)


def plain_words(ctx):
    return shared(ctx).avoids_words(ctx, BANNED)


def delete_and_keep_options(ctx):
    return shared(ctx).delete_and_keep_options(ctx, FLAGGED)


def picture_of_all_lines(ctx):
    """A preview holds the key words of all five lines; on a host without a preview, the question text below its first
    line holds them in a drawn line."""
    helper = shared(ctx)
    found = helper.dialog(ctx)
    if found is None:
        return False, "no question dialog was opened", {}
    previews = [option["preview"] for option in helper.options_of(found)] if found["tool"] == helper.PREVIEW_TOOL else []
    texts = [helper.below_first_line(question["question"]) for question in found["questions"]]
    complete = [text for text in previews if not helper.missing_words(text, ALL_LINES)]
    complete += [text for text in texts if not helper.missing_words(text, ALL_LINES) and helper.DRAWN.search(text)]
    return bool(complete), f"{len(complete)} text(s) hold all five lines", {}


def no_free_form_label(ctx):
    return shared(ctx).no_free_form_label(ctx)
