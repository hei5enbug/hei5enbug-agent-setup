#!/usr/bin/env python3
"""Update hei5enbug-agent-setup and companion plugins, then apply installed versions to idle Orca agent sessions."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Callable, Sequence

sys.dont_write_bytecode = True
SCRIPTS_FOLDER = str(Path(__file__).resolve().parent)
if SCRIPTS_FOLDER not in sys.path:
    sys.path.insert(0, SCRIPTS_FOLDER)

import refresh_core as core  # noqa: E402
import refresh_install as installs  # noqa: E402
import refresh_sessions as driver  # noqa: E402
from refresh_claude_update import attach_claude_update, run_claude_update  # noqa: E402
from refresh_codex_release import cached_root, install_time, prepare_marketplaces, verify_files, verify_hook  # noqa: E402
from refresh_core import (  # noqa: E402
    CODEX_HOOK_TRUST, HANDLE, HOSTS, MARKETPLACE, PLUGIN, PLUGIN_ID, PLUGIN_ROOT, RUN_ID, SESSION_CONTEXT, RefreshError,
    exclusive, executable, load_plugin_script, load_run, now, parse_time, run, run_json, run_path, save_json, state_root, update_run,
)
from refresh_feed import RunFeed  # noqa: E402
from refresh_follow import (  # noqa: E402
    IDLE_CONFIRM_SECONDS, INSTALL_CHECK_SECONDS, IdleWaiters, SendLock, follow_up, install_current, still_needed,
)
from refresh_install import (  # noqa: E402
    BUNDLE_SKIPPED_DIRS, CODEX_IDLE_EVENTS, CODEX_TURN_ENV, DEFAULT_HOOKS, HOME_RECORD_WARNING, HOOK_LAUNCHER, HOOK_ROOT, HOOKS_TRUST_WARNING,
    LAUNCHED_SCRIPT, REQUIRED_HOOK_TARGETS, REQUIRED_HOOKS, ROLLOUT_RECENT_SECONDS, ROLLOUT_TAIL_BYTES, bundle_digest,
    check_hooks, codex_home, codex_trust_reset, hook_file_entries, hooks_digest, inside, install_gate, installed,
    read_hook_file, read_manifest, rollout_idle, run_install, scan_hook_events, validate_claude_mod, validate_install,
)
import refresh_codex_job as codex_job  # noqa: E402
from refresh_answers import checked_codex_answers, decided_entry, parse_answers  # noqa: E402
from refresh_handoff import add_questions, alive, follow_item, hand_to_helper, handled, handoff_point, public  # noqa: E402
from refresh_trust import CODEX_TRUST_TIMEOUT_SECONDS, settle_companion_trust, trust_codex_hooks  # noqa: E402
from refresh_codex_session import gate_sessions  # noqa: E402
from refresh_orca import LazyOrca, Orca  # noqa: E402
from refresh_orphans import run_close, run_orphans  # noqa: E402
from refresh_interrupt import interrupt_apply, send_continue  # noqa: E402
from refresh_manual import ACTIONS as MANUAL_ACTIONS, RESULTS as MANUAL_RESULTS, run_record_manual  # noqa: E402
from refresh_questions import CHOICES, CODEX_INSTALL, codex_question_record, question_record, question_view  # noqa: E402
from refresh_process import ProcessOs  # noqa: E402
from refresh_resume import resume_outdated, run_resume  # noqa: E402
from refresh_plugins import (  # noqa: E402
    COMPANION_ENV, COMPANION_ID, COMPANION_LIMIT, claude_marketplace, companion_entries, companion_ids, describe_plugin,
    folder_version, local_source, refresh_companion, validate_companion,
)
from refresh_screen import (  # noqa: E402
    CLAUDE_PLACEHOLDER, CODEX_FOOTER, CODEX_PLACEHOLDERS, CODEX_STARTING, SEPARATOR, TITLED_SEPARATOR, codex_fresh,
    composer_bounds, input_state, opening_rule, screen_host,
)
from refresh_sessions import (  # noqa: E402
    BACKSPACE, CLAUDE_COMPACT_ERROR, CLAUDE_COMPACTED, CLAUDE_NOTHING_TO_COMPACT, CLEAR_TIMEOUT, CODEX_COMPACTED,
    COMMAND_RECORD_PREFIXES, COMMANDS, COMPACT_TIMEOUT, DRAFT_STABLE_SECONDS, FINAL_STATUSES, POLL_SECONDS, PROBE_KEY,
    PROBE_RECHECK_SECONDS, PROBE_RETRIES, RELOAD_DONE, RELOAD_REFUSED, RELOAD_TIMEOUT, TRANSCRIPT_TAIL_BYTES, agent_host,
    claude_draft_state, claude_has_prompts, compact_reason, drive, finish, last_item_is, marker_host, newer_marker,
    plan_sessions, probe_left_input_clean, read_marker, ready, result_counts, settle, step, terminal_gone, terminal_host,
    transcript_outcome, transcript_records, transcript_size, verify,
)
from refresh_sessions import HELD_INPUT, OPEN_STATUSES, host_record, release_held  # noqa: E402

RUNTIME_PATHS = ("skills", "instructions", "scripts", "hooks", "config", "agents", "standalone-agents", ".claude-plugin", ".codex-plugin")
SELF_WAIT_SECONDS = 60 * 60
NOTIFY_SECONDS = 120
DEFAULT_APPLY_SECONDS = 20
FOLLOW_UP_SECONDS = 60 * 60


def recovery_command(root: str | None, companions: Sequence[str] = ()) -> str:
    current = Path(__file__).resolve()
    try:
        relative = current.relative_to(PLUGIN_ROOT)
    except ValueError:
        relative = current.name
    candidate = Path(root) / relative if root else current
    script = current if current.is_file() else candidate if candidate.is_file() else current
    also = "".join(f" --also {shlex.quote(plugin_id)}" for plugin_id in companions)
    return f"python3 {shlex.quote(str(script))} update{also} --json"


def claude_unreleased_changes() -> tuple[list[str], str | None]:
    """Runtime files the Claude marketplace has but a same-version install cannot pick up, or why that is unknown."""
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    try:
        record = json.loads((config / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
        installed_sha = record["plugins"][PLUGIN_ID][0]["gitCommitSha"]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return [], "installed commit is not recorded"
    try:
        marketplaces = run_json([core.executable("claude"), "plugin", "marketplace", "list", "--json"])
    except RefreshError as error:
        return [], error.message
    entries = [item for item in marketplaces if isinstance(item, dict) and item.get("name") == MARKETPLACE] if isinstance(marketplaces, list) else []
    if len(entries) != 1 or not isinstance(entries[0].get("installLocation"), str):
        return [], "the marketplace clone is not listed"
    clone = entries[0]["installLocation"]
    head = core.run([core.executable("git"), "-C", clone, "rev-parse", "HEAD"], check=False)
    if head.returncode != 0 or not head.stdout.strip():
        return [], "the marketplace revision is unreadable"
    if head.stdout.strip() == installed_sha:
        return [], None
    diff = core.run([core.executable("git"), "-C", clone, "diff", "--name-only", installed_sha, head.stdout.strip(), "--", *RUNTIME_PATHS], check=False)
    if diff.returncode != 0:
        return [], "the installed commit is not in the marketplace clone"
    return [line for line in diff.stdout.splitlines() if line.strip()], None


def update_host(host: str, context: dict | None = None) -> dict:
    context = {} if context is None else context
    before = installs.installed(host)
    before_snapshot = validate_install(host, before)
    saved = context.get("codex_before", {}).get(PLUGIN_ID) if host == "codex" else None
    if saved:
        before = {**before, "root": saved["root"], "version": saved["version"]}
        before_snapshot = {**before_snapshot, "digest": saved.get("digest"), "hooks": saved["hooks"]}
    local = local_source(host, PLUGIN_ID, before.get("item"), context)
    merged = [dict(HOME_RECORD_WARNING)] if before.get("home_project_record") else []
    if local:
        version = local["version"] or before["version"]
        result = {
            "before_version": version,
            "after_version": version,
            "root": before["root"],
            "previous_root": before["root"],
            "digest": before_snapshot["digest"],
            "instructions_changed": False,
            "warnings": merged,
            "local_source": True,
        }
        if local.get("note"):
            result["note"] = local["note"]
        return result
    before_bundle = saved["bundle"] if saved else bundle_digest(Path(before["root"])) if host == "codex" else None
    blocked = run_install(host, PLUGIN_ID, context)
    if blocked:
        blocked.details.update(root=before["root"], recovery_command=recovery_command(before["root"], context.get("ids", ())))
        raise blocked
    after = installs.installed(host)
    after_snapshot = validate_install(host, after)
    result = {
        "before_version": before["version"],
        "after_version": after["version"],
        "root": after["root"],
        "previous_root": before["root"],
        "digest": after_snapshot["digest"],
        "instructions_changed": before_snapshot["digest"] != after_snapshot["digest"],
        **({"installed_at": install_time(Path(after["root"]))} if host == "codex" else {}),
        "warnings": [dict(HOME_RECORD_WARNING)] if before.get("home_project_record") or after.get("home_project_record") else [],
    }
    if host == "claude":
        pending, unknown = claude_unreleased_changes()
        if unknown:
            result["warnings"].append(
                {"code": "unreleased_check_unavailable", "message": f"Could not check whether Claude Code missed same-version files: {unknown}."}
            )
        elif pending and before["version"] == after["version"]:
            result["warnings"].append(
                {"code": "unreleased_same_version", "message": "Claude Code keeps the installed copy because the version did not change; bump the version to release these files.", "files": pending[:20]}
            )
    if host == "codex" and (MARKETPLACE in context.get("release_pins", {}) or
                            codex_trust_reset(before_snapshot["hooks"], after_snapshot["hooks"], before_bundle,
                                              bundle_digest(Path(after["root"])))):
        reason = trust_codex_hooks()
        if reason is None:
            result["codex_hooks_trusted"] = True
        else:
            result["warnings"].append({**HOOKS_TRUST_WARNING, "detail": reason})
    return result


def host_failure(error: RefreshError) -> dict:
    entry = {"error": {"code": error.code, "message": error.message}}
    for key in ("root", "recovery_command"):
        if key in error.details:
            entry[key] = error.details[key]
    return entry


def refresh_report(run_id: str, hosts: dict[str, dict], extra: dict, questions: Sequence[dict] = (), codex_ids: Sequence[str] = ()) -> dict:
    saved = {"run_id": run_id, "created_at": now(), "hosts": hosts, "sessions": {}}
    if questions:
        saved.update(questions={item["id"]: item for item in questions}, question_seq=len(questions),
                     codex_install={"status": "asked", "ids": list(codex_ids)})
    save_json(run_path(run_id), saved)
    failed = any("error" in value or any(item["status"] == "error" for item in value["plugins"]) for value in hosts.values())
    asked = {"questions": [question_view(item) for item in questions]} if questions else {}
    return {"ok": not failed, "run_id": run_id, "script": continuation_script(hosts), "hosts": hosts, **extra, **asked}


def update_host_entry(host: str, ids: Sequence[str], ignore_env: bool = False) -> tuple[dict, RefreshError | None]:
    """One host's update with its companions as a result entry, and the install gate that held an install back, if any.

    `ignore_env` skips the check of the caller's own Codex turn, for the detached helper that runs the install later."""
    context: dict = {"ids": ids, **({"ignore_env": True} if ignore_env else {})}

    def gate() -> RefreshError | None:
        return installs.install_gate(host, ignore_env=True) if ignore_env else installs.install_gate(host)

    try:
        if host == "codex":
            held = gate()
            prepare_marketplaces([PLUGIN_ID, *ids], context, advance=held is None)
            held = held or gate()
            blocked = held if context["release_pins"] or context["release_errors"] else None
            if blocked:
                root = cached_root(PLUGIN_ID)
                blocked.details.update(root=root, recovery_command=recovery_command(root, ids))
                entry = host_failure(blocked)
                entry["plugins"] = [{"plugin": plugin_id, "status": "deferred", "code": blocked.code,
                                     "message": blocked.message, "before_version": None, "after_version": None,
                                     "warnings": []} for plugin_id in ids]
                return entry, blocked
        entry = update_host(host, context)
    except RefreshError as error:
        entry = host_failure(error)
    except (OSError, ValueError):
        entry = host_failure(RefreshError("plugin_check_failed", f"A {host} plugin file could not be checked."))
    if host == "codex" and "release_pins" not in context:
        entry["plugins"] = [{"plugin": plugin_id, "status": "error", "code": "codex_config_unreadable",
                             "message": "Release refs could not be prepared; no Codex command ran.",
                             "before_version": None, "after_version": None, "warnings": []} for plugin_id in ids]
        return entry, context.get("blocked")
    plugins = [refresh_companion(host, plugin_id, True, context) for plugin_id in ids]
    entry["plugins"] = settle_companion_trust(plugins, context)
    return entry, context.get("blocked")


