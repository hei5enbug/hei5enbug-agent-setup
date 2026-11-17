from jobq.queue import claim_next, enqueue


def test_jobs_are_claimed_in_order_and_once(tmp_path):
    first = enqueue(tmp_path, {"n": 1})
    second = enqueue(tmp_path, {"n": 2})
    job = claim_next(tmp_path, "w1")
    assert (job.id, job.payload, job.worker) == (first, {"n": 1}, "w1")
    assert job.path.parent.name == "running"
    assert claim_next(tmp_path, "w2").id == second
    assert claim_next(tmp_path, "w3") is None


def test_an_empty_queue_has_nothing_to_claim(tmp_path):
    assert claim_next(tmp_path, "w1") is None
