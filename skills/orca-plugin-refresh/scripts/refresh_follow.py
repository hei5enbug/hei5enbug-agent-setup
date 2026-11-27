from __future__ import annotations

import subprocess
import threading
import time
from contextlib import AbstractContextManager, ExitStack
from typing import Callable

import refresh_install as installs
import refresh_sessions as driver
from refresh_core import RefreshError, parse_time
from refresh_dialog import answer_compact_dialog, dialog_open
from refresh_host_record import record_state
from refresh_install import validate_install
from refresh_interrupt import send_continue
from refresh_orca import Orca
from refresh_process import ProcessOs
from refresh_resume import resume_deferred
from refresh_sessions import FINAL_STATUSES, OPEN_STATUSES, compact_reason, host_record, release_held, restorable_text, step, terminal_gone


IDLE_CONFIRM_SECONDS = 3.0
INSTALL_CHECK_SECONDS = 30.0
TIMESTAMP_RESOLUTION = 0.001
WAITING_DETAILS = ("busy", "waiting_for_idle", "deadline_reached", "turn_started", "background_task")


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


class SendLock:
    """Holds the machine-wide sessions lock across loop passes only while a command is in flight or typed text is held."""

    def __init__(self, factory: Callable[[], AbstractContextManager] | None = None) -> None:
        self.factory = factory
        self.stack: ExitStack | None = None

    def acquire(self) -> bool:
        if self.factory is None or self.stack is not None:
            return True
        stack = ExitStack()
        try:
            stack.enter_context(self.factory())
        except RefreshError as error:
            if error.code != "already_running":
                raise
            return False
        self.stack = stack
        return True

    def release(self) -> None:
        stack, self.stack = self.stack, None
        if stack is not None:
            stack.close()


def sending(entries: list[dict]) -> bool:
    return any(entry["status"] in ("sent", "restoring") or entry.get("input_held") for entry in entries)


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


def compact_owed(entry: dict, marker: dict | None) -> bool:
    """True while a compaction planned for the conversation a resume carried over is still outstanding. The resume
    rewrote the marker with the installed digest, so only a marker rewritten after the handoff by a compaction or a
    clear shows it is done."""
    if not entry.get("compact_after_resume") or "compact" not in entry["actions"]:
        return False
    written = parse_time((marker or {}).get("written_at")) or 0.0
    return not (marker and marker.get("source") in ("compact", "clear") and written >= entry.get("deferred_at", float("inf")))


NEW_PROCESS_SOURCES = ("startup", "resume")


def after_handoff_actions(entry: dict, marker: dict | None, target: dict) -> list[str]:
    """The entry's actions minus those a marker rewritten after the handoff settles. A reload is settled only by a new
    process (source `startup` or `resume`), whatever digest or root the marker holds; every other action is settled by a
    marker that passes the automatic compaction check and is not owed a compaction after a resume."""
    written = parse_time((marker or {}).get("written_at")) or 0.0
    if not marker or written < entry.get("deferred_at", float("inf")):
        return list(entry["actions"])
    new_process = entry["host"] == "claude" and marker.get("source") in NEW_PROCESS_SOURCES
    settled = compact_reason(entry["host"], marker, target, "auto") is None and not compact_owed(entry, marker)
    return [action for action in entry["actions"] if not (new_process if action == "reload" else settled)]


def current_actions(entry: dict, state: dict) -> list[str]:
    """The actions the entry still needs once `still_needed` would apply its rules, without changing the entry."""
    target = state["hosts"][entry["host"]]
    marker = driver.read_marker(entry["handle"])
    actions = after_handoff_actions(entry, marker, target)
    mode = entry.get("compact_mode") or state.get("compact_mode", "auto")
    if "compact" in actions and not compact_owed(entry, marker) and compact_reason(entry["host"], marker, target, mode) is None:
        actions.remove("compact")
    return actions


def still_needed(entry: dict, state: dict, cache: dict[str, tuple[float, bool]]) -> None:
    """Before a deferred send, stop on a changed install and drop actions the session no longer needs."""
    host = entry["host"]
    target = state["hosts"][host]
    if not install_current(host, target, cache):
        entry.update(status="skipped", detail="install_changed", actions=[])
        return
    entry["actions"] = current_actions(entry, state)
    if not entry["actions"]:
        entry.update(status="done", detail="already_current")


def reloaded_since_handoff(entry: dict) -> bool:
    """True when the transcript the session had at the handoff, read past that point, holds a successful reload."""
    path, offset = entry.get("handoff_transcript"), entry.get("handoff_offset")
    if not isinstance(path, str) or not isinstance(offset, int) or driver.transcript_size(path) < offset:
        return False
    records = driver.transcript_records(path, offset)
    return any(driver.transcript_outcome(entry["host"], "reload", [record], entry) == "done" for record in records)


