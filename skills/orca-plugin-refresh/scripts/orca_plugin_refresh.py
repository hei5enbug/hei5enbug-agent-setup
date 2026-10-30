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
from refresh_core import (  # noqa: E402
    CODEX_HOOK_TRUST, HANDLE, HOSTS, MARKETPLACE, PLUGIN, PLUGIN_ID, PLUGIN_ROOT, RUN_ID, SESSION_CONTEXT, RefreshError,
    exclusive, executable, load_plugin_script, load_run, now, parse_time, run, run_json, run_path, save_json, state_root, update_run,
)
from refresh_feed import RunFeed  # noqa: E402
from refresh_follow import (  # noqa: E402
    IDLE_CONFIRM_SECONDS, INSTALL_CHECK_SECONDS, IdleWaiters, SendLock, follow_up, install_current, still_needed,
)
from refresh_install import (  # noqa: E402
    BUNDLE_SKIPPED_DIRS, CODEX_IDLE_EVENTS, CODEX_TURN_ENV, DEFAULT_HOOKS, HOOK_LAUNCHER, HOOK_ROOT, HOOKS_TRUST_WARNING,
    LAUNCHED_SCRIPT, REQUIRED_HOOK_TARGETS, REQUIRED_HOOKS, ROLLOUT_RECENT_SECONDS, ROLLOUT_TAIL_BYTES, bundle_digest,
    check_hooks, codex_home, codex_trust_reset, hook_file_entries, hooks_digest, inside, install_gate, installed,
    read_hook_file, read_manifest, rollout_idle, run_install, scan_hook_events, validate_claude_mod, validate_install,
)
from refresh_orca import Orca  # noqa: E402
from refresh_orphans import run_close, run_orphans  # noqa: E402
from refresh_resume import run_resume  # noqa: E402
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
CODEX_TRUST_TIMEOUT_SECONDS = 60


def recovery_command(root: str | None, companions: Sequence[str] = ()) -> str:
    current = Path(__file__).resolve()
    try:
        relative = current.relative_to(PLUGIN_ROOT)
    except ValueError:
        relative = current.name
    candidate = Path(root) / relative if root else current
    script = candidate if candidate.is_file() else current
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
    local = local_source(host, PLUGIN_ID, before.get("item"), context)
    if local:
        version = local["version"] or before["version"]
        result = {
            "before_version": version,
            "after_version": version,
            "root": before["root"],
            "previous_root": before["root"],
            "digest": before_snapshot["digest"],
            "instructions_changed": False,
            "warnings": [],
            "local_source": True,
        }
        if local.get("note"):
            result["note"] = local["note"]
        return result
    before_bundle = bundle_digest(Path(before["root"])) if host == "codex" else None
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
        "warnings": [],
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
    if host == "codex" and codex_trust_reset(before_snapshot["hooks"], after_snapshot["hooks"], before_bundle,
                                             bundle_digest(Path(after["root"]))):
        reason = trust_codex_hooks()
        if reason is None:
            result["codex_hooks_trusted"] = True
        else:
            result["warnings"].append({**HOOKS_TRUST_WARNING, "detail": reason})
    return result


def trust_codex_hooks() -> str | None:
    """Re-trust this plugin's Codex hooks that the install left untrusted, from a verified official copy only; None when
    none are left untrusted, otherwise why they were not trusted."""
    command, cwd = [core.executable("codex"), "app-server"], str(Path.home())
    try:
        result = CODEX_HOOK_TRUST.app_server_calls(command, dict(os.environ), cwd, [("hooks/list", {"cwds": [cwd]})],
                                                   CODEX_TRUST_TIMEOUT_SECONDS)[0]
        listed = CODEX_HOOK_TRUST.listed_hooks(result, cwd)
        if CODEX_HOOK_TRUST.candidates(listed):
            CODEX_HOOK_TRUST.heal(listed, command, dict(os.environ), cwd, CODEX_TRUST_TIMEOUT_SECONDS)
    except (CODEX_HOOK_TRUST.TrustError, RefreshError) as error:
        return str(error)
    return None


