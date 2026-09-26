from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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


def markdown_files(root):
    try:
        listed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*.md"],
            check=True,
            capture_output=True,
        ).stdout.decode("utf-8")
    except (OSError, subprocess.CalledProcessError):
        return list(root.rglob("*.md"))
    return [root / name for name in listed.split("\0") if name]


def english_sources(root=REPO_ROOT):
    return sorted(
        path
        for path in markdown_files(root)
        if path.is_file()
        and EXCLUDED_DIRECTORIES.isdisjoint(path.relative_to(root).parts)
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


class MarkdownDiscoveryTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()

    def write(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Guide\n", encoding="utf-8")
        return path

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)

    def test_git이_무시하는_markdown은_미러_원본에서_제외한다(self):
        """git이 무시하는 로컬 도구 폴더의 Markdown은 미러 검사 대상이 아니다."""
        # Given
        self.git("init", "-q")
        (self.root / ".gitignore").write_text("local-cache/\n", encoding="utf-8")
        ignored = self.write("local-cache/README.md")
        tracked = self.write("docs/guide.md")
        self.git("add", "docs/guide.md")

        # When
        sources = english_sources(self.root)

        # Then
        self.assertIn(tracked, sources)
        self.assertNotIn(ignored, sources)

    def test_아직_추가하지_않은_새_markdown도_미러_원본에_포함한다(self):
        """커밋 전에 새로 만든 Markdown도 미러가 없으면 잡아내도록 검사 대상에 넣는다."""
        # Given
        self.git("init", "-q")
        created = self.write("docs/new.md")

        # When
        sources = english_sources(self.root)

        # Then
        self.assertEqual(sources, [created])

    def test_작업_트리에서_지운_추적_markdown은_검사하지_않는다(self):
        """git 색인에만 남고 실제로 지운 Markdown은 미러 검사 대상이 아니다."""
        # Given
        self.git("init", "-q")
        deleted = self.write("docs/deleted.md")
        self.git("add", "docs/deleted.md")
        deleted.unlink()

        # When
        sources = english_sources(self.root)

        # Then
        self.assertEqual(sources, [])

    def test_git을_실행할_수_없으면_폴더_전체를_훑는다(self):
        """git을 쓸 수 없는 환경에서도 Markdown을 빠짐없이 검사한다."""
        # Given
        nested = self.write("docs/nested/guide.md")
        skipped = self.write(".git/notes.md")

        # When
        with patch.object(subprocess, "run", side_effect=FileNotFoundError("git")):
            sources = english_sources(self.root)

        # Then
        self.assertEqual(sources, [nested])
        self.assertNotIn(skipped, sources)


if __name__ == "__main__":
    unittest.main()
