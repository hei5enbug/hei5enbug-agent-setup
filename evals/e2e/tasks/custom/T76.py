"""Custom checks for T76: the dialog that asks whether to delete two repeating checklist lines."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "question_shared.py"
    module = types.ModuleType("question_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


FLAGGED = (2, 5)
KEYS = {
    1: r"weekly\.csv|day,count|하루 한 행|일별 한 행|날짜별 한 행",
    2: r"첫 줄|first line|맨 첫|첫째 줄",
    3: r"같은 파일|동일한 파일|똑같은 파일|same file",
    4: r"빈 칸|빈 셀|비어 있|empty cell|(?<![\w.])0(?![\w.])",
    5: r"사본|second copy",
}
FORBIDDEN = (r"acceptance criteria|criterion|regression|reviewer|인수 조건|인수 기준|수락 기준|회귀|검토 의견|리뷰 의견|검토자|"
             r"리뷰어")
DELETE = re.compile(r"삭제|지우|지움|제거|delete|remove", re.IGNORECASE)
KEEP = re.compile(r"유지|남기|남겨|그대로|보존|keep|leave", re.IGNORECASE)
NEGATED = re.compile(r"(?:삭제|지우|지움|제거|유지|남기|보존)\w*\s*(?:하지|안|않|말)|(?:don't|do not|not)\s+\w+", re.IGNORECASE)
LABEL = re.compile(r"(?<![A-Za-z0-9])([A-Z])\s*[:：)]")


def has(key: int, text: str) -> bool:
    return re.search(KEYS[key], text, re.IGNORECASE) is not None


def opened(ctx):
    shown = shared(ctx).dialog(ctx.view)
    return shown is not None, "a dialog was opened" if shown is not None else "no question dialog was opened", {}


def names_both_flagged_lines(ctx):
    text = shared(ctx).text_of(shared(ctx).dialog(ctx.view))
    missing = [line for line in FLAGGED if not has(line, text)]
    return not missing, f"key words missing for lines {missing}" if missing else "both flagged lines named", {
        "missing": missing}


def uses_no_internal_terms(ctx):
    text = shared(ctx).text_of(shared(ctx).dialog(ctx.view))
    found = sorted({match.group(0).lower() for match in re.finditer(FORBIDDEN, text, re.IGNORECASE)})
    return not found, f"found {found}" if found else "none found", {"found": found}


def label_lines(text: str) -> dict[str, int]:
    """The flagged line each label of the question stands for, read from the text that follows the label."""
    marks = list(LABEL.finditer(text))
    bound: dict[str, int] = {}
    for mark, following in zip(marks, [*marks[1:], None]):
        segment = text[mark.end():following.start() if following else len(text)]
        line = next((line for line in FLAGGED if has(line, segment)), None)
        if line is not None:
            bound.setdefault(mark.group(1), line)
    return bound


def kind_of(label: str) -> str | None:
    cleaned = NEGATED.sub(" ", label)
    delete, keep = DELETE.search(cleaned), KEEP.search(cleaned)
    if delete and (not keep or delete.start() < keep.start()):
        return "delete"
    return "keep" if keep else None


def options_name_both_lines(ctx):
    tool_input = shared(ctx).dialog(ctx.view)
    pool = shared(ctx).questions(tool_input)
    labels: dict[str, int] = {}
    for blob in [str(q.get("question", "")) for q in pool] + [str(o.get("preview", "")) for o in
                                                                   shared(ctx).options(tool_input)]:
        labels = {**label_lines(blob), **labels}
    chosen: dict[str, list[dict]] = {"delete": [], "keep": []}
    for option in shared(ctx).options(tool_input):
        kind = kind_of(str(option.get("label", "")))
        if kind:
            chosen[kind].append(option)

    def names(description: str, line: int) -> bool:
        return has(line, description) or any(
            re.search(rf"(?<![A-Za-z0-9]){label}(?![A-Za-z0-9])", description) for label, bound in labels.items()
            if bound == line)

    complete = {kind: any(all(names(str(o.get("description", "")), line) for line in FLAGGED) for o in found)
                for kind, found in chosen.items()}
    return all(complete.values()), f"options that name both flagged lines: {complete}", {
        "labels": labels, "complete": complete}


def diagram_shows_all_lines(ctx):
    """The diagram, a preview on Claude Code and the question text below its first line on Codex, holds all five lines."""
    places = shared(ctx).diagram_texts(ctx.view)
    full = [place for place in places if all(has(line, place) for line in KEYS)]
    return bool(full), f"{len(full)} of {len(places)} places hold all five lines", {"places": len(places)}


def no_free_form_option(ctx):
    return shared(ctx).no_free_form_option(ctx.view)
