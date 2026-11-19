"""Watch a Claude Code stream for a final `result` that no background work follows, so a hung process can be ended."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

RESULT_TYPE = "result"
NEW_TURN_TYPES = frozenset({"assistant", "user"})
TASK_STARTED = "task_started"
TASK_ENDED = frozenset({"task_notification"})
TASK_UPDATED = "task_updated"
TASKS_CHANGED = "background_tasks_changed"
RUNNING_STATUSES = frozenset({"running", "pending", "in_progress", "started"})


class ResultIdleWatch:
    """Reads the growing stream file and decides when the run has answered, has no background work, and went quiet."""

    def __init__(self, path: Path, idle_seconds: float, begin: float, clock: Callable[[], float] = time.monotonic):
        self._path = path
        self._idle = idle_seconds
        self._begin = begin
        self._clock = clock
        self._offset = 0
        self._partial = b""
        self._answered_at: float | None = None
        self._last_line_at = begin
        self._listed_tasks = False
        self._open_tasks: frozenset[str] = frozenset()
        self.triggered = False

    @property
    def answer_seconds(self) -> float:
        """Seconds from the start to the last `result` event read."""
        return (self._answered_at if self._answered_at is not None else self._clock()) - self._begin

    def should_stop(self) -> bool:
        self._read_new_lines()
        if self._answered_at is None or self._listed_tasks or self._open_tasks:
            return False
        self.triggered = self._clock() - self._last_line_at >= self._idle
        return self.triggered

    def _read_new_lines(self) -> None:
        try:
            with self._path.open("rb") as handle:
                handle.seek(self._offset)
                data = handle.read()
        except OSError:
            return
        if not data:
            return
        self._offset += len(data)
        *lines, self._partial = (self._partial + data).split(b"\n")
        now = self._clock()
        for line in lines:
            if line.strip():
                self._last_line_at = now
                self._apply(line, now)

    def _apply(self, line: bytes, now: float) -> None:
        try:
            event = json.loads(line)
        except ValueError:
            return
        if not isinstance(event, dict):
            return
        kind, subtype = event.get("type"), event.get("subtype")
        if kind == RESULT_TYPE:
            self._answered_at = now
        elif kind in NEW_TURN_TYPES:
            self._answered_at = None
        elif subtype == TASKS_CHANGED:
            self._listed_tasks = bool(event.get("tasks"))
        elif subtype == TASK_STARTED:
            self._open_tasks = self._open_tasks | {str(event.get("task_id"))}
        elif subtype in TASK_ENDED or (subtype == TASK_UPDATED and _update_finished(event)):
            self._open_tasks = self._open_tasks - {str(event.get("task_id"))}


def _update_finished(event: dict[str, Any]) -> bool:
    patch = event.get("patch")
    status = patch.get("status") if isinstance(patch, dict) else None
    return isinstance(status, str) and status not in RUNNING_STATUSES