def untrusted_hook_counts() -> dict[str, int]:
    """How many hooks Codex lists as untrusted or modified, by plugin ID."""
    command, cwd = [core.executable("codex"), "app-server"], str(Path.home())
    result = CODEX_HOOK_TRUST.app_server_calls(command, dict(os.environ), cwd, [("hooks/list", {"cwds": [cwd]})],
                                               CODEX_TRUST_TIMEOUT_SECONDS)[0]
    counts: dict[str, int] = {}
    for hook in CODEX_HOOK_TRUST.listed_hooks(result, cwd):
        if isinstance(hook, dict) and hook.get("trustStatus") in CODEX_HOOK_TRUST.UNTRUSTED and isinstance(hook.get("pluginId"), str):
            counts[hook["pluginId"]] = counts.get(hook["pluginId"], 0) + 1
    return counts


def settle_companion_trust(plugins: list[dict], context: dict) -> list[dict]:
    """Narrow each companion's provisional trust warning to the hooks Codex still lists as untrusted or modified.

    One listing, taken after the last companion install, serves every companion that may have lost trust. Nothing is
    trusted here; a listing that fails keeps the warning with the reason."""
    pending = set(context.get("trust_reset", ()))
    if not pending:
        return plugins
    try:
        counts, unread = untrusted_hook_counts(), None
    except (CODEX_HOOK_TRUST.TrustError, RefreshError, OSError):
        counts, unread = {}, "Codex hook trust state could not be read"
    settled = []
    for plugin in plugins:
        if plugin["plugin"] not in pending:
            settled.append(plugin)
            continue
        count = counts.get(plugin["plugin"], 0)
        kept = [warning for warning in plugin["warnings"] if warning["code"] != HOOKS_TRUST_WARNING["code"]]
        if unread:
            kept.append({**HOOKS_TRUST_WARNING, "detail": unread})
        elif count:
            kept.append({**HOOKS_TRUST_WARNING, "detail": f"Codex lists {count} hook{'s' if count != 1 else ''} as untrusted or modified"})
        settled.append({**plugin, "warnings": kept})
    return settled


def host_failure(error: RefreshError) -> dict:
    entry = {"error": {"code": error.code, "message": error.message}}
    for key in ("root", "recovery_command"):
        if key in error.details:
            entry[key] = error.details[key]
    return entry


def refresh_report(run_id: str, hosts: dict[str, dict], extra: dict) -> dict:
    save_json(run_path(run_id), {"run_id": run_id, "created_at": now(), "hosts": hosts, "sessions": {}})
    failed = any("error" in value or any(item["status"] == "error" for item in value["plugins"]) for value in hosts.values())
    return {"ok": not failed, "run_id": run_id, "script": continuation_script(hosts), "hosts": hosts, **extra}


def command_update(also: Sequence[str] = ()) -> dict:
    ids, extra = companion_ids(also)
    run_id = uuid.uuid4().hex
    hosts: dict[str, dict] = {}
    for host in HOSTS:
        context: dict = {"ids": ids}
        try:
            hosts[host] = update_host(host, context)
        except RefreshError as error:
            hosts[host] = host_failure(error)
        except (OSError, ValueError):
            hosts[host] = host_failure(RefreshError("plugin_check_failed", f"A {host} plugin file could not be checked."))
        plugins = [refresh_companion(host, plugin_id, True, context) for plugin_id in ids]
        hosts[host]["plugins"] = settle_companion_trust(plugins, context)
    return refresh_report(run_id, hosts, extra)


def command_apply_installed(also: Sequence[str] = ()) -> dict:
    ids, extra = companion_ids(also)
    run_id = uuid.uuid4().hex
    hosts: dict[str, dict] = {}
    for host in HOSTS:
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
                "warnings": [],
            }
        except RefreshError as error:
            hosts[host] = host_failure(error)
        except (OSError, ValueError):
            hosts[host] = host_failure(RefreshError("plugin_check_failed", f"A {host} plugin file could not be checked."))
        context: dict = {}
        hosts[host]["plugins"] = [refresh_companion(host, plugin_id, False, context) for plugin_id in ids]
    return refresh_report(run_id, hosts, extra)


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