def queued_outcome(entry: dict, state: dict) -> str | None:
    """The result of the first queued command, from transcript records after the queue offset or, for a compaction, from
    a marker rewritten after the queue time that passes the automatic compaction check."""
    action = entry["queued"][0]
    outcome = driver.transcript_outcome(entry["host"], action, driver.transcript_records(entry.get("queue_transcript"), entry.get("queue_offset", 0)), entry)
    if outcome or action != "compact":
        return outcome
    marker = driver.read_marker(entry["handle"])
    written = parse_time((marker or {}).get("written_at")) or 0.0
    if marker and written + TIMESTAMP_RESOLUTION >= entry.get("queued_at", float("inf")) and compact_reason(entry["host"], marker, state["hosts"][entry["host"]], "auto") is None:
        return "done"
    return None


def queued_progress(orca: Orca, entry: dict, state: dict, cache: dict[str, tuple[float, bool]], lock: SendLock) -> bool:
    """Confirm the commands typed into the session while its turn was in progress, sending nothing more. True when this
    pass is finished with the entry; False once the queue is given up and the ordinary path takes over."""
    if not install_current(entry["host"], state["hosts"][entry["host"]], cache):
        entry.update(status="skipped", detail="install_changed", actions=[])
        return True
    outcome = queued_outcome(entry, state)
    if outcome:
        entry["queued"].pop(0)
        if outcome == "nothing_to_compact" and driver.claude_has_prompts((driver.read_marker(entry["handle"]) or {}).get("transcript_path")):
            driver.compaction_refused(entry)
        elif outcome == "nothing_to_compact":
            entry["actions"][0] = "clear"
            entry.update(queued=[], detail="empty_session_needs_clear")
            return False
        else:
            driver.finish(entry, outcome)
        if entry["status"] != "pending":
            entry["queued"] = []
        return True
    entry["detail"] = "commands_queued"
    turn = record_state(entry["host"], (driver.read_marker(entry["handle"]) or {}).get("transcript_path"), detailed=True)
    if turn not in ("idle", "owing"):
        entry.pop("queue_idle_since", None)
        return True
    if "compact" in entry["queued"]:
        try:
            lines = orca.screen(entry["handle"])[0]
        except RefreshError:
            return True
        if dialog_open(lines):
            if lock.acquire() and answer_compact_dialog(orca, entry, lines).startswith("failed:"):
                entry.update(status="failed", detail="compact_dialog_open", actions=[], queued=[])
            return True
    limits = {"reload": driver.RELOAD_TIMEOUT, "compact": driver.COMPACT_TIMEOUT}
    ended = entry.setdefault("queue_idle_since", time.time())
    if time.time() - ended <= max(limits.get(action, driver.RELOAD_TIMEOUT) for action in entry["queued"]):
        return True
    entry.update(queued=[], detail="waiting_for_idle")
    entry.pop("queue_idle_since", None)
    return False


def line_workable(orca: Orca, entry: dict) -> bool:
    """True when the session's input line is empty or holds text that can be typed back exactly."""
    try:
        draft = orca.screen(entry["handle"])[1]
    except RefreshError:
        return False
    return not (isinstance(draft, str) and draft.strip()) or restorable_text(draft)


def unask(entry: dict) -> None:
    """Take back a question the ordinary pass raised for an entry whose user already answered `wait`."""
    entry.update(status="pending", detail="waiting_for_idle")
    for key in ("ask", "background", "asked_transcript", "input_unrestorable"):
        entry.pop(key, None)


def deadline_detail(entry: dict) -> str:
    """Why a pending entry ends `skipped` at the one-hour limit: its own reason unless it was only waiting for the session."""
    if entry.get("queued"):
        return "queued_unconfirmed"
    return "not_idle_before_deadline" if entry.get("detail") in (None, *WAITING_DETAILS) else entry["detail"]


def expire(entry: dict) -> None:
    """End a pending entry at its one-hour limit; a deferred Codex resume that failed a check goes to the approval list."""
    if entry["actions"][:1] == ["resume"] and entry.get("resume_check"):
        entry.update(status="skipped", detail="codex_plugin_folder_replaced", actions=[])
    else:
        entry.update(status="skipped", detail=deadline_detail(entry), actions=[])


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
    entry["actions"] = after_handoff_actions(entry, driver.read_marker(entry["handle"]), target)
    if not entry["actions"]:
        waiters.cancel(entry["handle"])
        entry.update(status="done", detail="applied_by_session" if entry.get("reloaded_by_session") else "already_current")


