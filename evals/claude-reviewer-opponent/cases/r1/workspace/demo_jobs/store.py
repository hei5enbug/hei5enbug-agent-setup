"""In-memory job store shared by the producer and the worker threads of one process."""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass
class Job:
    id: str
    payload: str
    state: str = "pending"
    owner: str | None = None


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def add(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job

    def claim_next(self, worker_id: str) -> Job | None:
        for job in self._jobs.values():
            if job.state == "pending":
                job.state = "claimed"
                job.owner = worker_id
                return job
        return None

    def complete(self, job_id: str) -> None:
        with self._lock:
            self._jobs[job_id].state = "done"

    def count(self, state: str) -> int:
        with self._lock:
            return sum(1 for job in self._jobs.values() if job.state == state)
