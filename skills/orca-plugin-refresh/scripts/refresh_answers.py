from __future__ import annotations

from typing import Callable, Sequence

from refresh_core import RefreshError
from refresh_interrupt import interrupt_apply
from refresh_orca import Orca
from refresh_process import ProcessOs
from refresh_questions import CHOICES, CODEX_INSTALL
from refresh_sessions import plan_sessions


def parse_answers(answers: Sequence[str]) -> list[tuple[str, str]]:
    parsed = []
    for item in answers:
        question_id, _, choice = item.partition("=")
        if not question_id or choice not in CHOICES:
            raise RefreshError("answer_invalid", "Give each answer as <question id>=<wait|interrupt|skip>.")
        parsed.append((question_id, choice))
    return parsed


def decided_entry(orca: Orca, state: dict, question: dict, choice: str, system: ProcessOs | None, sleep: Callable[[float], None]) -> dict:
    """Carry out one answer on the session its question named; the entry holds the result."""
    handle = question["handle"]
    result = {"handle": handle, "host": question["host"], "title": question.get("title"), "worktree": question.get("worktree"),
              "initiator": False, "actions": [], "status": "skipped", "detail": "skipped_by_user"}
    if choice == "skip":
        return result
    planned = plan_sessions(orca, state, state.get("compact_mode", "auto"), [handle])
    if not planned:
        return {**result, "detail": "terminal_gone"}
    entry = planned[0]
    if entry["status"] != "pending":
        return entry
    if choice == "wait":
        entry.update(status="deferred", detail="waiting_for_idle", keep_unrestorable_input=question["reason"] == "input_not_restorable")
    else:
        interrupt_apply(orca, entry, state, system, sleep)
    return entry


def checked_codex_answers(known: dict, parsed: list[tuple[str, str]]) -> None:
    """Each Codex answer must be one the question offers, and every unanswered Codex question needs its answer in the same call."""
    for question_id, choice in parsed:
        if choice not in [option["choice"] for option in known[question_id].get("options", [])]:
            raise RefreshError("answer_invalid", f"Question {question_id} does not offer {choice}.")
    open_ids = {key for key, item in known.items() if item.get("reason") == CODEX_INSTALL and not item.get("answer")}
    if open_ids - {question_id for question_id, _ in parsed}:
        raise RefreshError("answers_incomplete", "Answer every Codex install question in the same decide call.")
