"""Regression checks for skill-builder agent prompts that emit structured JSON artifacts.

These checks reject fenced JSON examples in the declared artifact prompts and require an explicit path to
the canonical schema document. Semantic duplication outside that syntax remains a review concern.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL = SKILL_DIR / "SKILL.md"
SCHEMAS = SKILL_DIR / "references" / "schemas.md"
ARTIFACT_PROMPTS = {
    "analysis.json": SKILL_DIR / "agents" / "analyzer.md",
    "comparison.json": SKILL_DIR / "agents" / "comparator.md",
    "grading.json": SKILL_DIR / "agents" / "grader.md",
}
FENCED_JSON_BLOCK = re.compile(
    r"^[ \t]*```[ \t]*json[ \t]*\r?\n.*?^[ \t]*```[ \t]*$",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)


class SchemaSingleSourceTest(unittest.TestCase):
    def test_declared_artifact_prompts_do_not_embed_fenced_json_examples(self):
        for artifact, prompt in ARTIFACT_PROMPTS.items():
            with self.subTest(artifact=artifact, prompt=prompt.name):
                self.assertEqual(FENCED_JSON_BLOCK.findall(prompt.read_text(encoding="utf-8")), [])

    def test_each_artifact_prompt_points_at_its_schema_with_an_explicit_root(self):
        for artifact, prompt in ARTIFACT_PROMPTS.items():
            with self.subTest(artifact=artifact, prompt=prompt.name):
                text = prompt.read_text(encoding="utf-8")
                self.assertIn("**skill_builder_path**", text)
                self.assertIn("{skill_builder_path}/references/schemas.md", text)
                self.assertIn(f"`{artifact}`", text)

    def test_the_skill_passes_the_explicit_root_to_artifact_agents(self):
        text = SKILL.read_text(encoding="utf-8")
        paragraphs = [
            paragraph
            for paragraph in text.split("\n\n")
            if "Pass the resolved value as `skill_builder_path`" in paragraph
        ]
        self.assertEqual(len(paragraphs), 1)
        for prompt in ARTIFACT_PROMPTS.values():
            with self.subTest(prompt=prompt.name):
                self.assertIn(f"`agents/{prompt.name}`", paragraphs[0])

    def test_each_artifact_prompt_states_the_missing_schema_behavior(self):
        for artifact, prompt in ARTIFACT_PROMPTS.items():
            with self.subTest(artifact=artifact, prompt=prompt.name):
                self.assertRegex(prompt.read_text(encoding="utf-8"), r"(?i)unavailable|missing")

    def test_the_schema_document_defines_each_declared_artifact(self):
        text = SCHEMAS.read_text(encoding="utf-8")
        for artifact in ARTIFACT_PROMPTS:
            with self.subTest(artifact=artifact):
                self.assertIn(f"## {artifact}", text)

    def test_the_schema_document_keeps_the_field_documentation(self):
        text = SCHEMAS.read_text(encoding="utf-8")
        for field in ("`eval_feedback`", "`expectation_results`", "`improvement_suggestions[].category`"):
            with self.subTest(field=field):
                self.assertIn(field, text)

    def test_benchmark_notes_keep_their_small_contract_inline(self):
        text = ARTIFACT_PROMPTS["analysis.json"].read_text(encoding="utf-8")
        benchmark_section = text.split("# Analyzing Benchmark Results", 1)[1]
        self.assertNotIn("references/schemas.md", benchmark_section)
        self.assertIn("JSON array of strings", benchmark_section)


if __name__ == "__main__":
    unittest.main()