def codex_questions(gate: RefreshError | None) -> list[dict]:
    """One `codex_install` question for each busy Codex session an install gate names; ids continue from q1."""
    if gate is None or gate.code not in {"codex_turn_in_progress", "update_deferred_active_session"}:
        return []
    return [codex_question_record(f"q{number}", session) for number, session in enumerate(gate_sessions(gate), 1)]


def command_update(also: Sequence[str] = ()) -> dict:
    ids, extra = companion_ids(also)
    run_id = uuid.uuid4().hex
    claude_step = run_claude_update()
    hosts: dict[str, dict] = {}
    gate = None
    for host in HOSTS:
        hosts[host], held = update_host_entry(host, ids)
        gate = held if host == "codex" else gate
    return refresh_report(run_id, attach_claude_update(hosts, claude_step), extra, codex_questions(gate), ids)


def command_apply_installed(also: Sequence[str] = ()) -> dict:
    ids, extra = companion_ids(also)
    run_id = uuid.uuid4().hex
    claude_step = run_claude_update()
    hosts: dict[str, dict] = {}
    for host in HOSTS:
        context: dict = {}
        try:
            current = installs.installed(host)
            current_snapshot = validate_install(host, current)
            hosts[host] = {
                "before_version": current["version"],
                "after_version": current["version"],
                "root": current["root"],
                "previous_root": PLUGIN_ROOT.as_posix(),
                "digest": current_snapshot["digest"],
                "instructions_changed": False,
                "warnings": [dict(HOME_RECORD_WARNING)] if current.get("home_project_record") else [],
                **({"installed_at": install_time(Path(current["root"]))} if host == "codex" else {}),
            }
        except RefreshError as error:
            hosts[host] = host_failure(error)
        except (OSError, ValueError):
            hosts[host] = host_failure(RefreshError("plugin_check_failed", f"A {host} plugin file could not be checked."))
        hosts[host]["plugins"] = [refresh_companion(host, plugin_id, False, context) for plugin_id in ids]
    return refresh_report(run_id, attach_claude_update(hosts, claude_step), extra)


