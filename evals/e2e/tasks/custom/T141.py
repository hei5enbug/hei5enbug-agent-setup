"""Custom checks for T141: a session summary where the stored question input itself holds escape text, then a new question."""

from __future__ import annotations

import re
import types
from pathlib import Path

GREETING = "こんにちは"


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "stored_input_shared.py"
    module = types.ModuleType("stored_input_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def questions(ctx):
    """The dialog the run finally showed, else the final answer's paragraph with a question mark (Codex asks in the reply)."""
    helper = types.ModuleType("question_shared")
    path = Path(ctx.tasks_root) / "custom" / "question_shared.py"
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), helper.__dict__)
    shown = helper.dialog(ctx.view)
    if shown is not None:
        return helper.text_of(shown)
    paragraphs = re.split(r"\n\s*\n", str(ctx.view.get("final_answer", "")))
    return "\n".join(p for p in paragraphs if re.search(r"[?？]", p))


def read_stored_input(ctx):
    found = shared(ctx).read_transcript(ctx.view)
    return found, "the transcript was read" if found else "the transcript was never read", {}


def states_escape_text_stored(ctx):
    pattern = r"(?i)(저장|stored|기록|transcript)[^\n]{0,60}(이스케이프|escape|\\u3053)|(이스케이프|escape|\\u3053)[^\n]{0,60}(저장|stored|기록|transcript)"
    hits = [line for line in shared(ctx).said(ctx.view) if re.search(pattern, line)]
    return bool(hits), f"{len(hits)} line(s) say the stored input holds escape text", {"lines": hits[:2]}


def next_question_raw(ctx):
    text = questions(ctx)
    ok = GREETING in text and not shared(ctx).ESCAPE_SEQUENCE.search(text)
    return ok, "the next question holds raw characters" if ok else "no next question with the raw kana and no escape text", {}
