"""Tests for the builder of the combined revision of adopted loop-shape candidates."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))

from harness import cli, combined_build  # noqa: E402
from harness.command import ConfigError  # noqa: E402

IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com"}


def run_git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True, env={**os.environ, **IDENTITY})
    return done.stdout.strip()


class CombinedBuildTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.repo = self.root / "repo"
        self.repo.mkdir()
        run_git(self.repo, "init", "-q", "-b", "base")
        self.commit_file("shared.txt", "one\ntwo\nthree\n", "base")
        self.commit_file("other.txt", "x\n", "base other")
        self.candidate("cand-a", "a.txt", "from a\n")
        self.candidate("cand-b", "b.txt", "from b\n")
        self.candidate("cand-clash1", "shared.txt", "one\nONE-CLASH\nthree\n")
        self.candidate("cand-clash2", "shared.txt", "one\nTWO-CLASH\nthree\n")
        run_git(self.repo, "checkout", "-q", "base")
        run_git(self.repo, "checkout", "-q", "--orphan", "elsewhere")
        self.commit_file("e.txt", "e\n", "elsewhere")
        run_git(self.repo, "checkout", "-q", "base")

    def commit_file(self, name: str, text: str, message: str) -> None:
        (self.repo / name).write_text(text, encoding="utf-8")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-q", "-m", message)

    def candidate(self, branch: str, name: str, text: str) -> None:
        run_git(self.repo, "checkout", "-q", "-b", branch, "base")
        self.commit_file(name, text, branch)
        run_git(self.repo, "checkout", "-q", "base")

    def build(self, candidates: list[str], name: str = "wt", dry_run: bool = False) -> tuple[str | None, str, Path]:
        out, worktree = io.StringIO(), self.root / name
        sha = combined_build.build_combined(self.repo, "base", candidates, worktree, dry_run, out, io.StringIO())
        return sha, out.getvalue(), worktree

    def test_후보_둘을_기준_위에_합친_커밋을_만들고_SHA를_출력한다(self) -> None:
        # given: two candidates that touch different files
        # when
        sha, out, worktree = self.build(["cand-a", "cand-b"])
        # then
        self.assertEqual(out.strip(), sha)
        self.assertEqual(run_git(worktree, "rev-parse", "HEAD"), sha)
        self.assertTrue((worktree / "a.txt").is_file() and (worktree / "b.txt").is_file())
        self.assertEqual(run_git(self.repo, "merge-base", "base", sha), run_git(self.repo, "rev-parse", "base"))

    def test_같은_입력은_작업_폴더가_달라도_같은_SHA를_낸다(self) -> None:
        # regression: a SHA that differs per run would make the variant file of a campaign unrepeatable
        first, _, _ = self.build(["cand-a", "cand-b"], "wt1")
        second, _, _ = self.build(["cand-a", "cand-b"], "wt2")
        self.assertEqual(first, second)

    def test_충돌하면_후보와_파일을_밝히고_작업_폴더를_지운다(self) -> None:
        # given: two candidates that change the same line
        worktree = self.root / "wt"
        # when
        with self.assertRaises(ConfigError) as caught:
            self.build(["cand-clash1", "cand-clash2"])
        # then
        message = str(caught.exception)
        self.assertIn("cand-clash2", message)
        self.assertIn("shared.txt", message)
        self.assertFalse(worktree.exists())
        self.assertNotIn(str(worktree), run_git(self.repo, "worktree", "list"))

    def test_dry_run은_명령만_출력하고_아무것도_만들지_않는다(self) -> None:
        sha, out, worktree = self.build(["cand-a", "cand-b"], dry_run=True)
        self.assertIsNone(sha)
        self.assertFalse(worktree.exists())
        self.assertIn("git worktree add --detach", out)
        self.assertIn("merge --no-ff", out)
        self.assertEqual(run_git(self.repo, "worktree", "list").count("\n"), 0)

    def test_기준에서_갈라지지_않은_후보와_잘못된_입력은_거부한다(self) -> None:
        for candidates in (["cand-a", "elsewhere"], ["cand-a"], ["cand-a", "cand-a"], ["cand-a", "missing"], ["cand-a", "base"]):
            with self.subTest(candidates=candidates), self.assertRaises(ConfigError):
                self.build(candidates)
        self.assertFalse((self.root / "wt").exists())

    def test_이미_있는_작업_폴더는_덮어쓰지_않는다(self) -> None:
        self.build(["cand-a", "cand-b"])
        with self.assertRaises(ConfigError) as caught:
            self.build(["cand-a", "cand-b"])
        self.assertIn("exists", str(caught.exception))

    def test_cli는_없는_브랜치를_오류_메시지와_종료_코드_1로_알린다(self) -> None:
        err, real = io.StringIO(), sys.stderr
        sys.stderr = err
        try:
            code = cli.main(["build-combined", "--base", "no-such-base", "--candidate", "a", "--candidate", "b", "--dry-run"])
        finally:
            sys.stderr = real
        self.assertEqual(code, 1)
        self.assertIn("no-such-base is not a commit", err.getvalue())

if __name__ == "__main__":
    unittest.main()