def public(entry: dict) -> dict:
    keys = ("host", "title", "worktree", "status", "detail", "completed", "actions", "compact_reason", "note", "initiator",
            "ready_signal", "input", "release", "host_release_outdated", "plugin_load", "orphaned")
    view = {key: entry.get(key) for key in keys if entry.get(key) not in (None, [], False)}
    if entry.get("detail") == "plugin_load_error" or entry.get("host_release_outdated"):
        view["resume_approval_needed"] = True
    view["terminal"] = f"…{entry['handle'][-6:]}"
    return view


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


def command_plan(run_id: str, mode: str, only: Sequence[str]) -> dict:
    state = load_run(run_id)
    sessions = plan_sessions(Orca(), state, mode, only)
    return {"ok": True, "run_id": run_id, "sessions": [public(entry) for entry in sessions]}


def handled(state: dict, handle: str) -> str | None:
    """The status a session already reached in this run, ignoring a queue whose helper never ran or died."""
    status = state.get("sessions", {}).get(handle, {}).get("status")
    if status == "done":
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


def commit_apply(run_id: str, mode: str, sessions: list[dict], others: list[dict], spawn: Callable[[str], int]) -> None:
    """Record this apply and hand its deferred sessions to the live helper or a new one, on the run state read afresh under its lock."""
    own = next((entry for entry in sessions if entry["initiator"] and entry["status"] == "pending"), None)
    deferred = [entry for entry in others if entry["status"] == "deferred"]
    initiator = next((entry for entry in sessions if entry["initiator"]), None)
    handed = time.time()

    def change(state: dict) -> dict:
        helper = state.get("helper") or {}
        helper_waiting = alive(helper.get("pid")) and not state.get("helper_finished_at")
        state["initiator"] = ({key: initiator.get(key) for key in ("handle", "host", "screen_identified")}
                              if initiator else None)
        state["compact_mode"] = mode
        if own or deferred:
            items = [
                {key: entry.get(key) for key in ("handle", "host", "actions", "title", "worktree", "compact_reason", "detail", "probe_retries",
                                                 "screen_identified", "input", "ready_signal", "release", "host_release_outdated", "orphaned")}
                | {"deferred_at": handed, **handoff_point(entry["handle"])}
                for entry in deferred
            ]
            handed_off = True
            if helper_waiting:
                pid = helper["pid"]
                state["follow_up"] = [*state.get("follow_up", []), *items]
                if items:
                    state.pop("others_finished_at", None)
            else:
                try:
                    pid = spawn(run_id)
                except OSError:
                    handed_off = False
                    if own:
                        own.update(status="failed", detail="helper_start_failed", actions=[])
                    for entry in deferred:
                        entry.update(status="skipped", detail="helper_start_failed", actions=[])
                else:
                    state["helper"] = {"pid": pid, "started_at": now()}
                    state.pop("helper_finished_at", None)
                    state.pop("others_finished_at", None)
                    state["follow_up"] = items
                    if not own:
                        state.pop("self", None)
            if handed_off and own:
                own.update(status="queued_after_turn", detail="waits_for_this_turn_to_end")
                state["self"] = {key: own.get(key) for key in ("handle", "host", "actions", "title", "worktree", "screen_identified")}
                state["self"].update(compact_reason=own.get("compact_reason"), helper_pid=pid, helper_started_at=now(), deferred_at=handed,
                                   **handoff_point(own["handle"]))
                state.pop("self_finished_at", None)
        state["sessions"] = {**state.get("sessions", {}), **{entry["handle"]: public(entry) for entry in sessions if not entry.get("handled")}}
        state["applied_at"] = now()
        return state

    update_run(run_id, change)


