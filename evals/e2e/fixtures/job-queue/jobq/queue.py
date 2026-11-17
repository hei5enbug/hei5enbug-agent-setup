from __future__ import annotations

import json
import shutil
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


def claim_next(root: Path, worker: str) -> Job | None:
    running = Path(root) / "running"
    running.mkdir(parents=True, exist_ok=True)
    for path in sorted((Path(root) / "pending").glob("*.json")):
        data = json.loads(path.read_text())
        if data.get("claimed_by"):
            continue
        data["claimed_by"] = worker
        path.write_text(json.dumps(data))
        target = running / path.name
        shutil.move(str(path), str(target))
        return Job(data["id"], data["payload"], worker, target)
    return None
