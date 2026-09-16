from __future__ import annotations

import os
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_ENGLISH = {
    REPO_ROOT / "skills/skill-builder/references/schemas.md",
}
NON_ENGLISH_READMES = {
    REPO_ROOT / "README.de.md",
    REPO_ROOT / "README.es.md",
    REPO_ROOT / "README.fr.md",
    REPO_ROOT / "README.ja.md",
    REPO_ROOT / "README.ko.md",
    REPO_ROOT / "README.zh-CN.md",
}
EXCLUDED_DIRECTORIES = {".git", ".pytest_cache", ".decision-navigator"}
LINK_PATTERN = re.compile(r"\]\(([^)]+)\)")


def english_sources():
    return sorted(
        path
        for path in REPO_ROOT.rglob("*.md")
        if EXCLUDED_DIRECTORIES.isdisjoint(path.parts)
        and not path.name.endswith(".ko.md")
        and path not in EXCLUDED_ENGLISH
        and path not in NON_ENGLISH_READMES
    )


def mirror_for(source):
    if source == REPO_ROOT / "README.md":
        return REPO_ROOT / "README.ko.md"
    if source.parent == REPO_ROOT / "agents":
        return source.parent / "ko" / f"{source.stem}.ko.md"
    return source.with_name(f"{source.stem}.ko.md")


class KoreanMirrorTest(unittest.TestCase):
    def test_every_human_readable_english_markdown_has_a_korean_mirror(self):
        sources = english_sources()
        self.assertTrue(sources)
        for source in sources:
            mirror = mirror_for(source)
            with self.subTest(source=source.relative_to(REPO_ROOT)):
                self.assertTrue(mirror.is_file(), f"missing Korean mirror: {mirror}")
                text = mirror.read_text(encoding="utf-8")
                self.assertIn("영어 원본:", text)
                self.assertIn("비권위", text)
                relative = Path(os.path.relpath(source, mirror.parent)).as_posix()
                self.assertIn(f"]({relative})", text)

    def test_executable_markdown_never_links_to_a_korean_mirror(self):
        for source in english_sources():
            if source == REPO_ROOT / "README.md":
                continue
            for target in LINK_PATTERN.findall(source.read_text(encoding="utf-8")):
                with self.subTest(source=source.relative_to(REPO_ROOT), target=target):
                    self.assertFalse(target.split("#", 1)[0].endswith(".ko.md"))

    def test_schema_and_non_english_documents_are_not_mirror_sources(self):
        sources = set(english_sources())
        self.assertTrue(EXCLUDED_ENGLISH.isdisjoint(sources))
        self.assertTrue(NON_ENGLISH_READMES.isdisjoint(sources))


if __name__ == "__main__":
    unittest.main()
