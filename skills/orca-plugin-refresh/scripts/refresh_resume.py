from __future__ import annotations

import re
import shlex
import time
from pathlib import Path
from typing import Callable, Sequence

import refresh_sessions as driver
import refresh_codex_session as codex_session
from refresh_core import HANDLE, RefreshError, exclusive, load_run, parse_time, update_run
from refresh_host_record import record_state
from refresh_orca import Orca
from refresh_screen import screen_shape, shell_prompt_empty
from refresh_process import (ProcessOs, SessionProcess, find_session_process, installed_release, launch_arguments, release_of,
                             scan_session_processes)

SESSION_ID = re.compile(r"^[0-9A-Za-z][0-9A-Za-z-]{7,79}$")
EXIT_TIMEOUT = 60.0
LATE_EXIT_TIMEOUT = 120.0
MARKER_TIMEOUT = 90.0
READY_TIMEOUT = 20.0
RELOAD_TIMEOUT_AFTER_RESUME = 120.0
POLL = 1.0
RECORD_REASONS = {"busy": "busy", "owing": "background_task", None: "host_record_unavailable"}


def session_id_of(marker: dict | None) -> str | None:
    """The conversation ID: the stem of the transcript file the session marker names."""
    if (marker or {}).get("host") == "codex":
        return codex_session.rollout_identity(marker)[0]
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
    record = record_state(entry["host"], transcript, detailed=True)
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
    if entry["host"] == "codex":
        return None
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


def process_state(handle: str, pid: int, system: ProcessOs | None, host: str = "claude") -> str:
    """`ended` only when the process list was read and shows the process gone; `unreadable` when it could not be read."""
    try:
        found, unreadable = scan_session_processes(handle, system, host)
    except RefreshError:
        return "unreadable"
    if pid in unreadable:
        return "unreadable"
    return "running" if any(item.pid == pid for item in found) else "ended"


def at_shell_prompt(orca: Orca, handle: str) -> bool:
    try:
        return shell_prompt_empty(orca.screen(handle)[0])
    except RefreshError:
        return False


LATE_EXIT_STATES = {"ended": "ended_late", "unreadable": "process_list_unreadable", "running": "still_running"}


def late_exit_failure(orca: Orca, handle: str, pid: int, line: str, system: ProcessOs | None,
                      sleep: Callable[[float], None], host: str = "claude") -> dict | None:
    """Keep checking after the exit wait ran out; None once the process is gone and the terminal shows an empty shell
    prompt, otherwise the failure that gives the user the terminal and the exact resume line."""
    state = "running"
    screen: list[str] | None = None

    def settled() -> bool:
        nonlocal state, screen
        state, screen = process_state(handle, pid, system, host), None
        if state != "ended":
            return False
        try:
            screen = orca.screen(handle)[0]
        except RefreshError:
            return False
        return shell_prompt_empty(screen)

    if wait_for(settled, LATE_EXIT_TIMEOUT, sleep):
        return None
    failure = {"status": "failed", "detail": "exit_timeout", "exit_state": LATE_EXIT_STATES[state], "terminal_handle": handle,
               "resume_line": line}
    shape = {"prompt_shape": screen_shape(screen)} if state == "ended" and screen is not None else {}
    return {**failure, **shape}


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
                   system: ProcessOs | None, sleep: Callable[[float], None], reload: bool = True) -> dict:
    handle = entry["handle"]
    live = {item.get("handle"): item for item in orca.terminals()}
    reason = not_ready_reason(orca, entry, live, sleep)
    if reason:
        return {"status": "skipped", "detail": reason}
    orca.send(handle, "/exit")
    late: dict = {}

    def shell_ready() -> bool:
        return process_state(handle, process.pid, system, entry["host"]) == "ended" and at_shell_prompt(orca, handle)

    if not wait_for(shell_ready, EXIT_TIMEOUT, sleep):
        failure = late_exit_failure(orca, handle, process.pid, line, system, sleep, entry["host"])
        if failure:
            return failure
        late = {"exit_late": True}
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
    if entry["host"] == "codex":
        target = state.get("hosts", {}).get("codex", {})
        if any(marker.get(key) != target.get(key) for key in ("root", "digest")):
            return {"status": "failed", "detail": "resume_plugin_mismatch"}
    try:
        started = find_session_process(handle, system, entry["host"])
    except RefreshError:
        started = None
    if started is None:
        return {"status": "failed", "detail": "resumed_process_missing"}
    after = {"release_after": release_of(started.exe), **late}
    if started.config_dir != process.config_dir:
        return finished(after, "failed", "config_dir_mismatch")
    if not reload:
        return {**after, "status": "done", "detail": "resumed"}
    return {**after, **reload_after_resume(orca, entry, state, sleep)}


