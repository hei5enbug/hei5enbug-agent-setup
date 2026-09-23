#!/usr/bin/env python3
"""Validate the isolated Git fixtures used by suggest-commit evaluations."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from prepare_fixture import (
    AUTHOR_EMAIL,
    AUTHOR_NAME,
    FIXTURE_CASES,
    REPOSITORY_ROOT,
    FixtureError,
    prepare_fixture,
)


CONVENTION_MATCH_PATTERN = re.compile(r"commit ?(?:message|convention|format)", re.IGNORECASE)


def git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


class PrepareFixtureTest(unittest.TestCase):
    def make_fixture(self, case_name: str, root: Path) -> Path:
        output_root = root / "fixtures"
        return prepare_fixture(case_name, output_root)

    def inspect_documented_ticket_fixture(self, repo: Path) -> dict[str, object]:
        convention_lines = (repo / "CONTRIBUTING.md").read_text(encoding="utf-8").splitlines()
        history = git(repo, "log", "--format=%s", "-20")
        working_diff = git(repo, "diff", "--", "src/retry_policy.py")
        status = git(repo, "status", "--short")
        author = git(repo, "log", "--format=%an <%ae>", "-1")
        branch = git(repo, "branch", "--show-current")
        remotes = git(repo, "remote", "-v")
        return {
            "matches": [line for line in convention_lines if CONVENTION_MATCH_PATTERN.search(line)],
            "history": history.stdout.splitlines(),
            "working_diff": working_diff.stdout,
            "status": status.stdout.strip(),
            "author": author.stdout.strip(),
            "branch": branch.stdout,
            "remotes": remotes.stdout,
        }

    def inspect_no_change_fixture(self, repo: Path) -> dict[str, object]:
        head = git(repo, "rev-parse", "--verify", "HEAD")
        status = git(repo, "status", "--short")
        history = git(repo, "log", "--format=%s")
        remotes = git(repo, "remote", "-v")
        return {
            "head_status": head.returncode,
            "status": status.stdout,
            "history": history.stdout.splitlines(),
            "remotes": remotes.stdout,
        }

    def inspect_unborn_fixture(self, repo: Path) -> dict[str, object]:
        head = git(repo, "rev-parse", "--verify", "HEAD")
        staged = git(repo, "diff", "--cached", "--name-status")
        unstaged = git(repo, "diff", "--name-status")
        status = git(repo, "status", "--short")
        remotes = git(repo, "remote", "-v")
        return {
            "head_status": head.returncode,
            "staged": staged.stdout.strip(),
            "unstaged": unstaged.stdout.strip(),
            "status": status.stdout,
            "remotes": remotes.stdout,
        }

    def test_documented_ticket_rule_follows_more_than_ten_search_hits(self) -> None:
        """티켓 규칙은 열한 개의 검색 결과 뒤에 있고 변경은 HTTP 503만 추가한다."""
        # given
        with tempfile.TemporaryDirectory(prefix="suggest-commit-eval-test.") as temporary:
            root = Path(temporary)
            repo = self.make_fixture("documented-ticket", root)

            # when
            evidence = self.inspect_documented_ticket_fixture(repo)

            # then
            self.assertEqual(len(evidence["matches"]), 12)
            self.assertNotIn("[TICKET]", "\n".join(evidence["matches"][:10]))
            self.assertIn("required", evidence["matches"][11])
            self.assertEqual(len(evidence["history"]), 20)
            self.assertTrue(all("[" not in subject for subject in evidence["history"]))
            self.assertIn("feature/ABC-123", evidence["branch"])
            self.assertIn("+RETRYABLE_HTTP_STATUS_CODES = {429, 503}", evidence["working_diff"])
            self.assertEqual(evidence["status"], "M src/retry_policy.py")
            self.assertEqual(evidence["author"], f"{AUTHOR_NAME} <{AUTHOR_EMAIL}>")
            self.assertEqual(evidence["remotes"], "")

    def test_no_change_fixture_has_a_clean_head(self) -> None:
        """커밋이 있는 변경 없는 저장소는 빈 상태로 만들어진다."""
        # given
        with tempfile.TemporaryDirectory(prefix="suggest-commit-eval-test.") as temporary:
            root = Path(temporary)
            repo = self.make_fixture("no-change", root)

            # when
            evidence = self.inspect_no_change_fixture(repo)

            # then
            self.assertEqual(evidence["head_status"], 0)
            self.assertEqual(evidence["status"], "")
            self.assertEqual(evidence["history"], ["chore: seed clean evaluation repository"])
            self.assertEqual(evidence["remotes"], "")

    def test_unborn_fixture_has_staged_unstaged_and_untracked_paths(self) -> None:
        """커밋 없는 저장소에 스테이징·미스테이징 및 관련·무관 미추적 파일을 만든다."""
        # given
        with tempfile.TemporaryDirectory(prefix="suggest-commit-eval-test.") as temporary:
            root = Path(temporary)
            repo = self.make_fixture("unborn-mixed", root)

            # when
            evidence = self.inspect_unborn_fixture(repo)

            # then
            self.assertNotEqual(evidence["head_status"], 0)
            self.assertEqual(evidence["staged"], "A\tsrc/auth.py")
            self.assertEqual(evidence["unstaged"], "M\tsrc/auth.py")
            self.assertIn("?? tests/", evidence["status"])
            self.assertIn("?? notes/", evidence["status"])
            self.assertTrue((repo / "tests/test_auth.py").is_file())
            self.assertTrue((repo / "notes/unrelated.txt").is_file())
            self.assertEqual(evidence["remotes"], "")

    def test_fixture_builder_rejects_the_actual_repository(self) -> None:
        """실제 저장소 안에는 평가 저장소를 만들지 않는다."""
        # given
        target = REPOSITORY_ROOT.resolve()

        # when
        error = None
        try:
            prepare_fixture("no-change", target)
        except FixtureError as caught:
            error = caught

        # then
        self.assertIsNotNone(error)
        self.assertIn("outside the actual repository", str(error))
        self.assertEqual(FIXTURE_CASES, ("documented-ticket", "no-change", "unborn-mixed"))

    def test_cli_emits_a_usable_repository_working_directory(self) -> None:
        """준비 명령은 생성한 저장소의 실제 작업 경로를 출력한다."""
        # given
        with tempfile.TemporaryDirectory(prefix="suggest-commit-eval-cli.") as temporary:
            output_root = Path(temporary) / "fixtures"
            script = Path(__file__).with_name("prepare_fixture.py")

            # when
            result = subprocess.run(
                [sys.executable, str(script), "--case", "no-change", "--output-dir", str(output_root)],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)
            repo = Path(payload["fixtures"]["no-change"]["cwd"])

            # then
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["fixture_root"], str(output_root.resolve()))
            self.assertTrue(repo.is_dir())
            self.assertEqual(git(repo, "status", "--short").stdout, "")


if __name__ == "__main__":
    unittest.main()
