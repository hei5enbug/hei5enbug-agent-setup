from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Sequence

import refresh_sessions as driver
from refresh_core import HANDLE, RefreshError, exclusive, load_run, run_path, save_json
from refresh_host_record import record_state
from refresh_orca import Orca

CLOSE_IDLE_SECONDS = 24 * 60 * 60
READY_TIMEOUT = 20.0
RECORD_FAILURES = {"busy": "turn_busy", "owing": "background_task_pending", None: "turn_record_unavailable"}


def idle_seconds(marker: dict | None, now: float) -> float | None:
    """Seconds since the session's transcript or rollout was last written; None when it cannot be read."""
    path = (marker or {}).get("transcript_path")
    try:
        return max(0.0, now - Path(path).stat().st_mtime) if isinstance(path, str) else None
    except OSError:
        return None


def input_failure(orca: Orca, entry: dict, live: dict[str, dict], sleep: Callable[[float], None]) -> str | None:
    """`input_not_empty` or `input_unknown` unless the host's input line is readable and holds nothing typed."""
    deadline = time.time() + READY_TIMEOUT
    try:
        while True:
            reason, _ = driver.ready(orca, entry, live)
            if reason != "input_settling" or time.time() >= deadline:
                break
            sleep(driver.POLL_SECONDS)
        if reason:
            return "input_not_empty" if reason == "unsent_input" else "input_unknown"
        empty, _ = driver.input_cleared(orca, entry)
    except RefreshError:
        return "input_unknown"
    return None if empty else "input_not_empty"


def failing_check(orca: Orca, entry: dict, live: dict[str, dict], now: float, sleep: Callable[[float], None]) -> str | None:
    """The first check that keeps a terminal from being recommended for closing, or None when every check passes."""
    terminal = live[entry["handle"]]
    if terminal.get("connected") is not True or terminal.get("writable") is not True:
        return "terminal_unreachable"
    marker = driver.read_marker(entry["handle"])
    record = record_state(entry["host"], (marker or {}).get("transcript_path"), detailed=True)
    if record != "idle":
        return RECORD_FAILURES.get(record, "turn_busy")
    idle = idle_seconds(marker, now)
    if idle is None:
        return "activity_unknown"
    if idle < CLOSE_IDLE_SECONDS:
        return "recently_active"
    return input_failure(orca, entry, live, sleep)


def orphan_entry(orca: Orca, terminal: dict) -> dict | None:
    host = driver.terminal_host(orca, terminal)
    handle = terminal.get("handle")
    if host is None or not isinstance(handle, str) or not HANDLE.fullmatch(handle):
        return None
    return {"handle": handle, "host": host, "screen_identified": driver.marker_host(terminal) is not None}


def live_terminals(orca: Orca) -> dict[str, dict]:
    return {item.get("handle"): item for item in orca.terminals()}


def describe(entry: dict, terminal: dict, now: float, failed: str | None) -> dict:
    idle = idle_seconds(driver.read_marker(entry["handle"]), now)
    return {"handle": entry["handle"], "terminal": f"…{entry['handle'][-6:]}", "host": entry["host"],
            "worktree": terminal.get("worktreePath"), "idle_seconds": None if idle is None else int(idle),
            "recommended": failed is None, "failed_check": failed}


def list_orphans(orca: Orca, now: float, sleep: Callable[[float], None]) -> list[dict]:
    live = live_terminals(orca)
    items = []
    for terminal in live.values():
        entry = orphan_entry(orca, terminal) if terminal.get("orphaned") is True else None
        if entry is not None:
            items.append(describe(entry, terminal, now, failing_check(orca, entry, live, now, sleep)))
    return items


def run_orphans(run_id: str, orca: Orca | None = None, sleep: Callable[[float], None] = time.sleep) -> dict:
    """List orphaned agent terminals and name the check that keeps each unrecommended one open; closes nothing."""
    with exclusive("sessions"):
        load_run(run_id)
        orphans = list_orphans(orca or Orca(), time.time(), sleep)
    return {"ok": True, "run_id": run_id, "orphans": orphans,
            "recommended": [item["handle"] for item in orphans if item["recommended"]]}


def close_terminal(orca: Orca, handle: str, now: float, sleep: Callable[[float], None]) -> dict:
    """Close one approved terminal only when it is still an orphaned agent terminal and every check passes again."""
    live = live_terminals(orca)
    terminal = live.get(handle)
    if terminal is None:
        return {"status": "skipped", "detail": "terminal_not_found"}
    if terminal.get("orphaned") is not True:
        return {"status": "skipped", "detail": "not_orphaned"}
    entry = orphan_entry(orca, terminal)
    if entry is None:
        return {"status": "skipped", "detail": "not_an_agent_session"}
    failed = failing_check(orca, entry, live, now, sleep)
    view = describe(entry, terminal, now, failed)
    base = {key: view[key] for key in ("terminal", "host", "worktree", "idle_seconds")}
    if failed:
        return {**base, "status": "skipped", "detail": failed}
    error = None
    try:
        orca.close(handle)
    except RefreshError as caught:
        error = caught.code
    if handle in live_terminals(orca):
        return {**base, "status": "failed", "detail": error or "close_unconfirmed"}
    return {**base, "status": "closed"}


def run_close(run_id: str, handles: Sequence[str], orca: Orca | None = None,
              sleep: Callable[[float], None] = time.sleep) -> dict:
    """Close the named terminals the user approved in this request; every other terminal stays open."""
    if not handles or any(not HANDLE.fullmatch(handle) for handle in handles):
        raise RefreshError("terminal_invalid", "Name each approved terminal with a valid --terminal handle.")
    with exclusive("sessions"):
        state = load_run(run_id)
        orca = orca or Orca()
        results = {}
        for handle in dict.fromkeys(handles):
            try:
                result = close_terminal(orca, handle, time.time(), sleep)
            except RefreshError as error:
                result = {"status": "failed", "detail": error.code}
            results[handle] = {"terminal": f"…{handle[-6:]}", **result}
        state["closed"] = {**state.get("closed", {}), **results}
        save_json(run_path(run_id), state)
    sessions = list(results.values())
    return {"ok": all(item["status"] == "closed" for item in sessions), "run_id": run_id, "sessions": sessions}
