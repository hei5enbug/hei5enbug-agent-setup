"""Queues the jobs of the report and export features."""

from queues import alpha_queue, beta_queue


def enqueue_report(job: str) -> None:
    alpha_queue.put("report", job)


def enqueue_summary(job: str) -> None:
    alpha_queue.put("summary", job)


def enqueue_digest(job: str) -> None:
    alpha_queue.put("digest", job)


def enqueue_export(job: str) -> None:
    beta_queue.put("export", job)


def enqueue_archive(job: str) -> None:
    beta_queue.put("archive", job)


def next_report() -> str | None:
    return alpha_queue.get("report")