def command_apply(run_id: str, mode: str, only: Sequence[str], seconds: int, spawn: Callable[[str], int] = spawn_self_apply) -> dict:
    with exclusive("sessions"):
        state = load_run(run_id)
        orca = Orca()
        sessions = plan_sessions(orca, state, mode, only)
        for entry in sessions:
            previous = handled(state, entry["handle"])
            if previous:
                entry.update(status=previous, detail="already_handled_in_this_run", actions=[], handled=True)
        others = [entry for entry in sessions if not entry["initiator"] and not entry.get("handled")]
        drive(orca, others, state, time.time() + seconds, expire="deferred")
        commit_apply(run_id, mode, sessions, others, spawn)
    summary = {status: sum(1 for entry in sessions if entry["status"] == status) for status in {entry["status"] for entry in sessions}}
    return {"ok": all(entry["status"] in {"done", "queued_after_turn", "deferred"} for entry in sessions), "run_id": run_id, "summary": summary, "sessions": [public(entry) for entry in sessions]}


def lock_guard() -> AbstractContextManager:
    return exclusive("sessions")


def notify(orca: Orca, entry: dict, run_id: str, sleep: Callable[[float], None], guard: Callable[[], AbstractContextManager] = nullcontext) -> str:
    message = f"Plugin refresh run {run_id} finished. Run `{status_command(run_id)}` and report every session, including any that were not refreshed."
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


def command_self_apply(run_id: str, sleep: Callable[[float], None] = time.sleep, waiters: IdleWaiters | None = None) -> int:
    """The one detached helper: finish deferred sessions and this session, then send one result notice and exit.

    It holds the sessions lock only while sending to a session and confirming it, and reads the run state again on
    every pass so sessions that a later `apply` hands over join this helper.
    """
    feed = RunFeed(run_id, FOLLOW_UP_SECONDS, SELF_WAIT_SECONDS)
    with exclusive("run-state", wait_seconds=core.RUN_STATE_WAIT_SECONDS):
        entries = feed.poll()
    if not entries:
        return 0
    state = load_run(run_id)
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
    follow_up(orca, entries, state, sleep=sleep, waiters=waiters, progress=record, lock=guard,
              incoming=lambda closing: feed.close() if closing else feed.poll())
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


def status_command(run_id: str) -> str:
    prefix = f"XDG_STATE_HOME={shlex.quote(os.environ['XDG_STATE_HOME'])} " if os.environ.get("XDG_STATE_HOME") else ""
    return f"{prefix}python3 {shlex.quote(str(Path(__file__).resolve()))} status --run-id {run_id} --json"


def command_status(run_id: str) -> dict:
    state = load_run(run_id)
    return {
        "ok": True,
        "run_id": run_id,
        "hosts": state.get("hosts"),
        "sessions": list(state.get("sessions", {}).values()),
        "resumed": list(state.get("resumed", {}).values()),
        "not_refreshed": [item for item in state.get("sessions", {}).values() if item.get("status") in {"skipped", "failed", "blocked"}],
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
    for name in ("plan", "apply"):
        sub = commands.add_parser(name)
        sub.add_argument("--run-id", required=True)
        sub.add_argument("--compact", choices=("auto", "always", "never"), default="auto")
        sub.add_argument("--terminal", action="append", default=[])
        sub.add_argument("--json", action="store_true")
        if name == "apply":
            sub.add_argument("--timeout-seconds", type=int, default=DEFAULT_APPLY_SECONDS)
    commands.add_parser("self-apply").add_argument("--run-id", required=True)
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
    status = commands.add_parser("status")
    status.add_argument("--run-id", required=True)
    status.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "self-apply":
            return command_self_apply(args.run_id)
        if args.command == "update":
            output = command_update(args.also)
        elif args.command == "apply-installed":
            output = command_apply_installed(args.also)
        elif args.command == "plan":
            output = command_plan(args.run_id, args.compact, args.terminal)
        elif args.command == "resume":
            output = run_resume(args.run_id, args.terminal)
        elif args.command == "orphans":
            output = run_orphans(args.run_id)
        elif args.command == "close":
            output = run_close(args.run_id, args.terminal)
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
