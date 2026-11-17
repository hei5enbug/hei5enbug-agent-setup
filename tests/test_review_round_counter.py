"""The unapplied candidate patch that counts text review runs per draft and prints the three-run stop."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "text_review.py"
PATCH = REPO_ROOT / "evals/e2e/candidates/118-review-round-counter.patch"
DRAFT = "## Summary\n\nThe parser now rejects empty input.\n"
FAKE_RUNNER = textwrap.dedent(
    """
    import json, os, sys
    argv = sys.argv[1:]
    result = argv[argv.index("--result") + 1]
    mode = os.environ["FAKE_MODE"]
    if mode == "findings":
        body = {"findings": [{"type": "removable", "quote": "x", "reason": "y"}]}
    else:
        body = {"findings": []}
    if mode != "exit3":
        open(result, "w").write("```json\\n" + json.dumps(body) + "\\n```\\n")
    print(json.dumps({"verified": True, "exit": 3 if mode == "exit3" else 0}))
    sys.exit(3 if mode == "exit3" else 0)
    """
)


class ReviewRoundCounterTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.patched = self.copy_script("patched")
        subprocess.run(["git", "apply", str(PATCH)], cwd=self.root / "patched", check=True, capture_output=True)
        self.plain = self.copy_script("plain")
        (self.root / "runner.py").write_text(FAKE_RUNNER, encoding="utf-8")
        self.state = self.root / "state"
        self.drafts = {}
        for name in ("a", "b"):
            self.drafts[name] = self.root / f"draft-{name}.md"
            self.drafts[name].write_text(DRAFT, encoding="utf-8")

    def copy_script(self, name: str) -> Path:
        target = self.root / name / "scripts" / "text_review.py"
        target.parent.mkdir(parents=True)
        shutil.copy(SCRIPT, target)
        return target

    def review(self, script: Path, mode: str, draft: str = "a", *extra: str) -> tuple[int, dict]:
        completed = subprocess.run(
            [sys.executable, str(script), "review", "--kind", "other", "--draft", str(self.drafts[draft]),
             "--runner", str(self.root / "runner.py"), *extra],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "FAKE_MODE": mode, "TEXT_REVIEW_STATE_DIR": str(self.state)})
        return completed.returncode, json.loads(completed.stdout)

    def test_후보_패치는_이_브랜치의_text_review_스크립트에_깨끗하게_적용된다(self):
        """다른 변경이 text_review.py를 바꿔 후보 패치가 더는 적용되지 않으면 실패한다."""
        # Given
        target = self.copy_script("fresh")

        # When
        applied = subprocess.run(["git", "apply", "--check", str(PATCH)], cwd=target.parents[1],
                                 capture_output=True, text=True)

        # Then
        self.assertEqual(applied.returncode, 0, applied.stderr)

    def test_지적이_남는_세_번째_실행은_멈춤과_질문을_내고_여섯_번째도_다시_낸다(self):
        """같은 초안의 검토자까지 간 실행이 세 번 연속 지적을 내면 세 번째에만 멈춤 알림과 질문이 붙는다."""
        # Given
        outcomes = []

        # When
        for _ in range(6):
            outcomes.append(self.review(self.patched, "findings")[1])

        # Then
        self.assertEqual([item["runs"] for item in outcomes], [1, 2, 3, 4, 5, 6])
        self.assertEqual(["stop" in item for item in outcomes], [False, False, True, False, False, True])
        self.assertIn("write nothing outward", outcomes[2]["stop"])
        self.assertIn("one recommendation", outcomes[2]["question"])

    def test_패치하지_않은_사본은_몇_번을_돌려도_멈춤을_내지_않는다(self):
        """패치하지 않은 text_review.py는 세 번 이상 지적을 내도 stop, question, runs를 내지 않는다."""
        # Given
        outcomes = []

        # When
        for _ in range(4):
            outcomes.append(self.review(self.plain, "findings"))

        # Then
        self.assertEqual([code for code, _ in outcomes], [1, 1, 1, 1])
        self.assertTrue(all({"stop", "question", "runs"}.isdisjoint(item) for _, item in outcomes))

    def test_지적_없는_실행은_그_초안의_횟수만_되돌리고_다른_초안과_판정_못_낸_실행과_점검_멈춤은_세지_않는다(self):
        """깨끗한 결과는 그 초안만 0으로 되돌리고, 다른 초안의 횟수, 판정 없음(종료 코드 3), 점검에서 멈춘 실행은 횟수를 바꾸지 않는다."""
        # Given
        self.review(self.patched, "findings", "a")
        self.review(self.patched, "findings", "a")
        self.review(self.patched, "findings", "b")
        self.drafts["a"].write_text(DRAFT + "\nSee ABC-123.\n", encoding="utf-8")

        # When
        checked = self.review(self.patched, "findings", "a", "--no-ticket-keys")
        self.drafts["a"].write_text(DRAFT, encoding="utf-8")
        no_verdict = self.review(self.patched, "exit3", "a")
        third = self.review(self.patched, "findings", "a")
        clean = self.review(self.patched, "none", "a")
        again = self.review(self.patched, "findings", "a")
        other = self.review(self.patched, "findings", "b")

        # Then
        self.assertEqual((checked[0], checked[1]["stage"], "runs" in checked[1]), (1, "check", False))
        self.assertEqual((no_verdict[0], "runs" in no_verdict[1]), (3, False))
        self.assertEqual((third[1]["runs"], "stop" in third[1]), (3, True))
        self.assertEqual((clean[0], "runs" in clean[1]), (0, False))
        self.assertEqual(again[1]["runs"], 1)
        self.assertEqual(other[1]["runs"], 2)

    def test_표준_입력_초안은_횟수를_세지_않는다(self):
        """파일이 아닌 `-` 초안은 같은 초안으로 식별할 수 없어 runs를 내지 않는다."""
        # Given
        command = [sys.executable, str(self.patched), "review", "--kind", "other", "--draft", "-", "--runner",
                   str(self.root / "runner.py")]

        # When
        completed = subprocess.run(command, input=DRAFT, capture_output=True, text=True, timeout=60,
                                   env={**os.environ, "FAKE_MODE": "findings", "TEXT_REVIEW_STATE_DIR": str(self.state)})

        # Then
        self.assertEqual(completed.returncode, 1)
        self.assertNotIn("runs", json.loads(completed.stdout))


if __name__ == "__main__":
    unittest.main()
