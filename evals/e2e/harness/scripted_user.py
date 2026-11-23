"""A scripted user for the evaluation harness: no model, only an answer sheet the agent cannot read.

It answers a question asked through the question tool (`AskUserQuestion`), in that tool's free-form answer, and a plain-text
question that ends a turn. A task names its answer sheet in `user.sheet`; the sheet lives under `tasks/answers/`, which is not
part of the agent's folder or of the exported plugin.

A term may give alternatives separated by `|`, such as `sunday|일요일`; it is found when any alternative is. A decision's
term is found only as a whole word, so `week` matches `week` and `weeks` but not `weekly`; a Hangul term still matches inside
a longer word, because a particle follows it.

The sheet lists each decision (`id`, `terms`, `answer`) and each point an approved specification must hold (`id`, `terms`,
`rejected_terms`, `sentence`). A question is about a decision when it contains at least one of that decision's terms, compared
without case; it gets the answer of every decision it matches, and the fallback reply when it matches none. A request for
approval, a question that contains one of the sheet's approval terms, is approved when the specification text contains every
term of every required point and no rejected term outside the heading of rejected alternatives; otherwise it gets the sentence
of the first point that fails. Every exchange is logged with the identifiers it matched.

This module uses only the standard library and no package-relative import, so the approver server can run it as a script."""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

LOG_NAME = "user-log.jsonl"
KIND_TOOL = "tool"
KIND_TEXT = "text"
QUESTION_TOOL = "AskUserQuestion"
DEFAULT_APPROVAL_TERMS = ("approve", "approval", "승인")
DEFAULT_FALLBACK = "use your recommendation"
DEFAULT_APPROVED = "Approved. Go ahead with exactly this specification."
DEFAULT_HEADINGS = ("rejected alternatives", "기각한 대안")
DEFAULT_MAX_EXCHANGES = 25
NOT_AVAILABLE = "The user has nothing more to say right now and will answer in the next message."
QUESTION_ENDINGS = ("?", "？")
TRAILING_MARKUP = "*_`\"')]> \t"
HEADING_LINE = re.compile(r"^\s{0,3}#{1,6}\s")
LABEL_LINE = re.compile(r"^\s*(?:\*\*[^*\n]{1,80}\*\*|__[^_\n]{1,80}__|[^\s:][^:\n]{0,60}:)\s*$")
NOISE_PARTS = ("__pycache__", ".pytest_cache")
FENCE = "```"
WORD_CHARS = "A-Za-z0-9_"


class SheetError(ValueError):
    pass


@dataclass(frozen=True)
class Decision:
    id: str
    terms: tuple[str, ...]
    answer: str


@dataclass(frozen=True)
class Point:
    id: str
    terms: tuple[str, ...]
    rejected_terms: tuple[str, ...]
    sentence: str


@dataclass(frozen=True)
class Sheet:
    decisions: tuple[Decision, ...]
    points: tuple[Point, ...]
    approval_terms: tuple[str, ...] = DEFAULT_APPROVAL_TERMS
    fallback: str = DEFAULT_FALLBACK
    approved_reply: str = DEFAULT_APPROVED
    rejected_headings: tuple[str, ...] = DEFAULT_HEADINGS
    answer_after_approval: bool = True
    max_exchanges: int = DEFAULT_MAX_EXCHANGES


@dataclass(frozen=True)
class Exchange:
    """One question and the scripted user's reply. `reply` is None when the user gives none."""

    kind: str
    question: str
    matched: tuple[str, ...]
    reply: str | None
    approval: bool = False
    approved: bool | None = None
    failed_point: str | None = None


def strings(value: Any, where: str, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value) or (nonempty and not value):
        raise SheetError(f"{where} must be a list of non-empty strings" + (" with at least one" if nonempty else ""))
    return tuple(value)


def text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SheetError(f"{where} must be a non-empty string")
    return value


def parse_sheet(data: Any) -> Sheet:
    if not isinstance(data, Mapping):
        raise SheetError("the answer sheet is not an object")
    decisions, points = [], []
    for index, item in enumerate(data.get("decisions", [])):
        where = f"decisions[{index}]"
        decisions.append(Decision(text(item.get("id"), f"{where}.id"), strings(item.get("terms"), f"{where}.terms", True),
                                  text(item.get("answer"), f"{where}.answer")))
    for index, item in enumerate(data.get("required", [])):
        where = f"required[{index}]"
        points.append(Point(text(item.get("id"), f"{where}.id"), strings(item.get("terms"), f"{where}.terms", True),
                            strings(item.get("rejected_terms", []), f"{where}.rejected_terms"),
                            text(item.get("sentence"), f"{where}.sentence")))
    for kind, items in (("decision", decisions), ("required point", points)):
        names = [item.id for item in items]
        if len(set(names)) != len(names):
            raise SheetError(f"a {kind} id is used twice")
    return Sheet(
        tuple(decisions), tuple(points),
        strings(data.get("approval_terms", list(DEFAULT_APPROVAL_TERMS)), "approval_terms"),
        text(data.get("fallback_reply", DEFAULT_FALLBACK), "fallback_reply"),
        text(data.get("approved_reply", DEFAULT_APPROVED), "approved_reply"),
        strings(data.get("rejected_headings", list(DEFAULT_HEADINGS)), "rejected_headings"),
        bool(data.get("answer_after_approval", True)),
        int(data.get("max_exchanges", DEFAULT_MAX_EXCHANGES)),
    )


