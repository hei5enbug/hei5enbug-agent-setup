from __future__ import annotations

import time
from typing import Callable

import refresh_sessions as driver
from refresh_core import RefreshError
from refresh_host_record import record_state
from refresh_orca import Orca
from refresh_process import ProcessOs
from refresh_resume import RESUME_CARRIED, resume_session

ESCAPE_KEY = "\x1b"
INTERRUPT_SECONDS = 15.0
APPLY_SECONDS = 60.0
CONTINUE_SECONDS = 30.0
CONTINUE_PROMPT = "A plugin update interrupted the work you were doing. Please continue that work from where it stopped."


def turn_record(entry: dict) -> str | None:
    return record_state(entry["host"], (driver.read_marker(entry["handle"]) or {}).get("transcript_path"), detailed=True)


def send_continue(orca: Orca, entry: dict, sleep: Callable[[float], None]) -> None:
    """Ask the session to continue its work once it is idle with an empty input line; never types over input."""
    deadline = time.time() + CONTINUE_SECONDS
    reason: str | None = "not_attempted"
    while time.time() < deadline:
        live = {item.get("handle"): item for item in orca.terminals()}
        reason, _ = driver.ready(orca, entry, live)
        if reason is None and orca.draft(entry["handle"]) == entry.get("observed_draft"):
            orca.send(entry["handle"], CONTINUE_PROMPT)
            entry["continue_prompt"] = "sent"
            return
        if reason in ("terminal_gone", "unsent_input", "probe_interrupted"):
            break
        sleep(driver.POLL_SECONDS)
    entry["continue_prompt"] = f"not_sent:{reason}"


def resume_without_reload(orca: Orca, entry: dict, state: dict, system: ProcessOs | None, sleep: Callable[[float], None]) -> str | None:
    """End and resume the session, which loads the new plugins and instructions; None when the entry reached a final result,
    otherwise the detail of the resume check that held it back."""
    live = {item.get("handle"): item for item in orca.terminals()}
    try:
        result = resume_session(orca, entry, state, live, system, sleep, reload=False)
    except RefreshError as error:
        result = {"status": "failed", "detail": error.code}
    if result["status"] == "skipped":
        return result["detail"]
    carried = {key: result[key] for key in RESUME_CARRIED if result.get(key)}
    if result["status"] == "done":
        entry.update(carried, status="done", detail="applied", actions=[], note="resumed_without_compaction",
                     completed=[*entry.get("completed", []), "resumed"], release=result.get("release_after") or entry.get("release"))
    else:
        entry.update(carried, status="failed", detail=result["detail"], actions=[])
    return None


def interrupt_apply(orca: Orca, entry: dict, state: dict, system: ProcessOs | None = None,
                    sleep: Callable[[float], None] = time.sleep) -> None:
    """Apply to one session after the user answered `interrupt`.

    An idle session is applied normally with no continue prompt. Otherwise one Esc goes out and the turn record must leave
    busy within INTERRUPT_SECONDS, or the entry fails and nothing else is sent. A session that then owes nothing is ended and
    resumed with no compaction, or, when the resume check holds it back, gets the reload alone; one that may owe a background
    notification gets the reload, and the compaction when planned. The continue prompt goes out last, after the actions are
    confirmed; a session handed to the helper keeps `owes_continue` and the helper sends it.
    """
    handle = entry["handle"]
    verdict = turn_record(entry)
    if verdict in ("idle", "owing") or (verdict is None and orca.idle(handle)):
        driver.drive(orca, [entry], state, time.time() + APPLY_SECONDS, sleep, expire="deferred")
        return
    orca.keys(handle, ESCAPE_KEY)
    deadline = time.time() + INTERRUPT_SECONDS
    while verdict not in ("idle", "owing"):
        if time.time() >= deadline:
            entry.update(status="failed", detail="interrupt_unconfirmed", actions=[])
            return
        sleep(driver.POLL_SECONDS)
        verdict = turn_record(entry)
    entry["owes_continue"] = True
    unresumed = resume_without_reload(orca, entry, state, system, sleep) if verdict == "idle" else ""
    if unresumed is not None:
        if verdict == "idle":
            entry.update(actions=[action for action in entry["actions"] if action != "compact"], note=f"resume_check_skipped:{unresumed}")
        else:
            entry["compact_while_owing"] = True
        driver.drive(orca, [entry], state, time.time() + APPLY_SECONDS, sleep, expire="deferred")
    if entry["status"] == "done":
        send_continue(orca, entry, sleep)
    elif entry["status"] != "deferred":
        entry["continue_prompt"] = f"not_sent:{entry['status']}"