def continuation_script(hosts: dict[str, dict]) -> str:
    """The copy of this script that later commands must use; a Codex update deletes the invoking installation."""
    here = Path(__file__).resolve()
    for result in hosts.values():
        previous, root = result.get("previous_root"), result.get("root")
        if isinstance(previous, str) and isinstance(root, str) and here.is_relative_to(Path(previous)):
            candidate = Path(root) / here.relative_to(Path(previous))
            if candidate.is_file():
                return str(candidate)
    return str(here)


def spawn_self_apply(run_id: str) -> int:
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "self-apply", "--run-id", run_id],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
        cwd=state_root(),
    )
    return process.pid


def command_plan(run_id: str, mode: str, only: Sequence[str]) -> dict:
    state = load_run(run_id)
    sessions = plan_sessions(Orca(), state, mode, only)
    return {"ok": True, "run_id": run_id, "sessions": [public(entry) for entry in sessions]}


def commit_apply(run_id: str, mode: str, sessions: list[dict], others: list[dict], spawn: Callable[[str], int]) -> list[dict]:
    """Record this apply and hand its deferred sessions to the live helper or a new one, on the run state read afresh under its lock.

    Returns the questions this apply saved for sessions that wait for the user's answer."""
    own = next((entry for entry in sessions if entry["initiator"] and entry["status"] == "pending"), None)
    deferred = [entry for entry in others if entry["status"] == "deferred"]
    initiator = next((entry for entry in sessions if entry["initiator"]), None)
    handed = time.time()
    created: list[dict] = []

    def change(state: dict) -> dict:
        state["initiator"] = ({key: initiator.get(key) for key in ("handle", "host", "screen_identified")}
                              if initiator else None)
        state["compact_mode"] = mode
        if own or deferred:
            items = [follow_item(entry, mode, handed) for entry in deferred]
            handed_off, pid = hand_to_helper(state, run_id, items, spawn, own is not None)
            if not handed_off:
                if own:
                    own.update(status="failed", detail="helper_start_failed", actions=[])
                for entry in deferred:
                    entry.update(status="skipped", detail="helper_start_failed", actions=[])
            if handed_off and own:
                own.update(status="queued_after_turn", detail="waits_for_this_turn_to_end")
                state["self"] = {key: own.get(key) for key in ("handle", "host", "actions", "title", "worktree", "screen_identified")}
                state["self"].update(compact_reason=own.get("compact_reason"), compact_mode=mode, helper_pid=pid, helper_started_at=now(), deferred_at=handed,
                                   **handoff_point(own["handle"]))
                state.pop("self_finished_at", None)
        created[:] = add_questions(state, sessions)
        state["sessions"] = {**state.get("sessions", {}), **{entry["handle"]: public(entry) for entry in sessions if not entry.get("handled")}}
        state["applied_at"] = now()
        return state

    update_run(run_id, change)
    return created


