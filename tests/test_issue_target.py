#!/usr/bin/env python3
"""이 저장소가 skill-issue-creator 스킬에 선언한 이슈 대상이 기대한 값과 같은지 검사한다."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "skill-issue-creator" / "scripts" / "find_tracker.py"
SKILL = ROOT / "skills" / "skill-issue-creator"


class IssueTargetTest(unittest.TestCase):
    def test_repository_declares_its_github_tracker(self) -> None:
        """저장소는 자신의 GitHub 추적기를 공개 저장소로 선언하고 미리보기를 요구하지 않는다."""
        # Given
        command = [sys.executable, str(SCRIPT), str(SKILL)]
        # When
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
        # Then
        self.assertEqual(0, result.returncode, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual("declared", data["status"])
        self.assertEqual("hei5enbug-agent-setup", data["plugin_name"])
        self.assertEqual([], data["problems"])
        target = data["target"]
        self.assertEqual({"kind": "github", "location": "hei5enbug/hei5enbug-agent-setup"}, target["tracker"])
        self.assertEqual("en", target["language"])
        self.assertEqual("markdown", target["body_format"])
        self.assertEqual(["bug", "enhancement"], target["labels"])
        self.assertIs(True, target["public"])
        self.assertEqual("direct", target["write_approval"])
        self.assertIs(False, target["preview_required"])
        self.assertIsNone(target["content_rules"])


class SkillNameTest(unittest.TestCase):
    OLD_NAME = "report-skill-" + "gap"

    def test_스킬은_새_이름으로만_불리고_이전_이름은_어느_파일에도_남지_않는다(self) -> None:
        """스킬 폴더와 frontmatter 이름은 skill-issue-creator이고, 스킬 폴더의 어떤 파일에도 이전 이름이 없다."""
        # Given
        frontmatter = (SKILL / "SKILL.md").read_text(encoding="utf-8").split("---")[1]
        # When
        leftovers = [
            str(path.relative_to(SKILL))
            for path in sorted(SKILL.rglob("*"))
            if path.is_file() and self.OLD_NAME in path.read_text(encoding="utf-8", errors="ignore")
        ]
        # Then
        self.assertIn("name: skill-issue-creator", frontmatter)
        self.assertFalse((ROOT / "skills" / self.OLD_NAME).exists())
        self.assertEqual([], leftovers)


if __name__ == "__main__":
    unittest.main()
