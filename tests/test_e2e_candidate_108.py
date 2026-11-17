"""Tests of the issue 108 candidate: the final-report length threshold removed from both hosts, applied to a copy."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tests"))
from test_final_report_hook import assistant, edit, prompt  # noqa: E402

CANDIDATE = REPO_ROOT / "evals/e2e/candidates/108/apply.py"
RULES = "instructions/shared-text.md"
HOOK = "scripts/final_report_hook.py"
SHORT_REPORT = "설정을 바꿨고 테스트가 통과합니다."


def run_apply(checkout: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", str(CANDIDATE), str(checkout), *flags], capture_output=True, text=True)


class CandidateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.checkout = self.root / "checkout"
        shutil.copytree(REPO_ROOT / "scripts", self.checkout / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        (self.checkout / RULES).parent.mkdir(parents=True)
        shutil.copyfile(REPO_ROOT / RULES, self.checkout / RULES)

    def text(self, relative: str) -> str:
        return (self.checkout / relative).read_text(encoding="utf-8")

    def stop(self, message: str) -> str:
        transcript = self.root / "session.jsonl"
        transcript.write_text("\n".join((prompt(), assistant(edit()))) + "\n", encoding="utf-8")
        event = {"hook_event_name": "Stop", "transcript_path": str(transcript), "last_assistant_message": message}
        done = subprocess.run([sys.executable, "-B", str(self.checkout / HOOK)], input=json.dumps(event), capture_output=True,
                              text=True, check=True)
        return done.stdout

    def test_후보는_짧은_최종_보고의_면제_문장과_훅의_길이_기준을_함께_없앤다(self):
        """면제 문장만 지우면 Codex만 모든 보고를 검토하고, 훅만 바꾸면 Claude Code만 그렇게 되므로, 적용한 사본은 문장이 없고 훅은 짧은 보고도 이어 간다."""
        # given
        self.assertEqual(self.stop(SHORT_REPORT), "")

        # when
        applied = run_apply(self.checkout)
        continued = self.stop(SHORT_REPORT)

        # then
        self.assertEqual(applied.returncode, 0)
        self.assertNotIn("A final report under", self.text(RULES))
        self.assertIn("A final report is the reply that ends a task by reporting its result", self.text(RULES))
        self.assertIn("text_review.py review --kind final-report", continued)

    def test_후보를_두_번_적용해도_두_번째는_바꾸지_않고_dry_run은_아무것도_쓰지_않는다(self):
        """이미 적용된 사본에는 already applied만 알리고, --dry-run은 두 파일의 diff만 보여 준다."""
        # given
        before = (self.text(RULES), self.text(HOOK))
        dry = run_apply(self.checkout, "--dry-run")
        untouched = (self.text(RULES), self.text(HOOK)) == before

        # when
        self.assertEqual(run_apply(self.checkout).returncode, 0)
        once = (self.text(RULES), self.text(HOOK))
        second = run_apply(self.checkout)

        # then
        self.assertTrue(untouched)
        self.assertIn("+MINIMUM_REPORT_CHARACTERS = 0", dry.stdout)
        self.assertEqual((second.returncode, second.stdout.strip()), (0, "already applied"))
        self.assertEqual((self.text(RULES), self.text(HOOK)), once)

    def test_한_파일의_기준을_찾지_못하면_어느_파일도_바꾸지_않는다(self):
        """훅 상수가 바뀌어 기준을 못 찾을 때 문장만 지운 반쪽 사본이 남으면 두 호스트가 갈리므로 종료 코드 2로 멈추고 둘 다 그대로 둔다."""
        # given
        hook = self.text(HOOK).replace("MINIMUM_REPORT_CHARACTERS = 400", "MINIMUM_REPORT_CHARACTERS = 350")
        (self.checkout / HOOK).write_text(hook, encoding="utf-8")
        rules = self.text(RULES)

        # when
        result = run_apply(self.checkout)

        # then
        self.assertEqual(result.returncode, 2)
        self.assertIn("anchor found 0 times", result.stderr)
        self.assertEqual((self.text(RULES), self.text(HOOK)), (rules, hook))


if __name__ == "__main__":
    unittest.main()
