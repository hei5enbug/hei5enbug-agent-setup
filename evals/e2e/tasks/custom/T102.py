"""Custom checks for T102: the next question after a stored question input whose labels are themselves escape text.

The prompt names the session and shows only the first label, with escapes. The other options and all descriptions are in
the stored record alone, so a session that writes the question must read the record first.
"""

from __future__ import annotations

import re
import types
from pathlib import Path

SESSION = "s-1117b"
LABELS = ("こんにちは", "おはよう", "こんばんは")
DESCRIPTIONS = ("낮에 쓰는 인사", "아침에 쓰는 인사", "저녁에 쓰는 인사")
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
    """The agent says, in a text it wrote before the dialog or in a question of the dialog, that the stored input holds
    escape text. The run ends at the first dialog, so every text of the run came before it."""
    questions = shared(ctx).question_shared(ctx)
    found = questions.dialog(ctx)
    texts = [*ctx.view.get("assistant_texts", []), *([q["question"] for q in found["questions"]] if found else [])]
    said = [text for text in texts if STORED.search(text) and ESCAPE_TEXT.search(text)]
    return bool(said), f"{len(said)} text(s) say it" if said else "nothing says that the stored input holds escape text", {}


def option_texts(found, key):
    return [option[key] for question in found["questions"] for option in question["options"]]


def next_question_in_raw_characters(ctx):
    """The labels are the three kana words and no label, description, header, or preview holds escape text."""
    helper = shared(ctx)
    questions = helper.question_shared(ctx)
    found = questions.dialog(ctx)
    if found is None:
        return False, "no question dialog was opened", {}
    labels = option_texts(found, "label")
    fields = [*labels, *option_texts(found, "description"), *option_texts(found, "preview"), *[q["header"] for q in found["questions"]]]
    escaped = [text for text in fields if helper.ESCAPE.search(text)]
    missing = [word for word in LABELS if word not in labels]
    return not escaped and not missing, f"escape text in: {escaped}; labels missing: {missing}", {"escaped": escaped, "missing": missing}


def descriptions_from_record(ctx):
    """The three descriptions of the record are in the dialog, which only a read of the record can give."""
    questions = shared(ctx).question_shared(ctx)
    found = questions.dialog(ctx)
    if found is None:
        return False, "no question dialog was opened", {}
    missing = questions.missing_words("\n".join(option_texts(found, "description")), DESCRIPTIONS)
    return not missing, f"missing: {missing}" if missing else "all present", {"missing": missing}


def no_free_form_label(ctx):
    return shared(ctx).question_shared(ctx).no_free_form_label(ctx)
