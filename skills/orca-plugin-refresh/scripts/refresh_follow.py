from __future__ import annotations

import subprocess
import threading
import time
from typing import Callable

import refresh_install as installs
import refresh_sessions as driver
from refresh_core import RefreshError, parse_time
from refresh_install import validate_install
from refresh_orca import Orca
from refresh_sessions import FINAL_STATUSES, OPEN_STATUSES, compact_reason, host_record, release_held, step, terminal_gone


IDLE_CONFIRM_SECONDS = 3.0
INSTALL_CHECK_SECONDS = 30.0
WAITING_DETAILS = ("busy", "waiting_for_idle", "deadline_reached", "turn_started")


class IdleWaiters:
    """One background Orca idle wait per busy session; the helper acts when a wait reports the session idle."""

    def __init__(self, orca: Orca) -> None:
        self.orca = orca
        self.lock = threading.Lock()
        self.results: dict[str, bool] = {}
        self.threads: dict[str, threading.Thread] = {}
        self.failed: set[str] = set()
        self.processes: list[subprocess.Popen] = []
        self.by_handle: dict[str, list[subprocess.Popen]] = {}
        self.cancelled: set[str] = set()
        self.stopping = False

    def track(self, process: subprocess.Popen, handle: str | None = None) -> None:
        with self.lock:
            self.processes.append(process)
            if handle is not None:
                self.by_handle.setdefault(handle, []).append(process)
            stopping = self.stopping or handle in self.cancelled
        if stopping:
            self.end(process)

    def cancel(self, handle: str) -> None:
        """End one session's idle wait, including a process that registers after this call."""
        with self.lock:
            self.cancelled.add(handle)
            self.results.pop(handle, None)
            processes = list(self.by_handle.get(handle, []))
        for process in processes:
            self.end(process)

    @staticmethod
    def end(process: subprocess.Popen) -> None:
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    def start(self, handle: str, deadline: float) -> None:
        if self.stopping or self.waiting(handle):
            return

        def wait() -> None:
            try:
                idle = self.orca.wait_idle(handle, max(1.0, deadline - time.time()) * 1000, lambda process: self.track(process, handle))
            except (RefreshError, OSError):
                with self.lock:
                    self.failed.add(handle)
                return
            with self.lock:
                self.results[handle] = idle

        with self.lock:
            self.results.pop(handle, None)
        thread = threading.Thread(target=wait, daemon=True)
        self.threads[handle] = thread
        thread.start()

    def waiting(self, handle: str) -> bool:
        thread = self.threads.get(handle)
        return bool(thread and thread.is_alive())

    def take(self, handle: str) -> bool | None:
        with self.lock:
            return self.results.pop(handle, None)

    def stop(self) -> None:
        """Kill every Orca wait, including one registered while stopping, so the helper leaves no child process behind."""
        with self.lock:
            self.stopping = True
            processes = list(self.processes)
        for process in processes:
            self.end(process)
        for thread in list(self.threads.values()):
            thread.join(timeout=5)


def install_current(host: str, target: dict, cache: dict[str, tuple[float, bool]]) -> bool:
    """True while the installed plugin still matches the run's target; rechecked at most every INSTALL_CHECK_SECONDS."""
    checked = cache.get(host)
    if checked and time.time() - checked[0] < INSTALL_CHECK_SECONDS:
        return checked[1]
    try:
        current = installs.installed(host)
        snapshot = validate_install(host, current)
        same = current["root"] == target.get("root") and snapshot["digest"] == target.get("digest")
    except RefreshError:
        same = False
    cache[host] = (time.time(), same)
    return same


def still_needed(entry: dict, state: dict, cache: dict[str, tuple[float, bool]]) -> None:
    """Before a deferred send, stop on a changed install and drop actions the session no longer needs."""
    host = entry["host"]
    target = state["hosts"][host]
    if not install_current(host, target, cache):
        entry.update(status="skipped", detail="install_changed", actions=[])
        return
    marker = driver.read_marker(entry["handle"])
    written = parse_time((marker or {}).get("written_at")) or 0.0
    if marker and written >= entry.get("deferred_at", float("inf")) and compact_reason(host, marker, target, "auto") is None:
        entry.update(status="done", detail="already_current", actions=[])
        return
    if "compact" in entry["actions"] and compact_reason(host, marker, target, state.get("compact_mode", "auto")) is None:
        entry["actions"].remove("compact")
    if not entry["actions"]:
        entry.update(status="done", detail="already_current")


