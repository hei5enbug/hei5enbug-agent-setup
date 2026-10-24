#!/usr/bin/env python3
"""이 저장소가 report-skill-gap 스킬에 선언한 이슈 대상이 기대한 값과 같은지 검사한다."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "report-skill-gap" / "scripts" / "find_tracker.py"
SKILL = ROOT / "skills" / "report-skill-gap"


class IssueTargetTest(unittest.TestCase):
    def test_repository_declares_its_github_tracker(self) -> None:
        """저장소는 자신의 GitHub 추적기를 공개 저장소로 선언하고 미리보기를 요구한다."""
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
        self.assertEqual("preview", target["write_approval"])
        self.assertIs(True, target["preview_required"])
        self.assertIsNone(target["content_rules"])


if __name__ == "__main__":
    unittest.main()
