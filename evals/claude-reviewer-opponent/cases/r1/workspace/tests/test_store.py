import unittest

from demo_jobs.store import Job, JobStore
from demo_jobs.worker import drain


class JobStoreTest(unittest.TestCase):
    def test_complete_marks_the_job_done(self):
        store = JobStore()
        store.add(Job("j1", "a"))
        store.complete("j1")
        self.assertEqual(store.count("done"), 1)

    def test_claim_next_returns_each_pending_job_once(self):
        store = JobStore()
        store.add(Job("j1", "a"))
        store.add(Job("j2", "b"))
        first = store.claim_next("w0")
        second = store.claim_next("w0")
        self.assertEqual([first.id, second.id], ["j1", "j2"])
        self.assertIsNone(store.claim_next("w0"))

    def test_drain_runs_every_job(self):
        store = JobStore()
        for index in range(20):
            store.add(Job(f"j{index}", "x"))
        seen = []
        drain(store, lambda job: seen.append(job.id))
        self.assertEqual(store.count("done"), 20)
        self.assertEqual(len(seen), 20)
