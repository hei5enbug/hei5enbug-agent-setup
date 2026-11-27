"""Sections that only some runs need live in conditional references, each reached by exactly one entry line."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_HEADER_LINES = 2

# skill, host file, reference, entry line left behind
MOVED = (
    ("skill-builder", "SKILL.md", "multiple-hosts.md",
     "Before writing a skill for more than one host, read `references/multiple-hosts.md`."),
    ("skill-builder", "SKILL.md", "writing-patterns.md",
     "Before applying writing patterns while drafting, read `references/writing-patterns.md`."),
    ("skill-builder", "SKILL.md", "test-cases.md",
     "Before writing test cases, read `references/test-cases.md`."),
    ("flowchart-design", "SKILL.md", "png-export.md",
     "Before exporting or verifying a PNG, read `references/png-export.md`."),
    ("flowchart-design", "SKILL.md", "groups.md",
     "Before drawing a group or subgroup, read `references/groups.md`."),
    ("orca-plugin-refresh", "SKILL.md", "safety-and-limits.md",
     "Before explaining to the user why the script skipped, deferred, or failed a session, and before a manual finish, read `references/safety-and-limits.md`."),
    ("orca-plugin-refresh", "SKILL.md", "busy-sessions.md",
     "Before asking a question the script returns in `questions`, or running `decide`, read `references/busy-sessions.md`."),
    ("document-to-confluence", "references/confluence-body.md", "confluence-images.md",
     "Before writing a page that has images, read `references/confluence-images.md`."),
    ("document-to-confluence", "references/confluence-body.md", "confluence-inline-comments.md",
     "Before updating a page that holds inline comment markers, read `references/confluence-inline-comments.md`."),
)
KEPT = (
    ("flowchart-design", "SKILL.md", "## 9. Final Checklist"),
    ("orca-plugin-refresh", "SKILL.md", "4. **Report every session.**"),
    ("skill-builder", "SKILL.md", "### Translated mirrors"),
)


def section_of(skill: str, name: str) -> str:
    lines = (ROOT / "skills" / skill / "references" / name).read_text(encoding="utf-8").split("\n")
    return "\n".join(lines[REFERENCE_HEADER_LINES:]).rstrip("\n")


class ConditionalReferenceTest(unittest.TestCase):
    def test_참조_파일은_제목_한_줄_뒤에_옮긴_구간의_제목으로_시작하는_본문을_가진다(self):
        """각 참조 파일이 있고, 첫 줄은 제목, 둘째 줄은 비었으며, 본문은 Markdown 제목 줄로 시작하고 비어 있지 않다."""
        # Given
        for skill, _, name, _ in MOVED:
            with self.subTest(reference=f"{skill}/{name}"):
                # When
                path = ROOT / "skills" / skill / "references" / name
                lines = path.read_text(encoding="utf-8").split("\n")

                # Then
                self.assertTrue(lines[0].startswith("# "))
                self.assertEqual("", lines[1])
                self.assertRegex(lines[REFERENCE_HEADER_LINES], r"^#{2,3} \S")
                self.assertGreater(len(section_of(skill, name).split("\n")), 3)

    def test_입구_줄은_한_번만_있고_그_자리에_참조를_합치면_구간_제목이_한_번_나타난다(self):
        """입구 줄이 옮긴 구간 자리에 정확히 한 번 남고, 합친 본문에 옮긴 구간의 제목이 한 번만 있다."""
        # Given
        for skill, host, name, entry in MOVED:
            with self.subTest(reference=f"{skill}/{name}"):
                host_lines = (ROOT / "skills" / skill / host).read_text(encoding="utf-8").split("\n")
                section = section_of(skill, name)
                heading = section.split("\n", 1)[0]

                # When
                joined = "\n".join(section if line == entry else line for line in host_lines)

                # Then
                self.assertEqual(1, host_lines.count(entry))
                self.assertEqual(0, host_lines.count(heading))
                self.assertEqual(1, joined.split("\n").count(heading))

    def test_모든_실행이_쓰는_구간은_항상_읽는_본문에_남는다(self):
        """최종 체크리스트, 상태 용어집, 번역본 구간은 조건부 참조로 옮기지 않는다."""
        # Given
        for skill, host, line in KEPT:
            with self.subTest(section=line):
                # When
                lines = (ROOT / "skills" / skill / host).read_text(encoding="utf-8").split("\n")

                # Then
                self.assertTrue(any(item.startswith(line) for item in lines))


if __name__ == "__main__":
    unittest.main()