def load_sheet(path: str | Path) -> Sheet:
    try:
        return parse_sheet(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, AttributeError) as error:
        raise SheetError(f"cannot read the answer sheet: {error}") from error


def has_term(haystack: str, term: str) -> bool:
    """True when the text holds the term or, for `a|b`, any alternative, compared without case."""
    lowered = haystack.lower()
    return any(alternative.strip().lower() in lowered for alternative in term.split("|") if alternative.strip())


def contains_any(haystack: str, terms: Sequence[str]) -> bool:
    return any(has_term(haystack, term) for term in terms)


def has_word(haystack: str, term: str) -> bool:
    """Like `has_term`, but an alternative that starts or ends with a letter or digit must not touch another one there;
    a plural `s` or `es` may follow."""
    for alternative in (part.strip() for part in term.split("|")):
        if not alternative:
            continue
        before = rf"(?<![{WORD_CHARS}])" if re.match(rf"[{WORD_CHARS}]", alternative) else ""
        after = rf"(?:e?s)?(?![{WORD_CHARS}])" if re.search(rf"[{WORD_CHARS}]$", alternative) else ""
        if re.search(before + re.escape(alternative) + after, haystack, re.IGNORECASE):
            return True
    return False


def matched_decisions(sheet: Sheet, question: str) -> list[Decision]:
    return [decision for decision in sheet.decisions if any(has_word(question, term) for term in decision.terms)]


def is_approval_request(sheet: Sheet, question: str) -> bool:
    return contains_any(question, sheet.approval_terms)


def split_rejected_section(sheet: Sheet, specification: str) -> tuple[str, str]:
    """The specification text outside the heading of rejected alternatives, and the text under that heading.

    The section starts at a line whose words, without markup, begin with one of the sheet's headings, and ends at the next
    markdown heading or label line."""
    outside, inside, in_section = [], [], False
    for line in specification.splitlines():
        words = line.strip().lstrip("#*_ ").rstrip(":*_ ").lower()
        starts = any(words.startswith(heading.lower()) for heading in sheet.rejected_headings) and (
            HEADING_LINE.match(line) is not None or LABEL_LINE.match(line) is not None or len(words) <= 60)
        if starts:
            in_section = True
            inside.append(line)
            continue
        if in_section and (HEADING_LINE.match(line) or LABEL_LINE.match(line)):
            in_section = False
        (inside if in_section else outside).append(line)
    return "\n".join(outside), "\n".join(inside)


def review_specification(sheet: Sheet, specification: str) -> tuple[bool, str | None, str | None]:
    """Whether the specification may be approved, the id of the first point it fails, and that point's sentence."""
    outside, _ = split_rejected_section(sheet, specification)
    for point in sheet.points:
        missing = not all(has_term(specification, term) for term in point.terms)
        rejected = contains_any(outside, point.rejected_terms) if point.rejected_terms else False
        if missing or rejected:
            return False, point.id, point.sentence
    return True, None, None


def respond(sheet: Sheet, question: str, kind: str, specification: str | None = None, approved_before: bool = False) -> Exchange:
    """The scripted user's reply to one question. `specification` is the text a request for approval is judged on; it
    defaults to the question itself."""
    if is_approval_request(sheet, question):
        if approved_before and not sheet.answer_after_approval:
            return Exchange(kind, question, (), None, True, None, None)
        ok, failed, sentence = review_specification(sheet, specification if specification is not None else question)
        reply = sheet.approved_reply if ok else sentence
        return Exchange(kind, question, tuple(point.id for point in sheet.points), reply, True, ok, failed)
    if approved_before and not sheet.answer_after_approval:
        return Exchange(kind, question, (), None)
    found = matched_decisions(sheet, question)
    reply = "\n".join(decision.answer for decision in found) if found else sheet.fallback
    return Exchange(kind, question, tuple(decision.id for decision in found), reply)


def ends_with_question(final_text: str) -> bool:
    """True when the last line of a turn's final text ends with a question mark, ignoring closing markup."""
    lines = [line for line in final_text.splitlines() if line.strip()]
    return bool(lines) and lines[-1].rstrip(TRAILING_MARKUP).endswith(QUESTION_ENDINGS)