def command_apply(run_id: str, mode: str, only: Sequence[str], seconds: int, spawn: Callable[[str], int] = spawn_self_apply,
                  system: ProcessOs | None = None, sleep: Callable[[float], None] = time.sleep) -> dict:
    with exclusive("sessions"):
        state = load_run(run_id)
        orca = Orca()
        sessions = plan_sessions(orca, state, mode, only)
        for entry in sessions:
            previous = handled(state, entry["handle"])
            if previous:
                entry.update(status=previous, detail="skipped_by_user" if previous == "skipped" else "already_handled_in_this_run", actions=[], handled=True)
        others = [entry for entry in sessions if not entry["initiator"] and not entry.get("handled")]
        for entry in others:
            entry["queueable"] = entry["host"] == "claude"
        resume_outdated(orca, others, state, run_id, system, sleep)
        drive(orca, others, state, time.time() + seconds, sleep, expire="deferred")
        questions = commit_apply(run_id, mode, sessions, others, spawn)
    summary = {status: sum(1 for entry in sessions if entry["status"] == status) for status in {entry["status"] for entry in sessions}}
    return {"ok": all(entry["status"] in {"done", "queued_after_turn", "deferred", "awaiting_answer"} or entry.get("detail") == "skipped_by_user"
                      for entry in sessions), "run_id": run_id,
            "summary": summary, "sessions": [public(entry) for entry in sessions], "questions": [question_view(item) for item in questions]}


