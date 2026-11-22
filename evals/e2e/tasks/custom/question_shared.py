"""Shared helpers for the question dialog tasks: the dialog a run opened, its text, and its free-form options."""

from __future__ import annotations

import re

TOOLS = ("AskUserQuestion", "request_user_input")
GUARD_DENIAL = "free-form row"
TRAILING_NOTE = re.compile(r"\s*[(（][^()（）]*[)）]\s*$")
FREE_FORM_LABELS = frozenset({
    "other", "custom", "type your own", "type your own answer", "write your own", "enter your own",
    "직접 입력", "직접 작성", "기타", "자유 입력",
})


def normalized(label: str) -> str:
    text = label.strip()
    while TRAILING_NOTE.sub("", text) != text:
        text = TRAILING_NOTE.sub("", text)
    return " ".join(text.strip().rstrip(".,:;!…").split()).casefold()


def shown_call(view):
    """The last question tool call of either host that the question guard did not deny, or None."""
    shown = [call for call in view.get("tool_calls", [])
             if call.get("name") in TOOLS and GUARD_DENIAL not in str(call.get("result_text", ""))]
    return shown[-1] if shown else None


def dialog(view):
    """The input of the dialog the run finally showed, or None."""
    call = shown_call(view)
    return call.get("input") if call else None


def questions(tool_input) -> list[dict]:
    found = tool_input.get("questions") if isinstance(tool_input, dict) else None
    return [question for question in found if isinstance(question, dict)] if isinstance(found, list) else []


def options(tool_input) -> list[dict]:
    return [option for question in questions(tool_input) for option in (question.get("options") or [])
            if isinstance(option, dict)]


def text_of(tool_input) -> str:
    """Every question, header, label, description, and preview of the dialog, one per line."""
    parts: list[str] = []
    for question in questions(tool_input):
        parts += [str(question.get("question", "")), str(question.get("header", ""))]
    for option in options(tool_input):
        parts += [str(option.get(key, "")) for key in ("label", "description", "preview")]
    return "\n".join(parts)


def free_form_labels(tool_input) -> list[str]:
    return [str(option["label"]) for option in options(tool_input)
            if isinstance(option.get("label"), str) and normalized(option["label"]) in FREE_FORM_LABELS]


def diagram_texts(view) -> list[str]:
    """Where the dialog's diagram can sit on its host: each option's preview for `AskUserQuestion`, which has that
    field, and the question text below its first line for `request_user_input`, which has none."""
    call, tool_input = shown_call(view), dialog(view)
    if call is None:
        return []
    if call.get("name") == "AskUserQuestion":
        return [str(option.get("preview", "")) for option in options(tool_input)]
    return ["\n".join(str(question.get("question", "")).splitlines()[1:]) for question in questions(tool_input)]


def no_free_form_option(view):
    shown = dialog(view)
    if shown is None:
        return False, "no question dialog was opened", {}
    found = free_form_labels(shown)
    return not found, f"free-form option labels: {found}" if found else "no free-form option", {"labels": found}
