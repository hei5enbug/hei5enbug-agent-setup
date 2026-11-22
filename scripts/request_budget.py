"""Per-request counts of delegated runs and retries, their caps, and the parallel limit check for a launch.

One count per user request is kept in the approval state file of the session that received the prompt. The plugin
agent hook, the Codex agent hook, and the role runner all admit a launch through `admit`, so every layer adds to the
same count. A cap of 0 turns it off. The defaults come from `config/request-distribution.json`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import approval_state
import parallel_limit
import plugin_toggles
from approval_state_store import session_key

ROOT = Path(__file__).resolve().parents[1]
DISTRIBUTION_PATH = ROOT / "config" / "request-distribution.json"
RUN_CAP_KEY = "request_run_cap"
RETRY_CAP_KEY = "request_retry_cap"
CAP_MARKER = "Request cap reached"
LIMIT_MARKER = "Parallel limit reached"
ROLE_PREFIX = "role:"
HOSTS = ("claude", "codex")

CAP_MESSAGE = (
    CAP_MARKER + ": this request has {count} {what} and the cap `{option}` is {cap}, so this launch is denied. "
    "Start no further agent or role runner run for this request; work that is already running may finish. Report the "
    "request as stopped, with what is done and what remains, never as done. The next user prompt, or the next turn after this one ends, starts a new "
    "count, and the user can raise `{option}`."
)
LIMIT_MESSAGE = (
    LIMIT_MARKER + ": {running} agent runs are running on this machine and the parallel limit is {limit}. Do not poll. "
    "Start this run after one of this session's running runs ends."
)


def default_caps() -> dict[str, int]:
    """The shipped default of each cap from the committed distribution record; 0 when the record is unreadable."""
    try:
        record = json.loads(DISTRIBUTION_PATH.read_text(encoding="utf-8"))
        runs, retries = record["run_cap_default"], record["retry_cap_default"]
    except (OSError, ValueError, KeyError, TypeError):
        return {RUN_CAP_KEY: 0, RETRY_CAP_KEY: 0}
    return {RUN_CAP_KEY: runs if type(runs) is int and runs >= 0 else 0, RETRY_CAP_KEY: retries if type(retries) is int and retries >= 0 else 0}


def cap(key: str) -> int:
    """The cap an option sets: its digits, 0 for an off value, and the shipped default when it is unset or invalid."""
    text = os.environ.get(plugin_toggles.variable_name(key, plugin_toggles.detect_host()), "").strip().casefold()
    if text in plugin_toggles.OFF_VALUES:
        return 0
    return int(text) if text.isdigit() else default_caps()[key]


def identity(event_session: object = None) -> tuple[str, str] | None:
    """The host and session that received the user's prompt: the parent a role runner child names, else this session."""
    parent = approval_state.parent_session()
    if parent is not None:
        return parent
    key = session_key(event_session)
    return (plugin_toggles.detect_host(), key) if key else None


def identity_from_text(text: object) -> tuple[str, str] | None:
    """The identity of a `host:session` text such as the one a role runner passes to its children."""
    host, separator, session = text.partition(":") if isinstance(text, str) else ("", "", "")
    return (host, session) if separator and host in HOSTS and session_key(session) else None


def label(who: tuple[str, str]) -> str:
    return f"{who[0]}:{who[1]}"


def reset(who: tuple[str, str]) -> None:
    """Start a new request: counts begin at zero at the next user prompt and after each turn of the main session ends."""
    def change(data):
        data["request_budget"] = {"runs": 0, "retries": 0, "last": {}}
    approval_state._mutate(who[0], who[1], change)


def counts(who: tuple[str, str]) -> dict:
    return approval_state._load(who[0], who[1])["request_budget"]


def cap_denial(budget: dict, kind: str, run_cap: int, retry_cap: int) -> str | None:
    if run_cap and budget["runs"] >= run_cap:
        return CAP_MESSAGE.format(count=budget["runs"], what="delegated runs", option=RUN_CAP_KEY, cap=run_cap)
    if retry_cap and budget["last"].get(kind) == "error" and budget["retries"] >= retry_cap:
        return CAP_MESSAGE.format(count=budget["retries"], what="retries", option=RETRY_CAP_KEY, cap=retry_cap)
    return None


def admit(
    who: tuple[str, str], kind: str, run_id: str, *, background: bool = False, pid: int | None = None,
    limit: int | None = None, now: float | None = None, alive=parallel_limit.pid_alive,
) -> str | None:
    """Count a launch and register it as running, or return the denial message and change nothing.

    `kind` names the agent type, or `role:<role>` for a role runner run: the same kind launched after an error is a retry.
    Two launches at once are admitted one after the other, so the cap and the limit hold under a race.
    """
    run_cap, retry_cap = cap(RUN_CAP_KEY), cap(RETRY_CAP_KEY)
    moment = parallel_limit.now() if now is None else now
    with parallel_limit.locked() as path:
        entries = parallel_limit.live_entries(parallel_limit.read_entries(path), moment, alive)
        verdict: dict = {}

        def change(data):
            budget = data["request_budget"]
            reason = cap_denial(budget, kind, run_cap, retry_cap)
            if reason is None:
                allowed = parallel_limit.current_limit(who[0]) if limit is None else limit
                if parallel_limit.over_limit(entries, label(who), allowed):
                    reason = LIMIT_MESSAGE.format(running=len(entries), limit=allowed)
            if reason is None:
                budget["retries"] += 1 if budget["last"].get(kind) == "error" else 0
                budget["runs"] += 1
                budget["last"][kind] = "running"
            verdict["reason"] = reason

        approval_state._mutate(who[0], who[1], change)
        reason = verdict.get("reason")
        if reason is None and "reason" in verdict:
            entry = {"id": run_id, "session": label(who), "pid": pid if pid is not None else os.getpid(),
                     "started": moment, "kind": kind, "background": background}
            entries = parallel_limit.add_entry(entries, entry)
        parallel_limit.write_entries(path, entries)
    return reason


def finish(who: tuple[str, str], kind: str, run_id: str, *, ok: bool, background: bool = False) -> None:
    """Record how a launch ended and stop counting it as running; a background launch that started well keeps running."""
    def change(data):
        if data["request_budget"]["last"].get(kind) == "running":
            data["request_budget"]["last"][kind] = "ok" if ok else "error"
    approval_state._mutate(who[0], who[1], change)
    if ok and background:
        return
    with parallel_limit.locked() as path:
        parallel_limit.write_entries(path, parallel_limit.remove_entries(parallel_limit.read_entries(path), run_id=run_id))


def end_background(who: tuple[str, str], kind: str | None = None) -> None:
    """A subagent of this session stopped: stop counting its oldest background launch."""
    with parallel_limit.locked() as path:
        entries = parallel_limit.read_entries(path)
        parallel_limit.write_entries(path, parallel_limit.remove_entries(entries, session=label(who), kind=kind))