def apply_codex_sessions(run_id: str, orca: Orca, interrupted: set[str], spawn: Callable[[str], int], system: ProcessOs | None,
                         sleep: Callable[[float], None]) -> None:
    """After the Codex install: resume the Codex sessions on replaced folders, the session that ran the skill included, apply
    to the other Codex sessions as `apply` does, and ask each interrupted session to continue. A busy session goes to the helper."""
    state = load_run(run_id)
    mode, handed = state.get("compact_mode", "auto"), time.time()
    sessions = [entry for entry in plan_sessions(orca, state, mode, []) if entry["host"] == "codex"]
    for entry in sessions:
        entry["initiator"] = False
    resume_outdated(orca, sessions, state, run_id, system, sleep)
    drive(orca, sessions, state, time.time() + DEFAULT_APPLY_SECONDS, sleep, expire="deferred")
    for entry in sessions:
        if entry["handle"] in interrupted:
            if entry["status"] == "done":
                send_continue(orca, entry, sleep)
            else:
                entry["continue_prompt"] = f"not_sent:{entry['status']}"

    def change(saved: dict) -> dict:
        deferred = [entry for entry in sessions if entry["status"] == "deferred"]
        if deferred:
            handed_off, _ = hand_to_helper(saved, run_id, [follow_item(entry, mode, handed) for entry in deferred], spawn, bool(saved.get("self")))
            if not handed_off:
                for entry in deferred:
                    entry.update(status="skipped", detail="helper_start_failed", actions=[])
        saved["sessions"] = {**saved.get("sessions", {}), **{entry["handle"]: public(entry) for entry in sessions}}
        return saved

    update_run(run_id, change)


def codex_tick(run_id: str, orca: Orca, acquire: Callable[[], bool], sleep: Callable[[float], None], system: ProcessOs | None,
               spawn: Callable[[str], int], ignore_env: bool) -> bool:
    """One pass of the Codex install job saved in the run state; True while it is pending.

    The job waits until every session answered `wait` has ended its turn, presses Esc once in each session answered
    `interrupt` that is still busy, then takes the lock, rechecks the gate, and installs the way `update` does. It saves
    the new script path, resumes the Codex sessions on replaced folders, and sends the continue prompt to the interrupted
    sessions only. At its deadline it installs nothing. `acquire` takes the lock that covers sending to sessions."""
    job = codex_job.job_of(run_id)
    if job.get("status") != "pending":
        return False
    if time.time() >= job["deadline"]:
        codex_job.change_job(run_id, status="not_idle_before_deadline")
        return False
    if codex_job.waiting_on(job):
        return True
    if any(item["state"] in {"queued", "esc_sent"} for item in job["interrupts"]):
        if not acquire():
            return True
        codex_job.interrupt_all(orca, run_id, sleep)
        job = codex_job.job_of(run_id)
        if codex_job.waiting_on(job):
            return True
    gate = installs.install_gate("codex", ignore_env=True) if ignore_env else installs.install_gate("codex")
    if gate:
        if job.get("detail") != gate.code:
            codex_job.change_job(run_id, detail=gate.code)
        return True
    if not acquire():
        return True
    if codex_job.claim(run_id) != "claimed":
        return False
    try:
        entry, blocked = update_host_entry("codex", job.get("ids", []), ignore_env)
    except BaseException:
        codex_job.change_job(run_id, status="pending")
        raise
    if blocked:
        codex_job.change_job(run_id, status="pending", detail=blocked.code)
        return True

    failure = (entry.get("error") or {}).get("code") or next((item.get("code") or "plugin_error" for item in entry.get("plugins", [])
                                                              if item["status"] == "error"), None)

    def installed(saved: dict) -> dict:
        saved["hosts"]["codex"] = entry
        saved["script"] = continuation_script(saved["hosts"])
        saved["codex_install"] = {**saved["codex_install"], "status": "failed" if failure else "done", "finished_at": now(),
                                  **({"detail": failure} if failure else {})}
        return saved

    update_run(run_id, installed)
    if "error" not in entry:
        apply_codex_sessions(run_id, orca, {item["handle"] for item in job["interrupts"] if item["state"] == "interrupted"}, spawn, system, sleep)
    return False


def hand_codex_job(run_id: str, spawn: Callable[[str], int]) -> None:
    """Give the pending Codex install job to the live helper or a new one; a helper that fails to start fails the job."""
    def change(saved: dict) -> dict:
        handed_off, _ = hand_to_helper(saved, run_id, [], spawn, bool(saved.get("self")))
        if not handed_off:
            saved["codex_install"].update(status="failed", detail="helper_start_failed")
        return saved

    update_run(run_id, change)


