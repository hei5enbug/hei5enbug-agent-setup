from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from refresh_core import now
from refresh_questions import question_record
from refresh_sessions import read_marker, transcript_size


def public(entry: dict) -> dict:
    keys = ("host", "title", "worktree", "status", "detail", "completed", "actions", "planned", "compact_reason", "note", "initiator",
            "ready_signal", "input", "release", "host_release_outdated", "plugin_load", "orphaned", "resume_check",
            "exit_late", "exit_state", "terminal_handle", "resume_line", "probe_position", "queued", "continue_prompt")
    view = {key: entry.get(key) for key in keys if entry.get(key) not in (None, [], False)}
    if entry.get("detail") in {"plugin_load_error", "codex_plugin_folder_replaced"} or entry.get("host_release_outdated"):
        view["resume_approval_needed"] = True
    view["terminal"] = f"…{entry['handle'][-6:]}"
    return view


def alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def handled(state: dict, handle: str) -> str | None:
    """The status a session already reached in this run, ignoring a queue whose helper never ran or died."""
    saved = state.get("sessions", {}).get(handle, {})
    status = saved.get("status")
    if status == "done" or (status == "skipped" and saved.get("detail") == "skipped_by_user"):
        return status
    if status == "awaiting_answer" and any(item.get("handle") == handle and not item.get("answer") for item in state.get("questions", {}).values()):
        return status
    if status == "queued_after_turn":
        own = state.get("self") or {}
        if own.get("handle") == handle and (alive(own.get("helper_pid")) or state.get("self_finished_at")):
            return status
    if status == "deferred":
        helper = state.get("helper") or {}
        if any(item.get("handle") == handle for item in state.get("follow_up", [])) and (alive(helper.get("pid")) or state.get("helper_finished_at")):
            return status
    return None


def handoff_point(handle: str) -> dict:
    """The transcript and its size at the handoff, both None when there is no transcript yet to measure from."""
    path = (read_marker(handle) or {}).get("transcript_path")
    if isinstance(path, str) and Path(path).is_file():
        return {"handoff_transcript": path, "handoff_offset": transcript_size(path)}
    return {"handoff_transcript": None, "handoff_offset": None}


def hand_to_helper(state: dict, run_id: str, items: list[dict], spawn: Callable[[str], int], own: bool) -> tuple[bool, int | None]:
    """Give `items` to the live helper or to a new one; (False, None) when no helper could start."""
    helper = state.get("helper") or {}
    if alive(helper.get("pid")) and not state.get("helper_finished_at"):
        state["follow_up"] = [*state.get("follow_up", []), *items]
        if items:
            state.pop("others_finished_at", None)
        return True, helper["pid"]
    try:
        pid = spawn(run_id)
    except OSError:
        return False, None
    state["helper"] = {"pid": pid, "started_at": now()}
    state.pop("helper_finished_at", None)
    state.pop("others_finished_at", None)
    state["follow_up"] = items
    if not own:
        state.pop("self", None)
    return True, pid


def follow_item(entry: dict, mode: str, handed: float) -> dict:
    """The saved form of a deferred session; one whose commands are queued is followed from the point it queued them."""
    queued = bool(entry.get("queued"))
    point = ({"handoff_transcript": entry.get("queue_transcript"), "handoff_offset": entry.get("queue_offset")}
             if queued else handoff_point(entry["handle"]))
    return ({key: entry.get(key) for key in ("handle", "host", "actions", "planned", "title", "worktree", "compact_reason", "detail", "probe_retries",
                                             "screen_identified", "input", "ready_signal", "release", "host_release_outdated", "orphaned")}
            | {key: entry[key] for key in ("completed", "note", "compact_after_resume", "queued", "queued_at", "queue_transcript", "queue_offset",
                                           "keep_unrestorable_input", "owes_continue", "compact_while_owing") if entry.get(key)}
            | {"compact_mode": mode, "deferred_at": entry.get("queued_at", handed) if queued else handed, **point})


def add_questions(state: dict, entries: list[dict]) -> list[dict]:
    """Save one question for each session that is `awaiting_answer`, replacing its unanswered earlier one; a session
    already waiting for its answer in this run keeps its question, which is returned again with the new ones."""
    asked = [entry for entry in entries if entry["status"] == "awaiting_answer" and not entry.get("handled")]
    questions = state.setdefault("questions", {})
    for question_id in [key for key, item in questions.items() if not item.get("answer") and item["handle"] in {entry["handle"] for entry in asked}]:
        del questions[question_id]
    created = []
    for entry in asked:
        state["question_seq"] = state.get("question_seq", 0) + 1
        questions[f"q{state['question_seq']}"] = created_item = question_record(f"q{state['question_seq']}", entry)
        created.append(created_item)
    waiting = {entry["handle"] for entry in entries if entry["status"] == "awaiting_answer" and entry.get("handled")}
    return [*(item for item in questions.values() if item["handle"] in waiting and not item.get("answer")), *created]
