"""Shared by the question tasks T63 and T64: read the dialog a run opened with the host's question tool and check
how it is worded.

Claude Code opens `AskUserQuestion` and Codex opens `request_user_input`; both carry `questions`, each with a
`question` text and `options` with a `label` and a `description`, and Claude Code options may carry a `preview`. The
harness cannot answer a dialog, so the run ends at the first one and the grader reads its input. A run that asked in
its final reply instead has no dialog, so every check of these tasks fails.
"""

from __future__ import annotations

import re
import types
from pathlib import Path
from typing import Any

TOOLS = ("AskUserQuestion", "request_user_input")
PREVIEW_TOOL = "AskUserQuestion"
DRAWN = re.compile(r"[|+│┌┐└┘├┤┬┴┼╭╮╰╯═║]|-{2,}|─")
DELETE_WORDS = ("지우", "지워", "삭제", "제거", "delete", "remove")
KEEP_WORDS = ("유지", "그대로", "남기", "남겨", "keep")
LABEL_MARK = r"[:：)\].=(（]"
LABEL_GAP = rf"(?:(?![A-D]\s*{LABEL_MARK})[^\n]){{0,80}}?"


def repository_root(ctx) -> Path:
    return Path(ctx.tasks_root).resolve().parents[2]


def guard_module(ctx):
    path = repository_root(ctx) / "scripts" / "question_guard.py"
    module = types.ModuleType("question_guard")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def dialog(ctx) -> dict[str, Any] | None:
    """The first question-tool call of the run, with its questions and options as plain strings."""
    for call in ctx.view.get("tool_calls", []):
        if call.get("name") not in TOOLS or not isinstance(call.get("input"), dict):
            continue
        questions = []
        for question in call["input"].get("questions") or []:
            options = [{key: str(option.get(key) or "") for key in ("label", "description", "preview")}
                       for option in question.get("options") or [] if isinstance(option, dict)]
            questions.append({"question": str(question.get("question") or ""), "header": str(question.get("header") or ""),
                              "options": options})
        return {"tool": call["name"], "input": call["input"], "questions": questions}
    return None


def all_text(found: dict[str, Any]) -> str:
    parts = []
    for question in found["questions"]:
        parts += [question["question"], question["header"]]
        for option in question["options"]:
            parts += [option["label"], option["description"], option["preview"]]
    return "\n".join(parts)


def options_of(found: dict[str, Any]) -> list[dict[str, str]]:
    return [option for question in found["questions"] for option in question["options"]]


def asked(ctx):
    found = dialog(ctx)
    return found is not None, f"asked with {found['tool']}" if found else "no question dialog was opened", {}


def missing_words(text: str, words) -> list[str]:
    return [word for word in words if word not in text]


def names_all(ctx, words):
    found = dialog(ctx)
    if found is None:
        return False, "no question dialog was opened", {}
    missing = missing_words(all_text(found), words)
    return not missing, f"missing: {missing}" if missing else "all named", {"missing": missing}


def avoids_words(ctx, words):
    found = dialog(ctx)
    if found is None:
        return False, "no question dialog was opened", {}
    text = all_text(found).casefold()
    used = [word for word in words if word.casefold() in text]
    return not used, f"used: {used}" if used else "none used", {"used": used}


def no_free_form_label(ctx):
    found = dialog(ctx)
    if found is None:
        return False, "no question dialog was opened", {}
    labels = guard_module(ctx).free_form_labels(found["input"])
    return not labels, f"free-form labels: {labels}" if labels else "none", {"labels": labels}


def drawn_lines(text: str, words) -> list[str]:
    return [line for line in text.splitlines() if DRAWN.search(line) and any(word in line for word in words)]


def below_first_line(text: str) -> str:
    return "\n".join(text.split("\n")[1:])


def picture_in_text(ctx, words):
    """A line drawn with `|`, `+`, `-`, or box characters that names one of the words, below the first line of a question."""
    found = dialog(ctx)
    if found is None:
        return False, "no question dialog was opened", {}
    lines = [line for question in found["questions"] for line in drawn_lines(below_first_line(question["question"]), words)]
    previews = [line for option in options_of(found) for line in drawn_lines(option["preview"], words)]
    ok = bool(lines) or (found["tool"] == PREVIEW_TOOL and bool(previews))
    where = "question text" if lines else "preview" if ok else "nowhere"
    return ok, f"picture in {where}", {"lines": (lines or previews)[:3]}


def kind_of(option: dict[str, str]) -> str | None:
    for text in (option["label"].casefold(), option["description"].casefold()):
        if any(word in text for word in KEEP_WORDS):
            return "keep"
        if any(word in text for word in DELETE_WORDS):
            return "delete"
    return None


def labels_of(text: str, key: str) -> list[str]:
    return re.findall(rf"(?<![A-Za-z0-9])([A-D])\s*{LABEL_MARK}" + LABEL_GAP + re.escape(key), text)


def names_line(option: dict[str, str], keys: dict[str, list[str]], key: str) -> bool:
    text = option["description"]
    return key in text or any(re.search(rf"(?<![A-Za-z0-9]){label}(?![A-Za-z0-9])", text) for label in keys[key])


def delete_and_keep_options(ctx, flagged):
    """One option that deletes and one that keeps the flagged lines, each description naming both by key word or label."""
    found = dialog(ctx)
    if found is None:
        return False, "no question dialog was opened", {}
    text = all_text(found)
    keys = {key: labels_of(text, key) for key in flagged}
    done = {"delete": False, "keep": False}
    for option in options_of(found):
        kind = kind_of(option)
        if kind and all(names_line(option, keys, key) for key in flagged):
            done[kind] = True
    return all(done.values()), f"delete option naming both: {done['delete']}; keep option naming both: {done['keep']}", {
        "labels": keys}


def every_option_names(ctx, words):
    """Every option description names every word, so each option says what happens to each column."""
    found = dialog(ctx)
    if found is None:
        return False, "no question dialog was opened", {}
    options = options_of(found)
    bare = [option["label"] for option in options if missing_words(option["description"], words)]
    return len(options) >= 2 and not bare, f"descriptions missing a name: {bare}" if bare else f"{len(options)} options", {
        "options": [option["label"] for option in options]}
