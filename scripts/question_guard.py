"""PreToolUse hook: deny a question dialog that carries its own free-form option.

Claude Code `AskUserQuestion` and Codex `request_user_input` add their own free-form row to every question, and the
Claude Code row has the text box, so an option whose label asks the user to type has none. The hook denies a call when
any option's label, after a trailing parenthesized note such as "(Recommended)" is removed, equals one of FORBIDDEN
without regard to case. A label that only contains such a word, such as "Other files", passes. The input is parsed
only when its raw text contains `label`.
"""

from __future__ import annotations

import json
import re
import sys

TOOLS = frozenset({"AskUserQuestion", "request_user_input"})
FORBIDDEN = frozenset({
    "other", "custom", "type your own", "type your own answer", "write your own", "enter your own",
    "직접 입력", "직접 입력하기", "직접 작성", "직접 작성하기", "기타",
})
TRAILING_NOTE = re.compile(r"\s*[(（][^()（）]*[)）]\s*$")
REASON = (
    "Blocked: the option labelled {labels} offers a free-form answer, but the host already adds its own free-form "
    "row to every question. Remove that option and send the question again with only the real choices."
)


def bare(label: object) -> str:
    return TRAILING_NOTE.sub("", label.strip()).casefold() if isinstance(label, str) else ""


def free_form_labels(tool_input: object) -> list[str]:
    questions = tool_input.get("questions") if isinstance(tool_input, dict) else None
    found: list[str] = []
    for question in questions if isinstance(questions, list) else []:
        options = question.get("options") if isinstance(question, dict) else None
        for option in options if isinstance(options, list) else []:
            label = option.get("label") if isinstance(option, dict) else None
            if bare(label) in FORBIDDEN:
                found.append(label.strip())
    return found


def main() -> int:
    raw = sys.stdin.read()
    if "label" not in raw:
        return 0
    try:
        event = json.loads(raw)
    except ValueError:
        return 0
    if not isinstance(event, dict) or event.get("tool_name") not in TOOLS:
        return 0
    labels = free_form_labels(event.get("tool_input"))
    if labels:
        reason = REASON.format(labels=", ".join(f'"{label}"' for label in labels))
        output = {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    import hook_runtime

    sys.exit(hook_runtime.run("question_guard.py", main))
