"""Cross-skill reference policy.

A skill may read a sibling skill's reference file, but the path must resolve from the skill's own
directory and must never name a host installation root. These checks run over every skill in the
repository so a rename or a move cannot leave a dangling reference behind.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOTS = ("skills", "standalone-skills")

# `../<skill-name>/<path>` written in backticks, a Markdown link, or plain prose.
SIBLING_PATTERN = re.compile(r"\.\./([A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+)")
# Host installation roots a portable skill must never hardcode.
HOST_ROOT_PATTERN = re.compile(r"~/\.(claude|codex|gjc)/|~/\.config/opencode/")


def skill_dirs() -> list[Path]:
    dirs: list[Path] = []
    for root in SKILL_ROOTS:
        dirs.extend(sorted(p.parent for p in (REPO_ROOT / root).glob("*/SKILL.md")))
    return dirs


def documents(skill: Path) -> list[Path]:
    return [p for p in sorted(skill.rglob("*.md")) if "tests" not in p.relative_to(skill).parts]


class SiblingReferenceTest(unittest.TestCase):
    def test_repository_has_skills_to_check(self):
        self.assertGreaterEqual(len(skill_dirs()), 2)

    def test_every_sibling_reference_resolves_from_the_skill_root(self):
        """`../x/y.md` is always anchored at the skill directory, whatever file spells it."""
        checked = 0
        for skill in skill_dirs():
            for document in documents(skill):
                for match in SIBLING_PATTERN.finditer(document.read_text()):
                    relative = match.group(1)
                    target = (skill / ".." / relative).resolve()
                    with self.subTest(source=str(document.relative_to(REPO_ROOT)), target=relative):
                        self.assertTrue(
                            target.exists(),
                            f"sibling reference does not resolve: ../{relative}",
                        )
                        self.assertTrue(
                            target.is_relative_to(skill.parent),
                            f"sibling reference escapes the skill root: ../{relative}",
                        )
                        checked += 1
        self.assertGreater(checked, 0, "no sibling reference found; the pattern may have changed")

    def test_no_skill_hardcodes_a_host_installation_root(self):
        for skill in skill_dirs():
            for document in documents(skill):
                match = HOST_ROOT_PATTERN.search(document.read_text())
                with self.subTest(source=str(document.relative_to(REPO_ROOT))):
                    self.assertIsNone(
                        match,
                        f"hardcoded host skill root: {match.group(0) if match else ''}",
                    )

    def test_declared_sibling_readers_state_the_missing_file_behavior(self):
        """A skill that reads a sibling file must say what happens when the file is absent."""
        for skill in skill_dirs():
            reads_sibling = any(
                SIBLING_PATTERN.search(document.read_text()) for document in documents(skill)
            )
            if not reads_sibling:
                continue
            declaration = (skill / "SKILL.md").read_text()
            with self.subTest(skill=skill.name):
                self.assertRegex(declaration, r"\.\./[A-Za-z0-9._-]+/")
                self.assertRegex(declaration, r"(?i)absent|missing|unavailable")


if __name__ == "__main__":
    unittest.main()
