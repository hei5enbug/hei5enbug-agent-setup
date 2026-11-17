"""A scripted user for evaluation runs: a script with no model that answers the agent's questions from an answer sheet.

The sheet lists each decision with an identifier, the terms that identify a question about it, and its answers in order,
and lists each point an approved specification must hold with the terms that show it and the terms of its rejected
options. A question is about a decision when it holds at least one of the decision's terms, compared without case. It
gets the next unused answer of every decision it matches, and the default answer when it matches none. An answer is
used once: a follow-up that matches a decision again gets that decision's next unused answer, and once every matching
decision has used all its answers, the sheet's repeat answer, which says that the earlier answer stands. A request for
approval is approved when the specification text holds every term of every required point and no term of a rejected
option outside the heading of rejected alternatives; otherwise it gets the sentence of the first point that fails. Every exchange is appended to a log, and the log is the
only state, so the approver process and the harness process, which answer different kinds of question, share one count.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

DEFAULT_ANSWER = "Use your recommendation."
REPEAT_ANSWER = "My earlier answer on that stands. Use your recommendation for the rest."
APPROVED_ANSWER = "Approved."
APPROVAL_TERMS = ("approve", "approval", "승인")
REJECTED_HEADINGS = ("rejected alternatives", "기각한 대안")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
KIND_TOOL = "tool"
KIND_TEXT = "text"


class SheetError(ValueError):
    pass


@dataclass(frozen=True)
class Exchange:
    """One question and what the scripted user answered; `approval` is None for a question about a decision."""

    index: int
    kind: str
    question: str
    matched: tuple[str, ...]
    answer: str | None
    approval: bool | None = None
    ended: bool = False
    tool_use_id: str | None = None
    detail: str = ""
    stream_offset: int = 0
    used: tuple[str, ...] = ()


def lowered(texts: Sequence[str]) -> list[str]:
    return [text.lower() for text in texts]


def strings_of(value: Any, name: str) -> list[str]:
    if not (isinstance(value, list) and value and all(isinstance(item, str) and item.strip() for item in value)):
        raise SheetError(f"{name} is not a non-empty list of text")
    return list(value)


def validate_sheet(sheet: Any) -> dict[str, Any]:
    """The sheet with its defaults filled in; a malformed sheet raises SheetError naming the problem."""
    if not isinstance(sheet, Mapping):
        raise SheetError("the sheet is not an object")
    decisions, points, seen = [], [], set()
    for position, item in enumerate(sheet.get("decisions") or []):
        name = f"decisions[{position}]"
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), str) or not item["id"]:
            raise SheetError(f"{name} has no id")
        if item["id"] in seen:
            raise SheetError(f"{name} repeats the id {item['id']}")
        seen.add(item["id"])
        decisions.append({"id": item["id"], "terms": strings_of(item.get("terms"), f"{name}.terms"),
                          "answers": strings_of(item.get("answers"), f"{name}.answers")})
    for position, item in enumerate(sheet.get("points") or []):
        name = f"points[{position}]"
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), str) or not item["id"]:
            raise SheetError(f"{name} has no id")
        rejected = item.get("rejected_terms", [])
        if not isinstance(rejected, list) or not all(isinstance(term, str) and term.strip() for term in rejected):
            raise SheetError(f"{name}.rejected_terms is not a list of text")
        sentence = item.get("sentence")
        if not (isinstance(sentence, str) and sentence.strip()):
            raise SheetError(f"{name} has no sentence")
        points.append({"id": item["id"], "terms": strings_of(item.get("terms"), f"{name}.terms"),
                       "rejected_terms": list(rejected), "sentence": sentence})
    if not decisions and not points:
        raise SheetError("the sheet lists no decision and no point")
    return {
        "decisions": decisions, "points": points,
        "approval_terms": strings_of(sheet.get("approval_terms", list(APPROVAL_TERMS)), "approval_terms"),
        "rejected_headings": strings_of(sheet.get("rejected_headings", list(REJECTED_HEADINGS)), "rejected_headings"),
        "default_answer": str(sheet.get("default_answer") or DEFAULT_ANSWER),
        "repeat_answer": str(sheet.get("repeat_answer") or REPEAT_ANSWER),
        "approved_answer": str(sheet.get("approved_answer") or APPROVED_ANSWER),
        "stop_after_approval": bool(sheet.get("stop_after_approval", False)),
        "max_answers": int(sheet.get("max_answers", 30)),
    }


def load_sheet(path: Path) -> dict[str, Any]:
    try:
        return validate_sheet(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        raise SheetError(f"cannot read the answer sheet: {error}") from error


def without_rejected_section(text: str, headings: Sequence[str]) -> str:
    """The specification text without the sections whose heading names the rejected alternatives; a section lasts until
    the next heading of the same or a higher level."""
    keep: list[str] = []
    skipping: int | None = None
    for line in text.splitlines():
        match = HEADING.match(line)
        if match:
            level = len(match.group(1))
            if skipping is not None and level <= skipping:
                skipping = None
            if skipping is None and any(name in match.group(2).lower() for name in lowered(headings)):
                skipping = level
        if skipping is None:
            keep.append(line)
    return "\n".join(keep)


def first_failing_point(sheet: Mapping[str, Any], specification: str) -> Mapping[str, Any] | None:
    """The first point whose required terms are not all held, or whose rejected terms appear outside the heading of the
    rejected alternatives; None when the specification holds every point."""
    whole = specification.lower()
    outside = without_rejected_section(specification, sheet["rejected_headings"]).lower()
    for point in sheet["points"]:
        missing = any(term.lower() not in whole for term in point["terms"])
        kept = any(term.lower() in outside for term in point["rejected_terms"])
        if missing or kept:
            return point
    return None


def is_approval_request(sheet: Mapping[str, Any], question: str) -> bool:
    return any(term in question.lower() for term in lowered(sheet["approval_terms"]))


def read_log(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not Path(path).is_file():
        return []
    found = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            found.append(item)
    return found


class ScriptedUser:
    """Answers questions from a sheet and appends each exchange to `log_path`; the log is the whole state."""

    def __init__(self, sheet: Mapping[str, Any], log_path: Path | None = None):
        self.sheet = validate_sheet(sheet)
        self.log_path = Path(log_path) if log_path else None

    def answer(
        self, question: str, kind: str = KIND_TEXT, specification: str | None = None, tool_use_id: str | None = None,
        stream_offset: int = 0,
    ) -> Exchange:
        """Answer one question. `specification` is the text a request for approval is judged on; it defaults to the question.
        `stream_offset` is the number of stream events seen so far; the next specification is read from there."""
        if self.log_path is None:
            return replace(self.decide(question, kind, specification, tool_use_id, []), stream_offset=stream_offset)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.seek(0)
            earlier = []
            for line in stream.read().splitlines():
                try:
                    earlier.append(json.loads(line))
                except ValueError:
                    continue
            exchange = replace(self.decide(question, kind, specification, tool_use_id, earlier), stream_offset=stream_offset)
            stream.write(json.dumps(asdict(exchange), ensure_ascii=False) + "\n")
            return exchange

    def decide(
        self, question: str, kind: str, specification: str | None, tool_use_id: str | None, earlier: Sequence[Mapping[str, Any]],
    ) -> Exchange:
        index = len(earlier) + 1
        approved_before = any(item.get("approval") is True for item in earlier)
        make = lambda **fields: Exchange(index=index, kind=kind, question=question, tool_use_id=tool_use_id, **fields)  # noqa: E731
        if is_approval_request(self.sheet, question):
            failing = first_failing_point(self.sheet, specification if specification is not None else question)
            if failing is None:
                return make(matched=(), answer=self.sheet["approved_answer"], approval=True)
            return make(matched=(), answer=failing["sentence"], approval=False, detail=failing["id"])
        if approved_before and self.sheet["stop_after_approval"]:
            return make(matched=(), answer=None, ended=True)
        if len([item for item in earlier if item.get("answer") is not None]) >= self.sheet["max_answers"]:
            return make(matched=(), answer=None, ended=True, detail="answer limit")
        lowered_question = question.lower()
        matched = [item for item in self.sheet["decisions"] if any(term in lowered_question for term in lowered(item["terms"]))]
        if not matched:
            return make(matched=(), answer=self.sheet["default_answer"])
        answers, used = [], []
        for item in matched:
            given = sum(1 for earlier_item in earlier if item["id"] in earlier_item.get("used", ()))
            if given < len(item["answers"]):
                answers.append(item["answers"][given])
                used.append(item["id"])
        return make(matched=tuple(item["id"] for item in matched), answer="\n".join(answers) or self.sheet["repeat_answer"],
                    used=tuple(used))


def sheet_leaks(folder: Path, sheet_path: Path) -> list[str]:
    """Paths below `folder` that hold a copy of the sheet: a file with the sheet's name or the sheet's exact content."""
    sheet = Path(sheet_path)
    digest = hashlib.sha256(sheet.read_bytes()).hexdigest()
    found = []
    for path in sorted(Path(folder).rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            same = path.name == sheet.name or hashlib.sha256(path.read_bytes()).hexdigest() == digest
        except OSError:
            continue
        if same:
            found.append(str(path.relative_to(folder)))
    return found
