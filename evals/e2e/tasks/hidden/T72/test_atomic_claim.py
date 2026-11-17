import json
import subprocess
import sys
from pathlib import Path

import pytest

from jobq.queue import claim_batch, claim_next, enqueue

ROOT = Path(__file__).resolve().parents[2]

LOOP = """
import json, sys
from jobq.queue import {call}
root, worker, out = sys.argv[1:4]
ids = []
while True:
    {body}
    if not got:
        break
    ids.extend(got)
open(out, "w").write(json.dumps(ids))
"""
SINGLE = LOOP.format(call="claim_next", body="job = claim_next(root, worker); got = [job.id] if job else []")
BATCH = LOOP.format(call="claim_batch", body="got = [job.id for job in claim_batch(root, worker, 7)]")


def race(tmp_path, script, workers):
    queue = tmp_path / "queue"
    ids = [enqueue(queue, {"n": n}) for n in range(60)]
    processes = []
    for index in range(workers):
        out = tmp_path / f"out{index}.json"
        processes.append((out, subprocess.Popen([sys.executable, "-B", "-c", script, str(queue), f"w{index}", str(out)],
                                                cwd=ROOT, stderr=subprocess.PIPE, text=True)))
    claimed = []
    for out, process in processes:
        _, error = process.communicate(timeout=120)
        assert process.returncode == 0, error
        claimed.extend(json.loads(out.read_text()))
    return queue, ids, claimed


def test_competing_workers_claim_every_job_exactly_once(tmp_path):
    queue, ids, claimed = race(tmp_path, SINGLE, 6)
    assert sorted(claimed) == sorted(ids)
    assert len(list((queue / "pending").glob("*.json"))) == 0
    assert len(list((queue / "running").glob("*.json"))) == 60


def test_competing_batch_claims_share_no_job(tmp_path):
    queue, ids, claimed = race(tmp_path, BATCH, 5)
    assert sorted(claimed) == sorted(ids)


def test_a_claimed_file_records_its_worker(tmp_path):
    job_id = enqueue(tmp_path, {"n": 1})
    job = claim_next(tmp_path, "w9")
    assert job.worker == "w9" and job.path.parent.name == "running"
    assert json.loads(job.path.read_text()) == {"id": job_id, "payload": {"n": 1}, "claimed_by": "w9"}


def test_claim_batch_takes_jobs_in_id_order_up_to_the_limit(tmp_path):
    ids = [enqueue(tmp_path, {"n": n}) for n in range(5)]
    batch = claim_batch(tmp_path, "w1", 3)
    assert [job.id for job in batch] == ids[:3]
    assert all(job.worker == "w1" for job in batch)
    assert [job.id for job in claim_batch(tmp_path, "w2", 10)] == ids[3:]
    assert claim_batch(tmp_path, "w3", 2) == []


@pytest.mark.parametrize("limit", [0, -1])
def test_claim_batch_needs_a_positive_limit(tmp_path, limit):
    with pytest.raises(ValueError):
        claim_batch(tmp_path, "w1", limit)


def test_an_empty_queue_has_nothing_to_claim(tmp_path):
    assert claim_next(tmp_path, "w1") is None
    assert claim_batch(tmp_path, "w1", 3) == []
