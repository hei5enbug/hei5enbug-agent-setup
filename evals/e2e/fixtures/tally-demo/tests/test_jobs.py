from queues import alpha_queue, beta_queue
from tally import jobs


def test_report_and_export_jobs_use_their_queues():
    jobs.enqueue_report("r1")
    jobs.enqueue_export("e1")
    assert jobs.next_report() == "r1"
    assert beta_queue.get("export") == "e1"
    assert alpha_queue.STEPS > 0