def follow_up(orca: Orca, entries: list[dict], state: dict, sleep: Callable[[float], None] = time.sleep, waiters: IdleWaiters | None = None,
              progress: Callable[[list[dict]], None] | None = None, lock: SendLock | None = None,
              incoming: Callable[[bool], list[dict]] | None = None, job: Callable[[SendLock], bool] | None = None,
              system: ProcessOs | None = None) -> None:
    """Apply deferred sessions when Orca reports them idle, each before its own deadline, then end every wait.

    `progress` receives the entries that reached a final status since its last call. `lock` is taken only to send
    to a session and kept until every command in flight is confirmed. `incoming(closing)` returns entries that
    joined meanwhile; they are added to `entries`, and a final-status entry of the same handle is replaced. `job` runs
    once per pass and returns True while its work is pending, which keeps the loop alive without any session.
    """
    waiters = waiters or IdleWaiters(orca)
    lock = lock or SendLock()
    cache: dict[str, tuple[float, bool]] = {}
    reported: set[str] = set()

    def report() -> None:
        finished = [entry for entry in entries if entry["status"] in FINAL_STATUSES and not entry.get("input_held") and entry["handle"] not in reported]
        for entry in finished[:]:
            if entry["status"] == "done" and entry.get("owes_continue") and not entry.get("continue_prompt"):
                if lock.acquire():
                    send_continue(orca, entry, sleep)
                else:
                    finished.remove(entry)
        if finished and progress:
            reported.update(entry["handle"] for entry in finished)
            progress(finished)

    def join(joined: list[dict]) -> bool:
        taken = False
        for new in joined:
            if any(entry["handle"] == new["handle"] and (entry["status"] in OPEN_STATUSES or entry.get("input_held")) for entry in entries):
                continue
            entries[:] = [entry for entry in entries if entry["handle"] != new["handle"]] + [new]
            reported.discard(new["handle"])
            taken = True
        return taken

    try:
        while True:
            if incoming:
                join(incoming(False))
            pending_job = bool(job and job(lock))
            active = [entry for entry in entries if entry["status"] in OPEN_STATUSES or entry.get("input_held")]
            if not active:
                if pending_job:
                    lock.release()
                    sleep(driver.POLL_SECONDS)
                    continue
                if incoming and join(incoming(True)):
                    continue
                if job and job(lock):
                    continue
                return
            try:
                live = {item.get("handle"): item for item in orca.terminals()}
            except RefreshError:
                live = None
            for entry in active:
                report()
                if entry.get("input_held") and not lock.acquire():
                    continue
                if release_held(orca, entry):
                    continue
                queue_now = False
                if entry["status"] == "pending":
                    if live is not None and terminal_gone(entry, live):
                        waiters.cancel(entry["handle"])
                        entry.update(status="skipped", detail="terminal_gone", actions=[])
                        continue
                    if time.time() >= entry["deadline"]:
                        expire(entry)
                        continue
                    if entry.get("queued") and (queued_progress(orca, entry, state, cache, lock) or entry["status"] != "pending"):
                        continue
                    applied_by_session(entry, state, cache, waiters)
                    if entry["status"] != "pending":
                        continue
                    if live is None:
                        entry["detail"] = "terminal_list_unavailable"
                        continue
                    handle = entry["handle"]
                    if handle not in waiters.failed and entry.get("detail") in WAITING_DETAILS:
                        needed = current_actions(entry, state)
                        record = host_record(entry, needed)
                        idle = waiters.take(handle)
                        queue_now = (record == "busy" and entry["host"] == "claude" and bool(entry.get("keep_unrestorable_input"))
                                     and line_workable(orca, entry))
                        if not queue_now:
                            if record in ("busy", "owing") or (record is None and idle is None):
                                waiters.start(handle, entry["deadline"])
                                entry["detail"] = "waiting_for_idle"
                                continue
                            if record is None and not idle:
                                continue
                            sleep(IDLE_CONFIRM_SECONDS)
                            if record == "idle" and host_record(entry, needed) != "idle":
                                continue
                    still_needed(entry, state, cache)
                    if entry["status"] != "pending":
                        continue
                    if time.time() >= entry["deadline"]:
                        expire(entry)
                        continue
                if not lock.acquire():
                    continue
                try:
                    if entry["status"] == "pending" and entry["actions"][:1] == ["resume"]:
                        resume_deferred(orca, entry, state, system, sleep)
                    else:
                        entry["queueable"] = queue_now
                        step(orca, entry, state["hosts"][entry["host"]], live)
                        if queue_now and entry["status"] == "awaiting_answer":
                            unask(entry)
                        elif queue_now and entry.get("queued") and entry["status"] == "deferred":
                            entry["status"] = "pending"
                except RefreshError as error:
                    entry.update(status="failed", detail=error.code, actions=[])
            if not sending(entries):
                lock.release()
            report()
            sleep(driver.POLL_SECONDS)
    finally:
        waiters.stop()
        lock.release()
