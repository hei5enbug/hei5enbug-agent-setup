import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "local_lock.py"


class LocalLockTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / ".decision-navigator" / "billing"
        self.tickets = self.root / "tickets"
        self.tickets.mkdir(parents=True)
        self.map = self.root / "map.md"
        self.map.write_text("# Billing map\n")
        self.ticket = self.tickets / "01-first-question.md"
        self.ticket.write_text(
            "# First question\n\nType: grilling\nStatus: open\nBlocked by:\n"
        )

    def tearDown(self):
        self.temp.cleanup()

    def run_lock(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, args)],
            capture_output=True,
            text=True,
        )

    def test_only_one_concurrent_ticket_claim_succeeds(self):
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "claim",
                    str(self.ticket),
                    "--owner",
                    f"worker-{index}",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for index in range(8)
        ]
        results = [process.communicate() + (process.returncode,) for process in processes]
        self.assertEqual(sum(result[2] == 0 for result in results), 1)

    def test_release_requires_matching_owner(self):
        claimed = self.run_lock("claim", self.ticket, "--owner", "session-a")
        self.assertEqual(claimed.returncode, 0)

        wrong = self.run_lock("release", self.ticket, "--owner", "session-b")
        self.assertNotEqual(wrong.returncode, 0)

        released = self.run_lock("release", self.ticket, "--owner", "session-a")
        self.assertEqual(released.returncode, 0)
        self.assertTrue(json.loads(released.stdout)["released"])

    def test_map_lock_is_independent(self):
        ticket_claim = self.run_lock("claim", self.ticket, "--owner", "session-a")
        map_claim = self.run_lock("claim", self.map, "--owner", "session-a")
        self.assertEqual(ticket_claim.returncode, 0)
        self.assertEqual(map_claim.returncode, 0)

    def test_resolved_ticket_cannot_be_claimed(self):
        self.ticket.write_text(
            "# First question\n\nType: grilling\nStatus: resolved\nBlocked by:\n"
        )
        result = self.run_lock("claim", self.ticket, "--owner", "session-a")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Ticket is not open", result.stderr)

    def test_unsafe_lock_path_is_refused(self):
        claims = self.root / "claims"
        claims.mkdir()
        (claims / "01-first-question.lock").write_text("not a directory")
        result = self.run_lock("claim", self.ticket, "--owner", "session-a")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsafe lock path", result.stderr)


if __name__ == "__main__":
    unittest.main()
