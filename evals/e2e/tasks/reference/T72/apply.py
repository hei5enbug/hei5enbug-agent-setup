import sys

from patch_tools import append

append(sys.argv[1], "tests/test_queue.py", '''

def test_claim_batch_takes_jobs_in_order(tmp_path):
    from jobq.queue import claim_batch

    ids = [enqueue(tmp_path, {"n": n}) for n in range(3)]
    assert [job.id for job in claim_batch(tmp_path, "w1", 2)] == ids[:2]
''')