def decide_codex(run_id: str, known: dict, parsed: list[tuple[str, str]], orca: Orca, spawn: Callable[[str], int],
                 system: ProcessOs | None, sleep: Callable[[float], None]) -> None:
    """Resolve every Codex answer of the run together. Any `skip` means no Codex update. Otherwise the install job is saved
    in the run state: with a `wait` answer the detached helper carries it, with only `interrupt` answers it runs here."""
    choices = dict(parsed)
    skipped = "skip" in choices.values()
    waits = [known[question_id]["rollout"] for question_id, choice in parsed if choice == "wait" and known[question_id].get("rollout")]
    interrupts = [{"handle": known[question_id]["handle"], "rollout": known[question_id].get("rollout"), "state": "queued"}
                  for question_id, choice in parsed if choice == "interrupt"]

    def change(saved: dict) -> dict:
        for question_id, choice in parsed:
            saved["questions"][question_id].update(answer=choice, answered_at=now())
        base = saved.get("codex_install") or {}
        if skipped:
            saved["codex_install"] = {**base, "status": "skipped_by_user", "answers": choices}
            saved.get("hosts", {}).get("codex", {})["decision"] = "skip"
            return saved
        saved["codex_install"] = {**base, "status": "pending", "answers": choices, "requested_at": now(),
                                  "deadline": time.time() + FOLLOW_UP_SECONDS, "waits": waits, "interrupts": interrupts}
        if "wait" in choices.values():
            handed_off, _ = hand_to_helper(saved, run_id, [], spawn, bool(saved.get("self")))
            if not handed_off:
                saved["codex_install"].update(status="failed", detail="helper_start_failed")
        return saved

    state = update_run(run_id, change)
    if codex_job.pending(state) and "wait" not in choices.values() and codex_tick(run_id, orca, lambda: True, sleep, system, spawn, False):
        hand_codex_job(run_id, spawn)


def command_decide(run_id: str, answers: Sequence[str], spawn: Callable[[str], int] = spawn_self_apply, system: ProcessOs | None = None,
                   sleep: Callable[[float], None] = time.sleep) -> dict:
    """Carry out the user's answers to the questions of one run: `wait` hands the session to the helper, `skip` sends
    nothing, and `interrupt` presses Esc once and applies. Each question takes one answer. The answers to the Codex install
    questions are resolved together."""
    parsed = parse_answers(answers)
    with exclusive("sessions"):
        state = load_run(run_id)
        known = state.get("questions", {})
        if len({question_id for question_id, _ in parsed}) != len(parsed) or any(
                question_id not in known or (known[question_id].get("answer") or choice) != choice for question_id, choice in parsed):
            raise RefreshError("question_unknown", "An answer names a question that this run did not ask or that is already answered with another choice.")
        repeated = [(question_id, choice) for question_id, choice in parsed if known[question_id].get("answer")]
        parsed = [item for item in parsed if item not in repeated]
        codex = [(question_id, choice) for question_id, choice in parsed if known[question_id].get("reason") == CODEX_INSTALL]
        parsed = [item for item in parsed if item not in codex]
        if codex:
            checked_codex_answers(known, codex)
        orca = LazyOrca(lambda: Orca())
        entries = []
        mode, handed = state.get("compact_mode", "auto"), time.time()

        def save(question_id: str, choice: str, entry: dict) -> None:
            def change(saved: dict) -> dict:
                saved["questions"][question_id].update(answer=choice, answered_at=now())
                if entry["status"] == "deferred":
                    handed_off, _ = hand_to_helper(saved, run_id, [follow_item(entry, mode, handed)], spawn, bool(saved.get("self")))
                    if not handed_off:
                        entry.update(status="skipped", detail="helper_start_failed", actions=[])
                saved["sessions"] = {**saved.get("sessions", {}), entry["handle"]: public(entry)}
                return saved

            update_run(run_id, change)

        for question_id, choice in parsed:
            entries.append(decided_entry(orca, state, known[question_id], choice, system, sleep))
            save(question_id, choice, entries[-1])
        if codex:
            decide_codex(run_id, known, codex, orca, spawn, system, sleep)
    output = {"ok": all(entry["status"] in {"done", "deferred"} or entry.get("detail") == "skipped_by_user" for entry in entries), "run_id": run_id,
              "sessions": [public(entry) for entry in entries],
              "questions": [question_view({**known[question_id], "answer": choice}) for question_id, choice in [*repeated, *parsed, *codex]]}
    if codex:
        saved = load_run(run_id)
        job = saved.get("codex_install") or {}
        output.update(codex_install=codex_job.job_view(job), **({"script": saved["script"]} if saved.get("script") else {}))
        output["ok"] = output["ok"] and job.get("status") in {"pending", "done", "skipped_by_user"}
    return output


def error_result(error: RefreshError) -> dict:
    return {"ok": False, "error": {"code": error.code, "message": error.message}}


