import json
import shutil
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).parents[1]


class DecisionNavigatorEvalFixtureTest(unittest.TestCase):
    def test_평가_보관소를_임시_작업에_복사할_수_있다(self):
        """평가 보관소를 임시 작업에 복사할 수 있다."""
        # Given
        eval_path = SKILL_ROOT / "evals" / "evals.json"
        frontier_fixture = SKILL_ROOT / "evals" / "files" / "frontier-100"
        race_fixture = SKILL_ROOT / "evals" / "files" / "frontier-race"

        # When
        suite = json.loads(eval_path.read_text())
        cases = suite["evals"]
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_effort = Path(temporary_directory) / ".decision-navigator" / "retries"
            temporary_effort.parent.mkdir()
            shutil.copytree(frontier_fixture, temporary_effort)

            # Then
            self.assertEqual(suite["skill_name"], "decision-navigator")
            self.assertEqual([case["id"] for case in cases], [1, 2, 3, 4, 5, 6, 7])
            self.assertTrue(all(case["expected_output"] and case["expectations"] for case in cases))
            self.assertEqual(cases[3]["files"], ["evals/files/frontier-100/"])
            self.assertEqual(cases[5]["files"], ["evals/files/frontier-race/"])
            self.assertEqual(len(list(temporary_effort.glob("tickets/*.md"))), 100)
            self.assertTrue((temporary_effort / "tickets" / "92-first-frontier.md").is_file())
            self.assertTrue(
                (temporary_effort / "claims" / "91-claimed-ticket.lock" / "claim.json").is_file()
            )
            self.assertTrue((race_fixture / "tickets" / "01-backoff-policy.md").is_file())


if __name__ == "__main__":
    unittest.main()
