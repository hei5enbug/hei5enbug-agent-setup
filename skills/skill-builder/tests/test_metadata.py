"""SKILL.md metadata parsing and validation."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))

from scripts import quick_validate as qv  # noqa: E402
from scripts.utils import parse_skill_md  # noqa: E402

REPO_ROOT = SKILL_DIR.parents[1]


def write_skill(root: Path, frontmatter: str, name: str = "demo") -> Path:
    skill = root / name
    skill.mkdir(exist_ok=True)
    (skill / "SKILL.md").write_text(f"---\n{frontmatter}\n---\nBody\n")
    return skill


class ValidateSkillTest(unittest.TestCase):
    def test_non_string_keys_are_rejected(self):
        """문자열이 아닌 키는 검증 오류로 반환한다."""
        # Given
        skill = write_skill(self.root, "name: demo\ndescription: Example\n1: value\nunknown: value")
        # When
        valid, message = qv.validate_skill(skill)
        # Then
        self.assertFalse(valid)
        self.assertIn("Unexpected key", message)

    def test_falsey_compatibility_values_are_rejected(self):
        """비어 보이는 값이라도 compatibility는 문자열이어야 한다."""
        for value in ("false", "0", "[]", "{}", "null"):
            with self.subTest(value=value):
                # Given
                skill = write_skill(self.root, f"name: demo\ndescription: Example\ncompatibility: {value}")
                # When
                valid, message = qv.validate_skill(skill)
                # Then
                self.assertFalse(valid)
                self.assertIn("Compatibility must be a string", message)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_empty_name_and_description_are_rejected(self):
        skill = write_skill(self.root, 'name: ""\ndescription: ""')
        valid, message = qv.validate_skill(skill)
        self.assertFalse(valid)
        self.assertIn("Name cannot be empty", message)

    def test_whitespace_description_is_rejected(self):
        skill = write_skill(self.root, 'name: demo\ndescription: "   "')
        valid, message = qv.validate_skill(skill)
        self.assertFalse(valid)
        self.assertIn("Description cannot be empty", message)

    def test_valid_skill_passes(self):
        skill = write_skill(self.root, "name: demo\ndescription: Does a thing.")
        self.assertEqual(qv.validate_skill(skill), (True, "Skill is valid!"))

    def test_non_string_description_is_rejected(self):
        skill = write_skill(self.root, "name: demo\ndescription: false")
        valid, message = qv.validate_skill(skill)
        self.assertFalse(valid)
        self.assertIn("Description must be a string", message)

    def test_all_repository_skills_pass(self):
        skill_dirs = sorted(p.parent for p in REPO_ROOT.glob("skills/*/SKILL.md"))
        skill_dirs += sorted(p.parent for p in REPO_ROOT.glob("standalone-skills/*/SKILL.md"))
        self.assertTrue(skill_dirs, "No repository skills found")
        for skill in skill_dirs:
            with self.subTest(skill=skill.name):
                self.assertEqual(qv.validate_skill(skill), (True, "Skill is valid!"))


class ParserContractTest(unittest.TestCase):
    def test_fallback_parser_is_gone(self):
        with patch.object(qv, "yaml", None):
            with self.assertRaises(qv.MissingDependencyError):
                qv.parse_frontmatter("name: demo")

    def test_missing_pyyaml_exits_with_code_2(self):
        with tempfile.TemporaryDirectory() as td:
            skill = write_skill(Path(td), "name: demo\ndescription: Does a thing.")
            shim = Path(td) / "shim"
            shim.mkdir()
            (shim / "yaml.py").write_text("raise ModuleNotFoundError('No module named yaml')\n")
            completed = subprocess.run(
                [sys.executable, str(SKILL_DIR / "scripts" / "quick_validate.py"), str(skill)],
                capture_output=True,
                text=True,
                env={"PATH": "", "PYTHONPATH": str(shim)},
            )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("pip install pyyaml", completed.stderr)

    def test_model_backed_clis_report_missing_pyyaml_without_traceback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            skill = write_skill(root, "name: demo\ndescription: Does a thing.")
            shim = root / "shim"
            shim.mkdir()
            (shim / "yaml.py").write_text("raise ModuleNotFoundError('No module named yaml')\n")
            eval_set = root / "eval.json"
            eval_set.write_text('[{"query":"q","should_trigger":true}]')
            eval_results = root / "results.json"
            eval_results.write_text(
                '{"description":"Does a thing.","summary":{"passed":0,"total":1},"results":[]}'
            )
            scripts = SKILL_DIR / "scripts"
            commands = [
                [
                    sys.executable,
                    str(scripts / "run_eval.py"),
                    "--eval-set", str(eval_set),
                    "--skill-path", str(skill),
                    "--runner-command", "unused",
                ],
                [
                    sys.executable,
                    str(scripts / "run_loop.py"),
                    "--eval-set", str(eval_set),
                    "--skill-path", str(skill),
                    "--runner-command", "unused",
                    "--report", "none",
                ],
                [
                    sys.executable,
                    str(scripts / "improve_description.py"),
                    "--eval-results", str(eval_results),
                    "--skill-path", str(skill),
                    "--runner-command", "unused",
                ],
            ]
            for command in commands:
                with self.subTest(script=Path(command[1]).name):
                    completed = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        env={"PATH": "", "PYTHONPATH": str(shim)},
                    )
                    self.assertEqual(completed.returncode, 2, completed.stderr)
                    self.assertIn("pip install pyyaml", completed.stderr)
                    self.assertNotIn("Traceback", completed.stderr)

    def test_validator_and_utils_agree_on_commented_description(self):
        with tempfile.TemporaryDirectory() as td:
            skill = write_skill(Path(td), 'name: demo\ndescription: "hello" # note')
            _, description, _ = parse_skill_md(skill)
        parsed = qv.parse_frontmatter('name: demo\ndescription: "hello" # note')
        self.assertEqual(description, "hello")
        self.assertEqual(parsed["description"], "hello")

    def test_utils_rejects_non_string_description(self):
        with tempfile.TemporaryDirectory() as td:
            skill = write_skill(Path(td), "name: demo\ndescription: false")
            with self.assertRaises(ValueError):
                parse_skill_md(skill)

    def test_utils_reads_folded_description(self):
        with tempfile.TemporaryDirectory() as td:
            skill = write_skill(Path(td), "name: demo\ndescription: >-\n  first line\n  second line")
            name, description, content = parse_skill_md(skill)
        self.assertEqual(name, "demo")
        self.assertEqual(description, "first line second line")
        self.assertTrue(content.startswith("---"))


class BundledCheckTimeoutTest(unittest.TestCase):
    def test_hanging_check_is_reported_as_timeout(self):
        with tempfile.TemporaryDirectory() as td:
            skill = write_skill(Path(td), "name: demo\ndescription: Does a thing.")
            scripts = skill / "scripts"
            scripts.mkdir()
            (scripts / "check_hang.py").write_text(
                textwrap.dedent(
                    """
                    import time
                    time.sleep(30)
                    """
                ).lstrip()
            )
            (scripts / "check_ok.py").write_text("raise SystemExit(0)\n")
            ok, results = qv.run_bundled_checks(skill, timeout_seconds=0.5)
        self.assertFalse(ok)
        by_name = {name: (code, output) for name, code, output in results}
        self.assertIs(by_name["check_hang.py"][0], qv.CHECK_TIMEOUT_RETURNCODE)
        self.assertIn("timed out", by_name["check_hang.py"][1])
        self.assertEqual(qv.check_status(by_name["check_hang.py"][0]), "TIMEOUT")
        self.assertEqual(by_name["check_ok.py"][0], 0)


if __name__ == "__main__":
    unittest.main()
