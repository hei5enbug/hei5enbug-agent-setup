from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import refresh_interrupt as interrupts
import refresh_sessions as driver
from refresh_core import RefreshError, load_run, update_run
from refresh_install import rollout_busy, rollout_last_record, rollout_open
from refresh_orca import Orca


def job_of(run_id: str) -> dict:
    return load_run(run_id).get("codex_install") or {}


def pending(state: dict) -> bool:
    return (state.get("codex_install") or {}).get("status") == "pending"


def change_job(run_id: str, **changes: object) -> dict:
    def change(saved: dict) -> dict:
        saved["codex_install"] = {**saved.get("codex_install", {}), **changes}
        return saved

    return update_run(run_id, change)["codex_install"]


def waiting_on(job: dict) -> list[str]:
    """The rollouts of the sessions the install still waits for that have not ended their turn."""
    return [path for path in job.get("waits", []) if rollout_open(Path(path))]


def claim(run_id: str) -> str:
    """Move a pending job to `installing` under the run-state lock. `claimed` goes to the one caller that does; `expired`
    means the job's deadline passed first, and `gone` that another caller already took or ended it."""
    outcome: list[str] = []

    def change(saved: dict) -> dict | None:
        job = saved.get("codex_install") or {}
        if job.get("status") != "pending":
            outcome.append("gone")
            return None
        expired = time.time() >= job["deadline"]
        job["status"] = "not_idle_before_deadline" if expired else "installing"
        outcome.append("expired" if expired else "claimed")
        return saved

    update_run(run_id, change)
    return outcome[0]


def aborted(path: Path) -> bool:
    record = rollout_last_record(path)
    payload = record.get("payload") if record else None
    return isinstance(payload, dict) and payload.get("type") == "turn_aborted"


def set_state(run_id: str, index: int, state: str, wait: bool = False) -> None:
    def change(saved: dict) -> dict:
        job = saved["codex_install"]
        job["interrupts"][index]["state"] = state
        if wait:
            job["waits"] = [*job.get("waits", []), job["interrupts"][index]["rollout"]]
        return saved

    update_run(run_id, change)


def interrupt_all(orca: Orca, run_id: str, sleep: Callable[[float], None]) -> None:
    """Send one Esc to each session answered `interrupt` that is still busy and confirm its turn ended. A session whose turn
    does not end within the interrupt limit, or whose Esc may already have been sent, is waited for instead; nothing more is
    sent to it. A session saved as `interrupted` is the only one that is asked to continue later."""
    for index, item in enumerate(job_of(run_id).get("interrupts", [])):
        if item["state"] == "esc_sent":
            set_state(run_id, index, "unconfirmed", wait=True)
            continue
        if item["state"] != "queued":
            continue
        path = Path(item["rollout"]) if item.get("rollout") else None
        if path is None or not rollout_busy(path):
            set_state(run_id, index, "idle")
            continue
        live = {terminal.get("handle"): terminal for terminal in orca.terminals()}
        if driver.terminal_gone({"handle": item["handle"], "host": "codex"}, live) or (
                (driver.read_marker(item["handle"]) or {}).get("transcript_path") != item["rollout"]):
            set_state(run_id, index, "unconfirmed", wait=True)
            continue
        try:
            orca.keys(item["handle"], interrupts.ESCAPE_KEY)
        except RefreshError:
            set_state(run_id, index, "unconfirmed", wait=True)
            continue
        set_state(run_id, index, "esc_sent")
        deadline = time.time() + interrupts.INTERRUPT_SECONDS
        while rollout_busy(path) and time.time() < deadline:
            sleep(driver.POLL_SECONDS)
        if rollout_busy(path):
            set_state(run_id, index, "unconfirmed", wait=True)
        else:
            set_state(run_id, index, "interrupted" if aborted(path) else "idle")


def job_view(job: dict) -> dict:
    view = {key: job[key] for key in ("status", "detail", "answers") if job.get(key)}
    interrupted = [{"terminal": f"…{item['handle'][-6:]}", "state": item["state"]} for item in job.get("interrupts", [])]
    return {**view, **({"interrupts": interrupted} if interrupted else {})}
