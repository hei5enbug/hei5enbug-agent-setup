from __future__ import annotations

import re

from refresh_core import HANDLE, RefreshError, update_run

ACTIONS = ("reload", "compact", "clear", "resume")
RESULTS = ("done", "failed")
RECORDABLE = frozenset({"skipped", "failed"})
DETAIL = re.compile(r"^[a-z0-9_]{1,60}$")


RESUME_MARKS = ("host_release_outdated", "resume_approval_needed", "resume_line", "terminal_handle", "exit_state")


def failed_view(view: dict, action: str, detail: str | None) -> dict:
    """Keep the failed action and every other unfinished action outstanding, and remember the status from before the failure."""
    current = list(view.get("actions") or [])
    actions = current if action in current else [*current, action]
    before = view.get("before_failure") or {"status": view["status"], "detail": view.get("detail")}
    failed = [item for item in view.get("failed_actions", []) if item != action]
    return {**view, "status": "failed", "detail": detail, "actions": actions, "failed_actions": [*failed, action],
            "before_failure": before}


def settled_view(view: dict, remaining: list[str], failed: list[str]) -> dict:
    """The view after a done record: done once nothing remains, failed while another failed action remains, else as before the failure."""
    cleaned = {key: value for key, value in view.items() if key not in ("before_failure", "failed_actions")}
    if not remaining:
        return {**cleaned, "status": "done", "detail": "applied_by_agent", "actions": []}
    if failed:
        return {**cleaned, "status": "failed", "actions": remaining, "failed_actions": failed,
                "before_failure": view.get("before_failure")}
    before = view.get("before_failure") or {}
    return {**cleaned, "status": before.get("status", view["status"]), "detail": before.get("detail", view.get("detail")),
            "actions": remaining}


def outstanding(view: dict) -> list[str]:
    """The actions still to do: the saved ones, or, when an automatic step cleared them, the planned ones not yet done."""
    if view.get("actions"):
        return list(view["actions"])
    done = {item for item in view.get("completed", []) if ":" not in item}
    if "resumed" in done or "resume" in done:
        done.add("reload")
    return [item for item in view.get("planned") or [] if item not in done]


def recorded_view(view: dict, action: str, result: str, detail: str | None) -> dict:
    """The session's saved view after the agent finished one action by hand."""
    completed = [*view.get("completed", []), action if result == "done" else f"{action}:{detail}"]
    changed = {**view, "completed": completed, "manual": True, "actions": outstanding(view)}
    if result == "failed":
        return failed_view(changed, action, detail)
    if action == "resume":
        for key in RESUME_MARKS:
            changed.pop(key, None)
    finished = {action, "reload"} if action == "resume" else {action}
    remaining = [item for item in changed["actions"] if item not in finished]
    failed = [item for item in view.get("failed_actions", []) if item != action]
    return settled_view(changed, remaining, failed)


def run_record_manual(run_id: str, handle: str, action: str, result: str, detail: str | None) -> dict:
    """Record one action that the agent finished by hand on a session the script skipped, so `status` shows it."""
    if not HANDLE.fullmatch(handle):
        raise RefreshError("terminal_invalid", "Name the session with a valid --terminal handle.")
    if action not in ACTIONS or result not in RESULTS:
        raise RefreshError("record_invalid", "Use a known --action and a --result of done or failed.")
    if detail is not None and not DETAIL.fullmatch(detail):
        raise RefreshError("detail_invalid", "Write --detail as lowercase letters, digits, and underscores.")
    if result == "failed" and detail is None:
        detail = f"manual_{action}_failed"

    def change(saved: dict) -> dict:
        view = saved.get("sessions", {}).get(handle)
        if not isinstance(view, dict):
            raise RefreshError("session_not_in_run", "This run holds no result for that session.")
        if view.get("status") not in RECORDABLE:
            raise RefreshError("session_not_recordable", "Only a session the script skipped or failed can be recorded by hand.")
        updated = recorded_view(view, action, result, detail)
        resumed = saved.get("resumed", {})
        if action == "resume" and result == "done":
            resumed = {**resumed, handle: {"terminal": view.get("terminal"), "status": "done", "detail": "resumed", "manual": True}}
        return {**saved, "sessions": {**saved["sessions"], handle: updated}, **({"resumed": resumed} if resumed else {})}

    saved = update_run(run_id, change)
    return {"ok": True, "run_id": run_id, "session": saved["sessions"][handle]}
