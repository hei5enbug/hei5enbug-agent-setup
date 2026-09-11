from __future__ import annotations

import json
import re
import tomllib
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
README_VERSION = re.compile(r"`\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?`")


class ReleaseVersionTest(unittest.TestCase):
    def test_release_files_use_one_version(self):
        versions = {
            ".codex-plugin/plugin.json": json.loads(
                (REPO_ROOT / ".codex-plugin/plugin.json").read_text()
            )["version"],
            ".claude-plugin/plugin.json": json.loads(
                (REPO_ROOT / ".claude-plugin/plugin.json").read_text()
            )["version"],
            "pyproject.toml": tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"][
                "version"
            ],
        }
        locked = tomllib.loads((REPO_ROOT / "uv.lock").read_text())["package"]
        versions["uv.lock"] = next(
            package["version"]
            for package in locked
            if package["name"] == "hei5enbug-agent-setup"
        )
        self.assertEqual(len(set(versions.values())), 1, versions)

    def test_readmes_do_not_publish_a_current_version(self):
        for path in REPO_ROOT.glob("README*.md"):
            with self.subTest(path=path.name):
                self.assertIsNone(README_VERSION.search(path.read_text()))


if __name__ == "__main__":
    unittest.main()
