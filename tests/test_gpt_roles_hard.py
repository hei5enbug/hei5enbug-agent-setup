"""Offline calibration of the harder GPT role cases W4 to W6, R2, and R3: the seed fails the hidden tests, the reference passes, and
every typical shallow fix fails; a plausible wrong research answer is rejected. No model is called."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals" / "gpt-roles"))

import gr_cases  # noqa: E402
import gr_research_cases  # noqa: E402
import gr_worker_cases  # noqa: E402
import gr_worker_hard_refs as refs  # noqa: E402

HARD = ("W4", "W5", "W6")


class HardWorkerCalibrationTest(unittest.TestCase):
    def seed(self, case_id, files=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name) / "repo"
        repo.mkdir()
        base = gr_worker_cases.seed(case_id, repo)
        for relative, text in (files or {}).items():
            (repo / relative).parent.mkdir(parents=True, exist_ok=True)
            (repo / relative).write_text(text, encoding="utf-8")
        return repo, base

    def test_시드의_기존_테스트는_통과하고_숨은_테스트는_실패한다(self):
        for case_id in HARD:
            repo, base = self.seed(case_id)
            found = gr_worker_cases.failures(case_id, repo, base)
            self.assertEqual(len(found), 1, (case_id, found))
            self.assertIn("hidden tests fail", found[0])

    def test_기준_해법은_통과한다(self):
        for case_id in HARD:
            repo, base = self.seed(case_id, refs.SOLUTIONS[case_id])
            self.assertEqual(gr_worker_cases.failures(case_id, repo, base), [], case_id)

    def test_흔한_얕은_수정은_사례마다_둘_이상_모두_실패한다(self):
        for case_id in HARD:
            self.assertGreaterEqual(len(refs.SHALLOW[case_id]), 2, case_id)
            for name, (files, missed) in refs.SHALLOW[case_id].items():
                repo, base = self.seed(case_id, files)
                self.assertTrue(gr_worker_cases.failures(case_id, repo, base), f"{case_id} shallow fix passed: {name} ({missed})")

    def test_얕은_수정이_실패하는_이유는_숨은_테스트나_상한이다(self):
        reasons = {}
        for case_id in HARD:
            for name, (files, _) in refs.SHALLOW[case_id].items():
                repo, base = self.seed(case_id, files)
                reasons[(case_id, name)] = " | ".join(gr_worker_cases.failures(case_id, repo, base))
        self.assertIn("hidden tests fail", reasons[("W4", "pager only")])
        self.assertIn("hidden tests fail", reasons[("W5", "locks everywhere except stats")])
        self.assertIn("visible tests fail", reasons[("W6", "is not None for every source")])
        self.assertIn("cap is 3", reasons[("W6", "shared helper in a new module")])
        self.assertIn("a new file outside tests/", reasons[("W6", "shared helper in a new module")])

    def test_상한은_테스트_폴더를_세지_않는다(self):
        files = {**refs.SOLUTIONS["W4"], "tests/test_extra.py": "def test_extra():\n    assert True\n"}
        repo, base = self.seed("W4", files)
        self.assertEqual(gr_worker_cases.failures("W4", repo, base), [])

    def test_교착하는_해법은_멈추지_않고_실패로_채점한다(self):
        deadlock = refs.swap(refs.BUCKET_FIXED, "    def remaining(self):\n        with self._lock:\n            self._refill()\n            return self._tokens\n",
                             "    def remaining(self):\n        with self._lock:\n            self._refill()\n            self.take(0)\n            return self._tokens\n")
        repo, base = self.seed("W5", {"ratelimit/bucket.py": deadlock, "ratelimit/limiter.py": refs.LIMITER_FIXED})
        original = gr_worker_cases.PYTEST_TIMEOUT
        gr_worker_cases.PYTEST_TIMEOUT = 20
        self.addCleanup(setattr, gr_worker_cases, "PYTEST_TIMEOUT", original)
        self.assertTrue(any("timed out" in item or "fail" in item for item in gr_worker_cases.failures("W5", repo, base)))

    def test_사례_표에_새_사례가_역할별로_들어_있다(self):
        self.assertEqual(gr_cases.ROLE_CASES["worker"][-3:], list(HARD))
        self.assertEqual(gr_cases.ROLE_CASES["researcher"], ["R1", "R2", "R3"])
        for case_id in HARD:
            self.assertIn("at most", gr_cases.worker_assignment(case_id))


class HardResearcherCasesTest(unittest.TestCase):
    SEARCH = '{"type":"web_search_call"}'
    R2_GOOD = ("Type stripping is enabled by default from Node.js v23.6.0 and was backported to v22.18.0; disable it with --no-strip-types. "
               "https://nodejs.org/docs/latest/api/typescript.html")
    R3_GOOD = ("PostgreSQL 15 added the MERGE command. PostgreSQL 17 lets MERGE use a RETURNING clause, and merge_action() names the action. "
               "https://www.postgresql.org/docs/release/17.0/")

    def test_맞는_답은_통과한다(self):
        self.assertEqual(gr_cases.researcher_failures(self.R2_GOOD, self.SEARCH, "R2"), [])
        self.assertEqual(gr_cases.researcher_failures(self.R3_GOOD, self.SEARCH, "R3"), [])

    def test_그럴듯한_오답은_거부한다(self):
        wrong_r2 = [
            "Enabled by default in v23.0.0, backported to v22.7.0, disabled with --no-experimental-strip-types. https://nodejs.org/api/typescript.html",
            "Enabled by default in v23.6.0 and backported to v22.6.0; disable it with --no-strip-types. https://nodejs.org/api/typescript.html",
            "Enabled by default in v23.6.0 and v22.18.0; disable it with --disable-types. https://nodejs.org/api/typescript.html",
        ]
        wrong_r3 = [
            "PostgreSQL 15 added MERGE, PostgreSQL 16 added RETURNING, and merge_action() names the action. https://www.postgresql.org/docs/release/16.0/",
            "PostgreSQL 16 added MERGE and 17 added RETURNING; merge_action() names the action. https://www.postgresql.org/docs/release/17.0/",
            "PostgreSQL 15 added MERGE and 17 added RETURNING; merge_returning() names the action. https://www.postgresql.org/docs/release/17.0/",
        ]
        for answer in wrong_r2:
            self.assertTrue(gr_cases.researcher_failures(answer, self.SEARCH, "R2"), answer)
        for answer in wrong_r3:
            self.assertTrue(gr_cases.researcher_failures(answer, self.SEARCH, "R3"), answer)

    def test_공식_주소와_검색_호출이_없으면_실패다(self):
        self.assertIn("no URL of the official site", gr_cases.researcher_failures(self.R2_GOOD.replace("https://nodejs.org", "https://example.com"), self.SEARCH, "R2"))
        self.assertIn("the rollout shows no web search call", gr_cases.researcher_failures(self.R3_GOOD, "no search", "R3"))

    def test_첫_연구_사례의_채점은_그대로다(self):
        good = "RFC 2119, 1997, Key words for use in RFCs to Indicate Requirement Levels, https://www.rfc-editor.org/rfc/rfc2119"
        self.assertEqual(gr_cases.researcher_failures(good, self.SEARCH), [])
        self.assertEqual(gr_cases.researcher_assignment("R1"), gr_cases.RESEARCH_ASSIGNMENT)
        self.assertEqual(set(gr_research_cases.ASSIGNMENTS), {"R2", "R3"})


if __name__ == "__main__":
    unittest.main()
