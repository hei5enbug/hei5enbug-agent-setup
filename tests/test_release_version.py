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
VERSION_FILES = frozenset({".codex-plugin/plugin.json", CLAUDE_MANIFEST, "pyproject.toml", "uv.lock"})


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


def commit_files(revision_range: str) -> dict[str, set[str]]:
    output = git("log", "--format=%x00%H", "--name-only", revision_range) or ""
    commits = {}
    for chunk in output.split("\0")[1:]:
        sha, *paths = [line for line in chunk.splitlines() if line]
        commits[sha] = set(paths)
    return commits


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

    def test_릴리스_기준_이후_변경이_있으면_계획한_버전은_기준보다_높다(self):
        """릴리스 기준 태그 이후 추적 파일이 바뀌었으면 매니페스트의 계획 버전은 기준 버전보다 높아야 한다."""
        # Given
        baseline = self.baseline[1:]
        changed = (git("diff", "--name-only", self.baseline) or "").splitlines()
        if not changed:
            self.skipTest(f"nothing changed since {self.baseline}")

        # When
        planned = planned_version()

        # Then
        self.assertGreater(
            version_tuple(planned), version_tuple(baseline), f"{planned} is not above {self.baseline} after changes"
        )

    def test_릴리스_기준_이후_버전_파일만_바꾸는_커밋은_없다(self):
        """릴리스는 태그만 달기 때문에 릴리스 기준 태그 이후에는 버전 파일만 바꾸는 커밋이 없어야 한다."""
        # Given
        revision_range = f"{self.baseline}..HEAD"

        # When
        version_only = sorted(
            sha for sha, paths in commit_files(revision_range).items() if paths and paths <= VERSION_FILES
        )

        # Then
        self.assertEqual(version_only, [], f"commits since {self.baseline} change only version files")


if __name__ == "__main__":
    unittest.main()