def resume_session(orca: Orca, entry: dict, state: dict, live: dict[str, dict], system: ProcessOs | None,
                   sleep: Callable[[float], None], reload: bool = True) -> dict:
    """End and resume one session only when every check judges it idle; otherwise `skipped` with the reason."""
    result = {"release_before": entry.get("release")}
    session_id = session_id_of(driver.read_marker(entry["handle"]))
    if session_id is None:
        return finished(result, "skipped", "session_id_unknown")
    host = entry["host"]
    reason = not_ready_reason(orca, entry, live, sleep)
    if reason:
        position = {"probe_position": entry["probe_position"]} if reason == "probe_interrupted" and entry.get("probe_position") else {}
        return finished(result, "skipped", reason, **position)
    try:
        process = find_session_process(entry["handle"], system, host)
    except RefreshError as error:
        return finished(result, "skipped", error.code)
    claude = (system or ProcessOs()).which("codex") if host == "codex" else installed_release(system)[1]
    if process is None or claude is None:
        return finished(result, "skipped", "process_not_found" if process is None else f"{host}_missing")
    arguments = (codex_session.resume_arguments(process.argv, (system or ProcessOs()).help_text(claude))
                 if host == "codex" else launch_arguments(claude, process.argv, system))
    if arguments is None:
        return finished(result, "skipped", "launch_arguments_unknown")
    line = (codex_session.resume_line if host == "codex" else resume_line)(claude, process.config_dir, arguments, session_id)
    note = {} if process.config_dir else {"note": "no_config_dir_in_process"}
    return {**result, **note, **end_and_resume(orca, entry, state, process, line, session_id, system, sleep, reload and host == "claude")}


def resume_view(handle: str, entry: dict | None, result: dict) -> dict:
    view = {"terminal": f"…{handle[-6:]}", "host": (entry or {}).get("host"), "worktree": (entry or {}).get("worktree"), **result}
    return {key: value for key, value in view.items() if value not in (None, [], False)}


RESUME_CARRIED = ("note", "exit_late", "exit_state", "terminal_handle", "resume_line", "prompt_shape", "probe_position")


def record_resume(entry: dict, result: dict) -> None:
    """Fold one resume result into an apply entry: no reload is left for a resumed session, a compact only when planned."""
    carried = {key: result[key] for key in RESUME_CARRIED if result.get(key)}
    if result["status"] == "skipped":
        entry.update(resume_check=result["detail"], **{key: value for key, value in carried.items() if key == "probe_position"})
    elif result["status"] == "done":
        remaining = [action for action in entry["actions"] if action == "compact"]
        entry.pop("host_release_outdated", None)
        entry.update(carried, release=result.get("release_after") or entry.get("release"), actions=remaining,
                     completed=[*entry.get("completed", []), "resumed"], status="pending" if remaining else "done",
                     detail=None if remaining else "applied", **({"compact_after_resume": True} if remaining else {}))
    else:
        entry.update(carried, status="failed", detail=result["detail"])


def saved_detail(state: dict, handle: str) -> str | None:
    """The detail this run already saved for a session; a `plugin_load_error` keeps it waiting for the user's approval."""
    return (state.get("sessions", {}).get(handle) or {}).get("detail")


def resume_outdated(orca: Orca, sessions: Sequence[dict], state: dict, run_id: str, system: ProcessOs | None = None,
                    sleep: Callable[[float], None] = time.sleep) -> None:
    """Resume, before anything else is sent, each session that runs an older release and passes every resume check.

    A session that fails a check stays as planned and keeps its place in the resume approval list."""
    candidates = [entry for entry in sessions if entry["host"] == "claude" and entry.get("host_release_outdated")
                  and entry["status"] == "pending" and not entry["initiator"] and not entry.get("handled")
                  and saved_detail(state, entry["handle"]) != "plugin_load_error"]
    views: dict[str, dict] = {}
    for entry in candidates:
        live = {item.get("handle"): item for item in orca.terminals()}
        try:
            result = resume_session(orca, entry, state, live, system, sleep, reload=False)
        except RefreshError as error:
            result = {"status": "failed", "detail": error.code}
        record_resume(entry, result)
        if result["status"] != "skipped":
            views[entry["handle"]] = resume_view(entry["handle"], entry, result)
    if views:
        update_run(run_id, lambda saved: {**saved, "resumed": {**saved.get("resumed", {}), **views}})


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
            if entry is None or entry["host"] not in {"claude", "codex"}:
                result = {"status": "skipped", "detail": "not_an_agent_session"}
            elif entry["host"] == "codex" and entry.get("detail") != "codex_plugin_folder_replaced":
                result = {"status": "skipped", "detail": "resume_not_needed"}
            else:
                try:
                    result = resume_session(orca, entry, state, live, system, sleep)
                except RefreshError as error:
                    result = {"status": "failed", "detail": error.code}
            views.append((handle, resume_view(handle, entry, result)))
        def save_results(saved: dict) -> dict:
            saved["resumed"] = {**saved.get("resumed", {}), **dict(views)}
            for handle, view in views:
                if view["status"] == "done" and view.get("host") == "codex":
                    saved.setdefault("sessions", {})[handle] = {**view, "completed": ["resumed"]}
            return saved
        update_run(run_id, save_results)
    sessions = [view for _, view in views]
    return {"ok": all(view["status"] == "done" for view in sessions), "run_id": run_id, "sessions": sessions}
