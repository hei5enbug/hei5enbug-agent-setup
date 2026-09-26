import json
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).parents[1]


class DeepInterviewEvalFixtureTest(unittest.TestCase):
    def test_평가_케이스가_상태_흐름과_입력_파일을_보존한다(self):
        """Deep Interview 평가 케이스가 상태 흐름과 입력 파일을 보존한다."""
        # Given
        eval_path = SKILL_ROOT / "evals" / "evals.json"

        # When
        suite = json.loads(eval_path.read_text())
        cases = suite["evals"][:13]
        case_ids = [case["id"] for case in cases]
        input_paths = [path for case in cases for path in case["files"]]

        # Then
        self.assertEqual(suite["skill_name"], "clarify-requirements")
        self.assertEqual(case_ids, list(range(1, 14)))
        self.assertEqual(len(case_ids), len(set(case_ids)))
        self.assertTrue(all(case["expected_output"] and case["expectations"] for case in cases))
        self.assertTrue(all((SKILL_ROOT / path).is_file() for path in input_paths))
        self.assertTrue(
            (SKILL_ROOT / "evals" / "operator-guides" / "brownfield-ten-rounds.md").is_file()
        )
        self.assertNotIn(
            "evals/operator-guides/brownfield-ten-rounds.md",
            input_paths,
        )


if __name__ == "__main__":
    unittest.main()