def command_refresh(also: Sequence[str], installed: bool, mode: str) -> dict:
    """One update (or apply-installed), then apply and orphans on its run id; apply and orphans never run when every host failed."""
    update = command_apply_installed(also) if installed else command_update(also)
    output: dict = {"ok": update["ok"], "update": update}
    if all("error" in host for host in update["hosts"].values()):
        if update.get("questions"):
            output["questions"] = update["questions"]
        return output
    for name, step in (("apply", lambda: command_apply(update["run_id"], mode, [], DEFAULT_APPLY_SECONDS)),
                       ("orphans", lambda: run_orphans(update["run_id"]))):
        try:
            output[name] = step()
        except RefreshError as error:
            output[name] = error_result(error)
    output["ok"] = update["ok"] and output["apply"]["ok"]
    output["questions"] = [*update.get("questions", []), *output["apply"].get("questions", [])]
    return output


def lock_guard() -> AbstractContextManager:
    return exclusive("sessions")


def notify(orca: Orca, entry: dict, run_id: str, sleep: Callable[[float], None], guard: Callable[[], AbstractContextManager] = nullcontext) -> str:
    try:
        script = load_run(run_id).get("script")
    except RefreshError:
        script = None
    message = f"Plugin refresh run {run_id} finished. Run `{status_command(run_id, script)}` and report every session, including any that were not refreshed."
    notice = {"handle": entry["handle"], "host": entry["host"], "screen_identified": entry.get("screen_identified")}
    deadline = time.time() + NOTIFY_SECONDS
    reason: str | None = "not_attempted"
    while time.time() < deadline:
        try:
            with guard():
                live = {item.get("handle"): item for item in orca.terminals()}
                reason, _ = driver.ready(orca, notice, live)
                if reason is None and (entry["host"] != "claude" or orca.draft(entry["handle"]) == notice.get("observed_draft")):
                    record = driver.host_record(notice)
                    if record != "busy" and (record is not None or orca.idle(entry["handle"])):
                        orca.send(entry["handle"], message)
                        return "sent"
                    reason = "turn_started"
            if reason in {"terminal_gone", "probe_interrupted", "unsent_input"}:
                break
        except RefreshError as error:
            reason = error.code
        sleep(driver.POLL_SECONDS)
    return f"not_sent:{reason}"


def command_self_apply(run_id: str, sleep: Callable[[float], None] = time.sleep, waiters: IdleWaiters | None = None,
                       system: ProcessOs | None = None) -> int:
    """The one detached helper: finish deferred sessions, a pending Codex install, and this session, then send one result notice and exit.

    It holds the sessions lock only while sending to a session and confirming it, and reads the run state again on
    every pass so sessions that a later `apply` hands over join this helper.
    """
    feed = RunFeed(run_id, FOLLOW_UP_SECONDS, SELF_WAIT_SECONDS)
    with exclusive("run-state", wait_seconds=core.RUN_STATE_WAIT_SECONDS):
        entries = feed.poll()
    state = load_run(run_id)
    if not entries and not codex_job.pending(state):
        return 0
    orca = Orca()
    guard = SendLock(lock_guard)

    def record(finished: list[dict]) -> None:
        def change(saved: dict) -> dict:
            views = {entry["handle"]: public(entry) for entry in finished}
            sessions = saved.setdefault("sessions", {})
            changed = any(sessions.get(handle) != view for handle, view in views.items())
            sessions.update(views)
            if any(entry["initiator"] for entry in entries) and not saved.get("others_finished_at") and all(
                    entry["status"] in FINAL_STATUSES and not entry.get("input_held") for entry in entries if not entry["initiator"]):
                saved["others_finished_at"] = now()
                changed = True
            return saved if changed else None

        try:
            update_run(run_id, change)
        except (RefreshError, OSError):
            pass

    record([])
    def job(lock: SendLock) -> bool:
        waiting = codex_tick(run_id, orca, lock.acquire, sleep, system, spawn_self_apply, True)
        if not waiting:
            state["hosts"] = load_run(run_id).get("hosts", state["hosts"])
        return waiting

    follow_up(orca, entries, state, sleep=sleep, waiters=waiters, progress=record, lock=guard, system=system,
              incoming=lambda closing: feed.close(codex_job.pending) if closing else feed.poll(), job=job)
    own_entry = next((entry for entry in entries if entry["initiator"]), None)
    finished = now()

    def conclude(saved: dict) -> dict:
        for entry in entries:
            saved.setdefault("sessions", {})[entry["handle"]] = public(entry)
        if own_entry and (saved.get("self") or {}).get("deferred_at") == own_entry.get("deferred_at"):
            saved["self_finished_at"] = finished
        saved["self_notification"] = "pending"
        return saved

    state = update_run(run_id, conclude)
    if own_entry:
        notification = notify(orca, own_entry, run_id, sleep, lock_guard) if own_entry["status"] in {"done", "failed"} else "not_sent:session_skipped"
    elif isinstance(state.get("initiator"), dict):
        notification = notify(orca, dict(state["initiator"]), run_id, sleep, lock_guard)
    else:
        notification = "not_sent:no_orca_initiator"
    update_run(run_id, lambda saved: {**saved, "self_notification": notification})
    return 0


