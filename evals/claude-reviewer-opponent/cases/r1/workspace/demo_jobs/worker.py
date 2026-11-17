"""Worker threads that drain a JobStore."""

from __future__ import annotations

import threading
from collections.abc import Callable

from demo_jobs.store import Job, JobStore


def run_worker(store: JobStore, handler: Callable[[Job], None], worker_id: str) -> None:
    while True:
        job = store.claim_next(worker_id)
        if job is None:
            return
        handler(job)
        store.complete(job.id)


def drain(store: JobStore, handler: Callable[[Job], None], workers: int = 4) -> None:
    threads = [
        threading.Thread(target=run_worker, args=(store, handler, f"w{index}"))
        for index in range(workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
