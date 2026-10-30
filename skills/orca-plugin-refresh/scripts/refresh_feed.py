from __future__ import annotations

import time

from refresh_core import RUN_STATE_WAIT_SECONDS, RefreshError, exclusive, load_run, now, run_path, save_json


class RunFeed:
    """The deferred sessions and the initiating session that a run hands to its helper, read again as new ones join."""

    def __init__(self, run_id: str, follow_seconds: float, self_seconds: float) -> None:
        self.run_id = run_id
        self.follow_seconds = follow_seconds
        self.self_seconds = self_seconds
        self.seen: set[tuple[str, object, bool]] = set()

    def fresh(self, state: dict) -> list[dict]:
        start, found = time.time(), []
        for item in state.get("follow_up", []):
            if not isinstance(item, dict) or not isinstance(item.get("handle"), str) or not isinstance(item.get("actions"), list):
                continue
            key = (item["handle"], item.get("deferred_at"), False)
            if key in self.seen:
                continue
            self.seen.add(key)
            found.append({**item, "actions": list(item["actions"]), "status": "pending", "initiator": False,
                          "detail": item.get("detail") or "busy", "deadline": item.get("deferred_at", start) + self.follow_seconds})
        own = state.get("self")
        if isinstance(own, dict) and isinstance(own.get("handle"), str) and isinstance(own.get("actions"), list):
            key = (own["handle"], own.get("deferred_at"), True)
            if key not in self.seen:
                self.seen.add(key)
                found.append({**own, "actions": list(own["actions"]), "status": "pending", "initiator": True, "detail": None,
                              "deadline": start + self.self_seconds})
        return found

    def poll(self) -> list[dict]:
        try:
            return self.fresh(load_run(self.run_id))
        except RefreshError:
            return []

    def close(self) -> list[dict]:
        """Take any entry that joined since the last read; only when none did, mark the helper finished in the same locked step."""
        with exclusive("run-state", wait_seconds=RUN_STATE_WAIT_SECONDS):
            state = load_run(self.run_id)
            found = self.fresh(state)
            if not found:
                save_json(run_path(self.run_id), {**state, "helper_finished_at": now()})
            return found
