from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION = REPO_ROOT / "instructions/implementation-planning.md"
VALIDATION = REPO_ROOT / "instructions/independent-model-validation.md"
DESIGN = REPO_ROOT / "skills/technical-design-writer/references/design-documents.md"
DESIGN_SKILL = REPO_ROOT / "skills/technical-design-writer/SKILL.md"


class PlanningContractTest(unittest.TestCase):
    def test_implementation_plan_has_six_ordered_stages(self):
        headings = re.findall(r"^## ([1-6])\. (.+)$", IMPLEMENTATION.read_text(), re.MULTILINE)
        self.assertEqual([number for number, _ in headings], list("123456"))
        self.assertEqual(len(headings), 6)

    def test_workflows_are_separate(self):
        implementation = IMPLEMENTATION.read_text()
        design = DESIGN.read_text()
        skill = DESIGN_SKILL.read_text()
        self.assertNotIn("Design document workflow", implementation)
        self.assertNotIn("Implementation planning", design)
        self.assertIn("Implementation planning", implementation)
        self.assertIn("Design document workflow", design)
        self.assertNotIn("## Workflow", skill)
        self.assertIn("references/design-documents.md", skill)

    def test_model_selection_has_one_canonical_source(self):
        validation = VALIDATION.read_text()
        self.assertIn("Latest available Claude Fable", validation)
        self.assertIn("Latest available GPT Sol", validation)
        for path in (IMPLEMENTATION, DESIGN):
            text = path.read_text()
            self.assertNotIn("Claude Fable", text)
            self.assertNotIn("GPT Sol", text)

        signatures = (
            "Latest available Claude Fable",
            "Latest available GPT Sol",
            "exactly one reviewer from the other model family",
            "This is one validation pass, not a debate",
        )
        for root in (REPO_ROOT / "instructions", REPO_ROOT / "skills"):
            for path in root.rglob("*.md"):
                if path.name.endswith(".ko.md") or path == VALIDATION:
                    continue
                with self.subTest(path=path.relative_to(REPO_ROOT)):
                    text = path.read_text()
                    for signature in signatures:
                        self.assertNotIn(signature, text)

    def test_validation_is_one_pass_and_read_only(self):
        validation = VALIDATION.read_text()
        self.assertIn("exactly one reviewer", validation)
        self.assertIn("read-only session", validation)
        self.assertIn("not a debate", validation)
        self.assertIn("do not substitute", validation)


if __name__ == "__main__":
    unittest.main()
