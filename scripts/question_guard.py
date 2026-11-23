#!/usr/bin/env python3
"""PreToolUse hook: deny a question dialog that holds an option asking the user to type an answer.

Claude Code `AskUserQuestion` and Codex `request_user_input` both add their own free-form row to every question, so
an option such as "Other" or "직접 입력" only shows a button with no text box. The hook denies the call when any
option's label equals, without case, a label from FREE_FORM_LABELS after trailing parenthesized notes such as
"(Recommended)" and trailing punctuation are removed. A label that only contains such a word, such as "Other
files", passes. Every other event, tool, or input shape prints nothing.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = sys.pycache_prefix is None
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hook_runtime  # noqa: E402

TOOLS = frozenset({"AskUserQuestion", "request_user_input"})
FREE_FORM_LABELS = frozenset({
    "other", "custom", "type your own", "type your own answer", "write your own", "enter your own",
    "직접 입력", "직접 작성", "기타", "자유 입력",
})
TRAILING_NOTE = re.compile(r"\s*[(（][^()（）]*[)）]\s*$")
TRAILING_PUNCTUATION = ".,:;!…"
REASON = (
    "Blocked: the option '{label}' asks the user to type an answer, but the host already adds its own free-form row "
    "to every question, so this option shows no text box. Remove that option and ask again with only the real "
    "choices; the user types a free answer in the host's own row."
)


def normalized(label: str) -> str:
    text = label.strip()
    while True:
        stripped = TRAILING_NOTE.sub("", text)
        if stripped == text:
            break
        text = stripped
    return " ".join(text.strip().rstrip(TRAILING_PUNCTUATION).split()).casefold()


def free_form_label(tool_input) -> str | None:
    """The first option label of the input that asks the user to type, else None."""
    questions = tool_input.get("questions") if isinstance(tool_input, dict) else None
    for question in questions if isinstance(questions, list) else []:
        options = question.get("options") if isinstance(question, dict) else None
        for item in options if isinstance(options, list) else []:
            label = item.get("label") if isinstance(item, dict) else None
            if isinstance(label, str) and normalized(label) in FREE_FORM_LABELS:
                return label
    return None


def handle(event):
    if not isinstance(event, dict) or event.get("hook_event_name") != "PreToolUse":
        return None
    if event.get("tool_name") not in TOOLS:
        return None
    label = free_form_label(event.get("tool_input"))
    if label is None:
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": REASON.format(label=label.strip()),
    }}


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    output = handle(event)
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(hook_runtime.run("question_guard.py", main))
