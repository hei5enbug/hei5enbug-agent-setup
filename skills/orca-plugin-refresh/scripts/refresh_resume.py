from __future__ import annotations

import re
import shlex
import time
from pathlib import Path
from typing import Callable, Sequence

import refresh_sessions as driver
from refresh_core import HANDLE, RefreshError, exclusive, load_run, parse_time, run_path, save_json
from refresh_host_record import record_state
from refresh_orca import Orca
from refresh_process import ProcessOs, SessionProcess, find_session_process, installed_release, launch_arguments, release_of

SESSION_ID = re.compile(r"^[0-9A-Za-z][0-9A-Za-z-]{7,79}$")
EXIT_TIMEOUT = 60.0
MARKER_TIMEOUT = 90.0
READY_TIMEOUT = 20.0
RELOAD_TIMEOUT_AFTER_RESUME = 120.0
POLL = 1.0
RECORD_REASONS = {"busy": "busy", "owing": "background_task", None: "host_record_unavailable"}


def session_id_of(marker: dict | None) -> str | None:
    """The conversation ID: the stem of the transcript file the session marker names."""
    path = (marker or {}).get("transcript_path")
    stem = Path(path).stem if isinstance(path, str) and path.endswith(".jsonl") else None
    return stem if stem and SESSION_ID.fullmatch(stem) else None


def resume_line(claude: str, config_dir: str | None, arguments: Sequence[str], session_id: str) -> str:
    """One shell line: the ended process's own `CLAUDE_CONFIG_DIR`, the current executable, the kept arguments, then the ID."""
    prefix = [f"CLAUDE_CONFIG_DIR={shlex.quote(config_dir)}"] if config_dir else []
    return " ".join([*prefix, shlex.quote(claude), *(shlex.quote(item) for item in arguments),
                     "--resume", shlex.quote(session_id)])


def not_ready_reason(orca: Orca, entry: dict, live: dict[str, dict], sleep: Callable[[float], None]) -> str | None:
    """None only when the session is idle by its own turn record, owes no background notification, and has an empty input line."""
    transcript = (driver.read_marker(entry["handle"]) or {}).get("transcript_path")
    record = record_state("claude", transcript, detailed=True)
    if record != "idle":
        return RECORD_REASONS.get(record, "busy")
    deadline = time.time() + READY_TIMEOUT
    while True:
        reason, _ = driver.ready(orca, entry, live)
        if reason != "input_settling" or time.time() >= deadline:
            break
        sleep(driver.POLL_SECONDS)
    if reason:
        return reason
    empty, _ = driver.line_empty(orca, entry["handle"], sleep=sleep)
    return None if empty else "unsent_input"


def wait_for(check: Callable[[], bool], timeout: float, sleep: Callable[[float], None]) -> bool:
    deadline = time.time() + timeout
    while True:
        if check():
            return True
        if time.time() >= deadline:
            return False
        sleep(POLL)


def process_ended(handle: str, pid: int, system: ProcessOs | None) -> bool:
    try:
        current = find_session_process(handle, system)
    except RefreshError:
        return False
    return current is None or current.pid != pid


def resumed_marker(handle: str, snapshot: dict | None, sent_at: float) -> dict | None:
    marker = driver.read_marker(handle)
    written = parse_time((marker or {}).get("written_at"))
    if marker and marker != snapshot and written is not None and written >= sent_at:
        return marker
    return None


def finished(result: dict, status: str, detail: str, **extra: object) -> dict:
    return {**result, "status": status, "detail": detail, **extra}


def reload_after_resume(orca: Orca, entry: dict, state: dict, sleep: Callable[[float], None]) -> dict:
    follow = {"handle": entry["handle"], "host": "claude", "title": entry.get("title"), "worktree": entry.get("worktree"),
              "initiator": False, "screen_identified": entry.get("screen_identified"), "actions": ["reload"],
              "status": "pending", "detail": None}
    driver.drive(orca, [follow], state, time.time() + RELOAD_TIMEOUT_AFTER_RESUME, sleep)
    extra = {"plugin_load": follow["plugin_load"]} if follow.get("plugin_load") else {}
    if follow["status"] == "done":
        return {"status": "done", "detail": "resumed", **extra}
    detail = follow.get("detail") or "reload_unconfirmed"
    return {"status": "failed", "detail": detail if detail == "plugin_load_error" else f"reload_{detail}", **extra}


