"""The role runner's share of the request budget: each assignment and result pair is admitted as one delegated run.

A pair counts under the session that received the user's prompt, which the runner learns from the environment as its
children do. A pair past a cap is denied. A pair the parallel limit holds back waits for one of this call's running
pairs to end, so a call runs at most the limit at once and starts the next pair as one ends.
"""

from __future__ import annotations

import os
import threading

import request_budget
from role_runner_child import parent_session
from role_runner_config import Run


def run_kind(run: Run) -> str:
    return request_budget.ROLE_PREFIX + (run.agent or run.role or run.capability or run.target)


class Gate:
    def __init__(self, run: Run, who: tuple[str, str] | None = None, limit: int | None = None) -> None:
        self.kind = run_kind(run)
        self.who = request_budget.identity_from_text(parent_session(os.environ)) if who is None else who
        self.limit = limit
        self.condition = threading.Condition()
        self.running = 0

    def acquire(self, run_id: str) -> str | None:
        """Admit one pair, waiting while the limit holds it back and this call has a pair running; return the denial, if any."""
        if self.who is None:
            return None
        with self.condition:
            while True:
                reason = request_budget.admit(self.who, self.kind, run_id, pid=os.getpid(), limit=self.limit)
                if reason is None:
                    self.running += 1
                    return None
                if not (reason.startswith(request_budget.LIMIT_MARKER) and self.running > 0):
                    return reason
                self.condition.wait()

    def release(self, run_id: str, ok: bool) -> None:
        if self.who is None:
            return
        with self.condition:
            request_budget.finish(self.who, self.kind, run_id, ok=ok)
            self.running -= 1
            self.condition.notify_all()