def status_command(run_id: str, script: str | None = None) -> str:
    """The status command line; `script` is the saved copy that a Codex install left in place of the deleted one."""
    prefix = f"XDG_STATE_HOME={shlex.quote(os.environ['XDG_STATE_HOME'])} " if os.environ.get("XDG_STATE_HOME") else ""
    return f"{prefix}python3 {shlex.quote(script or str(Path(__file__).resolve()))} status --run-id {run_id} --json"


def command_status(run_id: str) -> dict:
    state = load_run(run_id)
    return {
        "ok": True,
        "run_id": run_id,
        "hosts": state.get("hosts"),
        "sessions": list(state.get("sessions", {}).values()),
        "resumed": list(state.get("resumed", {}).values()),
        "not_refreshed": [item for item in state.get("sessions", {}).values() if item.get("status") in {"skipped", "failed", "blocked"}],
        "questions": [question_view(item) for item in state.get("questions", {}).values()],
        "unanswered": sum(1 for item in state.get("questions", {}).values() if not item.get("answer")),
        **({"codex_install": codex_job.job_view(state["codex_install"])} if state.get("codex_install") else {}),
        **({"script": state["script"]} if state.get("script") else {}),
        "helper_finished_at": state.get("helper_finished_at"),
        "self_finished_at": state.get("self_finished_at"),
        "others_finished_at": state.get("others_finished_at"),
        "self_notification": state.get("self_notification"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("update", "apply-installed"):
        sub = commands.add_parser(name)
        sub.add_argument("--also", action="append", default=[], metavar="PLUGIN@MARKETPLACE")
        sub.add_argument("--json", action="store_true")
    refresh = commands.add_parser("refresh")
    refresh.add_argument("--also", action="append", default=[], metavar="PLUGIN@MARKETPLACE")
    refresh.add_argument("--installed", action="store_true")
    refresh.add_argument("--compact", choices=("auto", "always", "never"), default="auto")
    refresh.add_argument("--json", action="store_true")
    for name in ("plan", "apply"):
        sub = commands.add_parser(name)
        sub.add_argument("--run-id", required=True)
        sub.add_argument("--compact", choices=("auto", "always", "never"), default="auto")
        sub.add_argument("--terminal", action="append", default=[])
        sub.add_argument("--json", action="store_true")
        if name == "apply":
            sub.add_argument("--timeout-seconds", type=int, default=DEFAULT_APPLY_SECONDS)
    commands.add_parser("self-apply").add_argument("--run-id", required=True)
    decide = commands.add_parser("decide")
    decide.add_argument("--run-id", required=True)
    decide.add_argument("--answer", action="append", required=True, metavar="QUESTION=wait|interrupt|skip")
    decide.add_argument("--json", action="store_true")
    resume = commands.add_parser("resume")
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--terminal", action="append", required=True)
    resume.add_argument("--json", action="store_true")
    orphans = commands.add_parser("orphans")
    orphans.add_argument("--run-id", required=True)
    orphans.add_argument("--json", action="store_true")
    close = commands.add_parser("close")
    close.add_argument("--run-id", required=True)
    close.add_argument("--terminal", action="append", required=True)
    close.add_argument("--json", action="store_true")
    manual = commands.add_parser("record-manual")
    manual.add_argument("--run-id", required=True)
    manual.add_argument("--terminal", required=True)
    manual.add_argument("--action", required=True, choices=MANUAL_ACTIONS)
    manual.add_argument("--result", required=True, choices=MANUAL_RESULTS)
    manual.add_argument("--detail")
    manual.add_argument("--json", action="store_true")
    status = commands.add_parser("status")
    status.add_argument("--run-id", required=True)
    status.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "self-apply":
            return command_self_apply(args.run_id)
        if args.command == "update":
            output = command_update(args.also)
        elif args.command == "refresh":
            output = command_refresh(args.also, args.installed, args.compact)
        elif args.command == "apply-installed":
            output = command_apply_installed(args.also)
        elif args.command == "plan":
            output = command_plan(args.run_id, args.compact, args.terminal)
        elif args.command == "resume":
            output = run_resume(args.run_id, args.terminal)
        elif args.command == "record-manual":
            output = run_record_manual(args.run_id, args.terminal, args.action, args.result, args.detail)
        elif args.command == "orphans":
            output = run_orphans(args.run_id)
        elif args.command == "close":
            output = run_close(args.run_id, args.terminal)
        elif args.command == "decide":
            output = command_decide(args.run_id, args.answer)
        elif args.command == "apply":
            output = command_apply(args.run_id, args.compact, args.terminal, max(5, args.timeout_seconds))
        else:
            output = command_status(args.run_id)
    except RefreshError as error:
        output = {"ok": False, "error": {"code": error.code, "message": error.message}}
        if "entry" in error.details:
            output = {"ok": False, "status": "error", "code": error.code, "entry": error.details["entry"], "error": output["error"]}
    print(json.dumps(output, ensure_ascii=False, indent=1))
    return 0 if output.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
