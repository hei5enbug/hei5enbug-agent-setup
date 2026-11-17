"""Tests of the issue 111 candidate: the usage-limit handling moves from the shared text rules into the result of text_review.py, applied to a copy."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tests"))
from test_text_review import CLEAN_DRAFT, FAKE_RUNNER  # noqa: E402

CANDIDATE = REPO_ROOT / "evals/e2e/candidates/111/apply.py"
FILES = ("scripts/text_review.py", "instructions/shared-text.md")


def run_apply(checkout: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", str(CANDIDATE), str(checkout), *flags], capture_output=True, text=True)


class CandidateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.checkout = self.root / "checkout"
        for relative in FILES:
            target = self.checkout / relative
            target.parent.mkdir(parents=True)
            target.write_text((REPO_ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")

    def text(self, relative: str) -> str:
        return (self.checkout / relative).read_text(encoding="utf-8")

    def review(self, mode: str) -> tuple[int, dict]:
        out = self.root / "out"
        out.mkdir(exist_ok=True)
        runner = self.root / "runner.py"
        runner.write_text(FAKE_RUNNER, encoding="utf-8")
        draft = self.root / "draft.md"
        draft.write_text(CLEAN_DRAFT, encoding="utf-8")
        done = subprocess.run(
            [sys.executable, "-B", str(self.checkout / "scripts/text_review.py"), "review", "--kind", "pr-description",
             "--draft", str(draft), "--runner", str(runner)],
            capture_output=True, text=True, env={**os.environ, "FAKE_OUT": str(out), "FAKE_MODE": mode})
        return done.returncode, json.loads(done.stdout)

    def test_후보는_한도_결과에만_다음_행동을_싣고_규칙_문단은_한_줄로_줄인다(self):
        """다음 행동은 exit 4 결과에만 들어가고 다른 실패의 결과에는 없으며, 공유 글 규칙의 exit 4 문단은 그 결과를 따르라는 한 줄만 남는다."""
        # given
        self.assertEqual(run_apply(self.checkout).returncode, 0)

        # when
        limited_code, limited = self.review("usage")
        failed_code, failed = self.review("auth")
        rules = self.text("instructions/shared-text.md")

        # then
        self.assertEqual((limited_code, limited["reason"]), (4, "usage_limit"))
        self.assertIn("post without asking", limited["next"])
        self.assertIn("check --kind final-report", limited["next"])
        self.assertEqual(failed_code, 3)
        self.assertNotIn("next", failed)
        self.assertIn("- Exit 4 means the reviewer's usage limit is reached. Follow the result's `next`.", rules)
        self.assertNotIn("post\n  without asking", rules)

    def test_후보를_두_번_적용해도_두_번째는_바꾸지_않고_dry_run은_아무것도_쓰지_않는다(self):
        """이미 적용된 사본에는 already applied만 알리고 같은 줄이 두 번 들어가지 않으며, --dry-run은 두 파일의 diff만 보여 준다."""
        # given
        before = {relative: self.text(relative) for relative in FILES}
        dry = run_apply(self.checkout, "--dry-run")
        untouched = {relative: self.text(relative) for relative in FILES} == before

        # when
        self.assertEqual(run_apply(self.checkout).returncode, 0)
        once = {relative: self.text(relative) for relative in FILES}
        second = run_apply(self.checkout)

        # then
        self.assertTrue(untouched)
        self.assertIn("+- Exit 4 means the reviewer's usage limit is reached.", dry.stdout)
        self.assertEqual((second.returncode, second.stdout.strip()), (0, "already applied"))
        self.assertEqual({relative: self.text(relative) for relative in FILES}, once)
        self.assertEqual(once["scripts/text_review.py"].count("USAGE_LIMIT_NEXT = "), 1)

    def test_한_파일의_기준_줄을_찾지_못하면_어느_파일도_바꾸지_않는다(self):
        """규칙 문단이 바뀌어 기준을 못 찾을 때 스크립트만 바뀐 반쪽 사본이 남으면 규칙과 결과가 어긋나므로 종료 코드 2로 멈추고 둘 다 그대로 둔다."""
        # given
        rules = self.text("instructions/shared-text.md").replace("- Exit 4, with", "- Exit 4 with")
        (self.checkout / "instructions/shared-text.md").write_text(rules, encoding="utf-8")
        script = self.text("scripts/text_review.py")

        # when
        result = run_apply(self.checkout)

        # then
        self.assertEqual(result.returncode, 2)
        self.assertIn("anchor found 0 times", result.stderr)
        self.assertEqual((self.text("scripts/text_review.py"), self.text("instructions/shared-text.md")), (script, rules))


if __name__ == "__main__":
    unittest.main()
