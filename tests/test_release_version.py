from __future__ import annotations

import json
import re
import subprocess
import tomllib
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
README_VERSION = re.compile(r"`\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?`")
RELEASE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
MANIFEST_VERSION_ADDED = re.compile(r'^\+\s*"version":\s*"(\d+\.\d+\.\d+)"', re.MULTILINE)
CLAUDE_MANIFEST = ".claude-plugin/plugin.json"


def git(*args: str) -> str | None:
    try:
        completed = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout


def version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def planned_version() -> str:
    return json.loads((REPO_ROOT / CLAUDE_MANIFEST).read_text(encoding="utf-8"))["version"]


def baseline_tag() -> str | None:
    """The newest release tag reachable from HEAD, or None when git history or tags are unavailable."""
    if git("rev-parse", "--is-shallow-repository") != "false\n":
        return None
    listed = git("tag", "--merged", "HEAD")
    if listed is None:
        return None
    tags = [tag for tag in listed.split() if RELEASE_TAG.fullmatch(tag)]
    return max(tags, key=lambda tag: version_tuple(tag[1:])) if tags else None


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


class ReleaseBaselineTest(unittest.TestCase):
    def setUp(self):
        self.baseline = baseline_tag()
        if self.baseline is None:
            self.skipTest("release tags are unavailable in this checkout")

    def test_계획한_버전은_릴리스_기준_태그보다_낮지_않다(self):
        """매니페스트의 계획 버전은 HEAD에서 닿는 가장 새로운 릴리스 태그보다 낮을 수 없다."""
        # Given
        baseline = self.baseline[1:]

        # When
        planned = planned_version()

        # Then
        self.assertGreaterEqual(version_tuple(planned), version_tuple(baseline), f"{planned} is below {self.baseline}")

    def test_릴리스_기준_이후_계획한_버전은_하나뿐이다(self):
        """릴리스 기준 태그 이후 매니페스트에 나타난 버전은 기준 버전과 계획 버전 둘 중 하나뿐이어야 한다."""
        # Given
        baseline = self.baseline[1:]
        planned = planned_version()

        # When
        history = git("log", f"{self.baseline}..HEAD", "-p", "--", CLAUDE_MANIFEST) or ""
        introduced = set(MANIFEST_VERSION_ADDED.findall(history))

        # Then
        self.assertLessEqual(introduced, {baseline, planned}, f"more than one planned version since {self.baseline}")


if __name__ == "__main__":
    unittest.main()
