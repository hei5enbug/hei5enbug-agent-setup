from __future__ import annotations

import os
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_ENGLISH = {
    REPO_ROOT / "skills/skill-builder/references/schemas.md",
}
NON_ENGLISH_DOCUMENTS = {
    REPO_ROOT / ".plan/orca-plugin-refresh-resume/implementation-plan.md",
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


def is_eval_fixture(path: Path) -> bool:
    return any(parent.name == "files" and parent.parent.name == "evals" for parent in path.parents)


def english_sources():
    return sorted(
        path
        for path in REPO_ROOT.rglob("*.md")
        if EXCLUDED_DIRECTORIES.isdisjoint(path.parts)
        and not path.name.endswith(".ko.md")
        and path not in EXCLUDED_ENGLISH
        and path not in NON_ENGLISH_DOCUMENTS
        and path not in NON_ENGLISH_READMES
        and not is_eval_fixture(path)
    )


def mirror_for(source):
    if source == REPO_ROOT / "README.md":
        return REPO_ROOT / "README.ko.md"
    if source.parent == REPO_ROOT / "agents":
        return source.parent / "ko" / f"{source.stem}.ko.md"
    return source.with_name(f"{source.stem}.ko.md")


class KoreanMirrorTest(unittest.TestCase):
    def test_영어_markdown에는_의미가_같은_한국어_미러가_있다(self):
        """사람이 읽는 영어 Markdown마다 의미가 같은 한국어 미러가 존재한다."""
        # Given
        sources = english_sources()
        self.assertTrue(sources)
        mirrors = [(source, mirror_for(source)) for source in sources]

        # When
        observed = [(source, mirror, mirror.is_file()) for source, mirror in mirrors]

        # Then
        for source, mirror, exists in observed:
            with self.subTest(source=source.relative_to(REPO_ROOT)):
                self.assertTrue(exists, f"missing Korean mirror: {mirror}")
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

    def test_스키마와_한국어_문서는_미러_원본에서_제외한다(self):
        """스키마와 이미 한국어로 작성된 문서는 번역 미러 원본에서 제외한다."""
        # Given
        sources = set(english_sources())

        # When
        excluded_sources = EXCLUDED_ENGLISH | NON_ENGLISH_DOCUMENTS | NON_ENGLISH_READMES

        # Then
        self.assertTrue(EXCLUDED_ENGLISH.isdisjoint(sources))
        self.assertTrue(NON_ENGLISH_DOCUMENTS.isdisjoint(sources))
        self.assertTrue(NON_ENGLISH_READMES.isdisjoint(sources))
        self.assertTrue(excluded_sources.isdisjoint(sources))

    def test_평가_입력에는_미러가_필요_없고_운영_안내서는_필요하다(self):
        # Given
        fixture = REPO_ROOT / "skills/deep-interview/evals/files/billing-service/README.md"
        operator_guide = REPO_ROOT / "skills/deep-interview/evals/operator-guides/brownfield-ten-rounds.md"

        # When
        sources = set(english_sources())

        # Then
        self.assertTrue(fixture.is_file())
        self.assertTrue(operator_guide.is_file())
        self.assertNotIn(fixture, sources)
        self.assertIn(operator_guide, sources)


if __name__ == "__main__":
    unittest.main()