def has_question_line(final_text: str) -> bool:
    """True when any line of a turn's final text outside a code block ends with a question mark, ignoring closing markup."""
    fenced = False
    for line in final_text.splitlines():
        if line.strip().startswith(FENCE):
            fenced = not fenced
        elif not fenced and line.strip() and line.rstrip(TRAILING_MARKUP).endswith(QUESTION_ENDINGS):
            return True
    return False


def tool_question_text(question: Mapping[str, Any]) -> str:
    """The text a tool question is matched on: its question, its header, and its option labels."""
    options = question.get("options") if isinstance(question.get("options"), list) else []
    labels = [str(option.get("label", "")) for option in options if isinstance(option, Mapping)]
    return "\n".join([str(question.get("question", "")), str(question.get("header", "")), *labels])


def repo_state(cwd: str | Path | None) -> dict[str, Any]:
    """The paths a working copy changed and its commit count, so a grader can tell what the agent had edited at a question."""
    if not cwd:
        return {"edited": [], "commits": None}

    def git(*args: str) -> str:
        try:
            done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return done.stdout

    edited = [line[3:] for line in git("status", "--porcelain", "--untracked-files=all").splitlines()
              if len(line) > 3 and not any(part in line[3:] for part in NOISE_PARTS) and not line.endswith(".pyc")]
    count = git("rev-list", "--count", "HEAD").strip()
    return {"edited": sorted(edited), "commits": int(count) if count.isdigit() else None}


def log_exchange(path: str | Path | None, exchange: Exchange, specification: str | None = None, cwd: str | Path | None = None,
                 tool_use_id: str | None = None) -> dict[str, Any]:
    """Append one exchange to the log and return the entry. An approval request also keeps the text it was judged on."""
    entry: dict[str, Any] = {
        "at": time.time(), "kind": exchange.kind, "question": exchange.question, "matched": list(exchange.matched),
        "approval": exchange.approval, "approved": exchange.approved, "answered": exchange.reply is not None,
        "answer": exchange.reply, "failed_point": exchange.failed_point, **repo_state(cwd),
    }
    if tool_use_id:
        entry["tool_use_id"] = tool_use_id
    if exchange.approval and specification is not None:
        entry["specification"] = specification
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def load_log(path: str | Path) -> list[dict[str, Any]]:
    """The logged exchanges in order; a missing file or a malformed line reads as no exchange."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    found = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            found.append(item)
    return found


def approved_before(entries: Sequence[Mapping[str, Any]]) -> bool:
    return any(entry.get("approved") is True for entry in entries)


def answer_tool_input(
    sheet: Sheet, tool_input: Mapping[str, Any], log_path: str | None, specification: str | None, cwd: str | None,
    tool_use_id: str | None = None,
) -> dict[str, Any]:
    """The approver's decision for one `AskUserQuestion` call: every question answered in the free-form field, or a denial
    that asks the agent to wait when the sheet gives no more answers after approval."""
    questions = [item for item in tool_input.get("questions", []) if isinstance(item, Mapping)]
    answers: dict[str, str] = {}
    for question in questions:
        done = approved_before(load_log(log_path)) if log_path else False
        exchange = respond(sheet, tool_question_text(question), KIND_TOOL, specification, done)
        log_exchange(log_path, exchange, specification if exchange.approval else None, cwd, tool_use_id)
        if exchange.reply is None:
            return {"behavior": "deny", "message": NOT_AVAILABLE}
        answers[str(question.get("question", ""))] = exchange.reply
    return {"behavior": "allow", "updatedInput": {"questions": tool_input.get("questions", []), "answers": answers}}


def assistant_text_since_last_question(events: Sequence[Mapping[str, Any]], current_id: str | None) -> str:
    """The main session's assistant text of a Claude stream after the previous question-tool call, up to the current one."""
    pieces: list[str] = []
    for event in events:
        if event.get("type") != "assistant" or event.get("parent_tool_use_id") is not None:
            continue
        content = (event.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, Mapping):
                continue
            if block.get("type") == "tool_use" and block.get("name") == QUESTION_TOOL and block.get("id") != current_id:
                pieces = []
            elif block.get("type") == "text" and str(block.get("text", "")).strip():
                pieces.append(str(block["text"]))
    return "\n\n".join(pieces)


def agent_folder_leaks(folder: str | Path, sheet: Sheet) -> list[str]:
    """The files under `folder` that hold an answer or a point sentence of the sheet; an agent's folder must hold none."""
    needles = [decision.answer for decision in sheet.decisions] + [point.sentence for point in sheet.points]
    leaked = []
    for path in sorted(Path(folder).rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(needle.lower() in body.lower() for needle in needles):
            leaked.append(path.relative_to(folder).as_posix())
    return leaked
