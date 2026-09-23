"""Skill packaging: file boundaries, output location, and installed-copy checks."""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))

from scripts import package_skill  # noqa: E402

REPO_ROOT = SKILL_DIR.parents[1]


def make_skill(root: Path, name: str = "demo") -> Path:
    skill = root / name
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: demo\ndescription: Does a thing.\n---\nBody\n")
    (skill / "references").mkdir()
    (skill / "references" / "guide.md").write_text("guide\n")
    return skill


def quiet_package(*args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()) as buffer:
        result = package_skill.package_skill(*args, **kwargs)
    return result, buffer.getvalue()


class PackageBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.skill = make_skill(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_secrets_and_symlinks_are_not_packaged(self):
        external = self.root / "outside-dummy.txt"
        external.write_text("DUMMY-NOT-A-SECRET")
        (self.skill / "outside.txt").symlink_to(external)
        (self.skill / "linked-dir").symlink_to(self.root, target_is_directory=True)
        (self.skill / ".env").write_text("DUMMY=synthetic")
        (self.skill / ".env.local").write_text("DUMMY=synthetic")
        (self.skill / "old.skill").write_bytes(b"zip")
        (self.skill / ".git").mkdir()
        (self.skill / ".git" / "HEAD").write_text("ref")
        (self.skill / "evals").mkdir()
        (self.skill / "evals" / "evals.json").write_text("[]")
        (self.skill / "demo-workspace").mkdir()
        (self.skill / "demo-workspace" / "feedback.json").write_text("{}")

        packaged, output = quiet_package(self.skill, self.root / "dist")

        self.assertIsNotNone(packaged)
        with zipfile.ZipFile(packaged) as zf:
            names = sorted(zf.namelist())
        self.assertEqual(names, ["demo/SKILL.md", "demo/references/guide.md"])
        self.assertIn("Skipped symbolic link: demo/outside.txt", output)
        self.assertIn("Skipped symbolic link: demo/linked-dir", output)

    def test_output_inside_skill_fails_before_writing(self):
        packaged, output = quiet_package(self.skill, self.skill / "dist")
        self.assertIsNone(packaged)
        self.assertIn("inside the skill folder", output)
        self.assertFalse((self.skill / "dist").exists())

    def test_home_is_not_scanned_without_option(self):
        with patch.object(package_skill, "find_installed_copies") as finder:
            packaged, _ = quiet_package(self.skill, self.root / "dist")
        self.assertIsNotNone(packaged)
        finder.assert_not_called()

    def test_packaging_runs_metadata_validation_and_bundle_checks_once(self):
        """패키징은 메타데이터와 번들 검사를 각각 한 번 수행한다."""
        # given
        with patch.object(package_skill, "validate_skill", wraps=package_skill.validate_skill) as validate:
            with patch.object(package_skill, "run_bundled_checks", wraps=package_skill.run_bundled_checks) as checks:
                # when
                packaged, _ = quiet_package(self.skill, self.root / "dist")

        # then
        self.assertIsNotNone(packaged)
        self.assertEqual(validate.call_count, 1)
        self.assertEqual(checks.call_count, 1)

    def test_check_installed_compares_every_file(self):
        installed_root = self.root / "installed" / "skills"
        installed = installed_root / "demo"
        installed.mkdir(parents=True)
        (installed / "SKILL.md").write_text((self.skill / "SKILL.md").read_text())
        (installed / "references").mkdir()
        (installed / "references" / "guide.md").write_text("older guide\n")

        with patch.dict(os.environ, {"SKILL_BUILDER_SKILL_ROOTS": str(installed_root)}):
            packaged, output = quiet_package(self.skill, self.root / "dist", check_installed=True)

        self.assertIsNotNone(packaged)
        self.assertIn(f"[stale] {installed.resolve()}", output)

        (installed / "references" / "guide.md").write_text("guide\n")
        with patch.dict(os.environ, {"SKILL_BUILDER_SKILL_ROOTS": str(installed_root)}):
            _, output = quiet_package(self.skill, self.root / "dist", check_installed=True)
        self.assertIn(f"[same] {installed.resolve()}", output)

    def test_failed_package_preserves_existing_artifact(self):
        output_dir = self.root / "dist"
        output_dir.mkdir()
        artifact = output_dir / "demo.skill"
        original = b"previous-good-artifact"
        artifact.write_bytes(original)

        with patch.object(package_skill.zipfile.ZipFile, "write", side_effect=OSError("synthetic failure")):
            packaged, output = quiet_package(self.skill, output_dir)

        self.assertIsNone(packaged)
        self.assertIn("synthetic failure", output)
        self.assertEqual(artifact.read_bytes(), original)
        self.assertEqual(list(output_dir.glob(".*.skill.tmp")), [])


class RepositorySkillsPackageTest(unittest.TestCase):
    def test_every_repository_skill_packages_with_skill_md(self):
        skill_dirs = sorted(p.parent for p in REPO_ROOT.glob("skills/*/SKILL.md"))
        skill_dirs += sorted(p.parent for p in REPO_ROOT.glob("standalone-skills/*/SKILL.md"))
        self.assertTrue(skill_dirs, "No repository skills found")
        with tempfile.TemporaryDirectory() as td:
            for skill in skill_dirs:
                with self.subTest(skill=skill.name):
                    packaged, _ = quiet_package(skill, Path(td))
                    self.assertIsNotNone(packaged)
                    with zipfile.ZipFile(packaged) as zf:
                        names = zf.namelist()
                    self.assertIn(f"{skill.name}/SKILL.md", names)
                    self.assertFalse(any("/evals/" in n or "__pycache__" in n for n in names))


if __name__ == "__main__":
    unittest.main()
