from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Job:
    id: str
    payload: dict
    worker: str
    path: Path


def enqueue(root: Path, payload: dict) -> str:
    pending = Path(root) / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    job_id = f"{len(list(pending.iterdir())) + len(list((Path(root) / 'running').glob('*.json'))):06d}-{uuid.uuid4().hex[:6]}"
    (pending / f"{job_id}.json").write_text(json.dumps({"id": job_id, "payload": payload}))
    return job_id


def _take(root: Path, worker: str) -> Job | None:
    running = Path(root) / "running"
    running.mkdir(parents=True, exist_ok=True)
    for path in sorted((Path(root) / "pending").glob("*.json")):
        target = running / path.name
        try:
            os.rename(path, target)
        except FileNotFoundError:
            continue
        data = json.loads(target.read_text())
        data["claimed_by"] = worker
        temporary = target.with_name(target.name + f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(data))
        os.replace(temporary, target)
        return Job(data["id"], data["payload"], worker, target)
    return None


def claim_next(root: Path, worker: str) -> Job | None:
    return _take(root, worker)


def claim_batch(root: Path, worker: str, limit: int) -> list[Job]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    jobs: list[Job] = []
    while len(jobs) < limit:
        job = _take(root, worker)
        if job is None:
            break
        jobs.append(job)
    return jobs