def end_and_resume(orca: Orca, entry: dict, state: dict, process: SessionProcess, line: str, session_id: str,
                   system: ProcessOs | None, sleep: Callable[[float], None]) -> dict:
    handle = entry["handle"]
    orca.send(handle, "/exit")
    if not wait_for(lambda: process_ended(handle, process.pid, system), EXIT_TIMEOUT, sleep):
        return {"status": "failed", "detail": "exit_timeout"}
    snapshot, sent_at = driver.read_marker(handle), time.time()
    orca.send(handle, line)
    marker: dict | None = None

    def rewritten() -> bool:
        nonlocal marker
        marker = resumed_marker(handle, snapshot, sent_at)
        return marker is not None

    if not wait_for(rewritten, MARKER_TIMEOUT, sleep):
        return {"status": "failed", "detail": "resume_marker_missing"}
    if marker.get("source") != "resume" or session_id_of(marker) != session_id:
        return {"status": "failed", "detail": "resume_session_mismatch"}
    try:
        started = find_session_process(handle, system)
    except RefreshError:
        started = None
    if started is None:
        return {"status": "failed", "detail": "resumed_process_missing"}
    after = {"release_after": release_of(started.exe)}
    if started.config_dir != process.config_dir:
        return finished(after, "failed", "config_dir_mismatch")
    return {**after, **reload_after_resume(orca, entry, state, sleep)}


def resume_session(orca: Orca, entry: dict, state: dict, live: dict[str, dict], system: ProcessOs | None,
                   sleep: Callable[[float], None]) -> dict:
    """End and resume one session only when every check judges it idle; otherwise `skipped` with the reason."""
    result = {"release_before": entry.get("release")}
    session_id = session_id_of(driver.read_marker(entry["handle"]))
    if session_id is None:
        return finished(result, "skipped", "session_id_unknown")
    reason = not_ready_reason(orca, entry, live, sleep)
    if reason:
        return finished(result, "skipped", reason)
    try:
        process = find_session_process(entry["handle"], system)
    except RefreshError as error:
        return finished(result, "skipped", error.code)
    claude = installed_release(system)[1]
    if process is None or claude is None:
        return finished(result, "skipped", "process_not_found" if process is None else "claude_missing")
    arguments = launch_arguments(claude, process.argv, system)
    if arguments is None:
        return finished(result, "skipped", "launch_arguments_unknown")
    line = resume_line(claude, process.config_dir, arguments, session_id)
    note = {} if process.config_dir else {"note": "no_config_dir_in_process"}
    return {**result, **note, **end_and_resume(orca, entry, state, process, line, session_id, system, sleep)}


def resume_view(handle: str, entry: dict | None, result: dict) -> dict:
    view = {"terminal": f"…{handle[-6:]}", "worktree": (entry or {}).get("worktree"), **result}
    return {key: value for key, value in view.items() if value not in (None, [], False)}


def run_resume(run_id: str, handles: Sequence[str], orca: Orca | None = None, system: ProcessOs | None = None,
               sleep: Callable[[float], None] = time.sleep) -> dict:
    """Resume the named sessions the user approved in this request; every other session stays untouched."""
    invalid = [handle for handle in handles if not HANDLE.fullmatch(handle)]
    if invalid or not handles:
        raise RefreshError("terminal_invalid", "Name each approved session with a valid --terminal handle.")
    with exclusive("sessions"):
        state = load_run(run_id)
        orca = orca or Orca()
        requested = list(dict.fromkeys(handles))
        entries = {entry["handle"]: entry for entry in driver.plan_sessions(orca, state, "never", requested)}
        live = {item.get("handle"): item for item in orca.terminals()}
        views = []
        for handle in requested:
            entry = entries.get(handle)
            if entry is None or entry["host"] != "claude":
                result = {"status": "skipped", "detail": "not_a_claude_session"}
            else:
                try:
                    result = resume_session(orca, entry, state, live, system, sleep)
                except RefreshError as error:
                    result = {"status": "failed", "detail": error.code}
            views.append((handle, resume_view(handle, entry, result)))
        state["resumed"] = {**state.get("resumed", {}), **{handle: view for handle, view in views}}
        save_json(run_path(run_id), state)
    sessions = [view for _, view in views]
    return {"ok": all(view["status"] == "done" for view in sessions), "run_id": run_id, "sessions": sessions}
