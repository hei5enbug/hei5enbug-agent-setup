"""Every skill description is loaded into every session, so a description over the limit fails and names its skill."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MAX_DESCRIPTION_CHARACTERS = 700


def descriptions() -> dict[str, str]:
    found = {}
    for path in sorted((ROOT / "skills").glob("*/SKILL.md")):
        front = yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])
        found[path.parent.name] = " ".join(str(front["description"]).split())
    return found


class SkillDescriptionLengthTest(unittest.TestCase):
    def test_모든_스킬_설명은_700자_이하다(self):
        """각 skills/*/SKILL.md의 description이 700자를 넘으면 그 스킬 이름과 글자 수를 대며 실패한다."""
        # Given
        found = descriptions()

        # When
        too_long = {name: len(text) for name, text in found.items() if len(text) > MAX_DESCRIPTION_CHARACTERS}

        # Then
        self.assertTrue(found)
        self.assertEqual({}, too_long, f"descriptions over {MAX_DESCRIPTION_CHARACTERS} characters")


if __name__ == "__main__":
    unittest.main()