def reloaded_since_handoff(entry: dict) -> bool:
    """True when the transcript the session had at the handoff, read past that point, holds a successful reload."""
    path, offset = entry.get("handoff_transcript"), entry.get("handoff_offset")
    if not isinstance(path, str) or not isinstance(offset, int) or driver.transcript_size(path) < offset:
        return False
    records = driver.transcript_records(path, offset)
    return any(driver.transcript_outcome(entry["host"], "reload", [record]) == "done" for record in records)


def applied_by_session(entry: dict, state: dict, cache: dict[str, tuple[float, bool]], waiters: IdleWaiters) -> None:
    """Finish an entry the session already brought up to date itself since the handoff, even while busy. Sends nothing."""
    host = entry["host"]
    target = state["hosts"][host]
    if not install_current(host, target, cache):
        entry.update(status="skipped", detail="install_changed", actions=[])
        return
    if host == "claude" and "reload" in entry["actions"] and reloaded_since_handoff(entry):
        entry["actions"].remove("reload")
        entry["reloaded_by_session"] = True
    marker = driver.read_marker(entry["handle"])
    written = parse_time((marker or {}).get("written_at")) or 0.0
    if marker and written >= entry.get("deferred_at", float("inf")) and compact_reason(host, marker, target, "auto") is None:
        entry["actions"] = []
    if not entry["actions"]:
        waiters.cancel(entry["handle"])
        entry.update(status="done", detail="applied_by_session" if entry.get("reloaded_by_session") else "already_current")


def follow_up(orca: Orca, entries: list[dict], state: dict, sleep: Callable[[float], None] = time.sleep, waiters: IdleWaiters | None = None,
              progress: Callable[[list[dict]], None] | None = None) -> None:
    """Apply deferred sessions when Orca reports them idle, each before its own deadline, then end every wait.

    `progress` receives the entries that reached a final status since its last call.
    """
    waiters = waiters or IdleWaiters(orca)
    cache: dict[str, tuple[float, bool]] = {}
    reported: set[str] = set()

    def report() -> None:
        finished = [entry for entry in entries if entry["status"] in FINAL_STATUSES and not entry.get("input_held") and entry["handle"] not in reported]
        if finished and progress:
            reported.update(entry["handle"] for entry in finished)
            progress(finished)

    try:
        while True:
            active = [entry for entry in entries if entry["status"] in OPEN_STATUSES or entry.get("input_held")]
            if not active:
                return
            try:
                live = {item.get("handle"): item for item in orca.terminals()}
            except RefreshError:
                live = None
            for entry in active:
                report()
                if release_held(orca, entry):
                    continue
                if entry["status"] == "pending":
                    if live is not None and terminal_gone(entry, live):
                        waiters.cancel(entry["handle"])
                        entry.update(status="skipped", detail="terminal_gone", actions=[])
                        continue
                    if time.time() >= entry["deadline"]:
                        busy = entry.get("detail") in (None, *WAITING_DETAILS)
                        entry.update(status="skipped", detail="not_idle_before_deadline" if busy else entry["detail"], actions=[])
                        continue
                    applied_by_session(entry, state, cache, waiters)
                    if entry["status"] != "pending":
                        continue
                    if live is None:
                        entry["detail"] = "terminal_list_unavailable"
                        continue
                    handle = entry["handle"]
                    if handle not in waiters.failed and entry.get("detail") in WAITING_DETAILS:
                        record = host_record(entry)
                        idle = waiters.take(handle)
                        if record == "busy" or (record is None and idle is None):
                            waiters.start(handle, entry["deadline"])
                            entry["detail"] = "waiting_for_idle"
                            continue
                        if record is None and not idle:
                            continue
                        sleep(IDLE_CONFIRM_SECONDS)
                        if record == "idle" and host_record(entry) != "idle":
                            continue
                    still_needed(entry, state, cache)
                    if entry["status"] != "pending":
                        continue
                    if time.time() >= entry["deadline"]:
                        entry.update(status="skipped", detail="not_idle_before_deadline", actions=[])
                        continue
                try:
                    step(orca, entry, state["hosts"][entry["host"]], live)
                except RefreshError as error:
                    entry.update(status="failed", detail=error.code, actions=[])
            report()
            sleep(driver.POLL_SECONDS)
    finally:
        waiters.stop()
