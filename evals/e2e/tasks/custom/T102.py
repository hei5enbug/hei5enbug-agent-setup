"""Custom checks for T102: the next question after a stored question input that itself holds escape text."""

from __future__ import annotations

import re
import types
from pathlib import Path

SESSION = "s-1117b"
KANA = ("こんにちは", "おはよう")
STORED = re.compile(r"저장|기록|transcript|stored|session", re.IGNORECASE)
ESCAPE_TEXT = re.compile(r"이스케이프|escape|\\u3053", re.IGNORECASE)


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "session_display_shared.py"
    module = types.ModuleType("session_display_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def asked(ctx):
    return shared(ctx).question_shared(ctx).asked(ctx)


def is_dialog(call) -> bool:
    return call.get("name") in ("AskUserQuestion", "request_user_input")


def read_stored_input_first(ctx):
    return shared(ctx).read_before(ctx, SESSION, is_dialog)


def says_stored_input_has_escape_text(ctx):
    """A text the agent wrote before it opened the dialog says that the stored input holds escape text."""
    texts = list(ctx.view.get("assistant_texts", []))
    said = [text for text in texts if STORED.search(text) and ESCAPE_TEXT.search(text)]
    return bool(said), f"{len(said)} text(s) say it" if said else "no text says that the stored input holds escape text", {}


def next_question_in_raw_characters(ctx):
    helper = shared(ctx)
    questions = helper.question_shared(ctx)
    found = questions.dialog(ctx)
    if found is None:
        return False, "no question dialog was opened", {}
    text = questions.all_text(found)
    escaped = helper.ESCAPE.findall(text)
    missing = questions.missing_words(text, KANA)
    return not escaped and not missing, f"escape text: {escaped}; missing kana: {missing}", {
        "escaped": escaped, "missing": missing}


def no_free_form_label(ctx):
    return shared(ctx).question_shared(ctx).no_free_form_label(ctx)
