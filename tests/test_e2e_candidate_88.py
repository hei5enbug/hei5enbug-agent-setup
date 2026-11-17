"""Tests of the issue 88 candidate: a deterministic advisory for a stage named only by its number, applied to a copy of text_review.py."""

from __future__ import annotations

import difflib
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = REPO_ROOT / "evals/e2e/candidates/88/apply.py"
SHIPPED = REPO_ROOT / "scripts/text_review.py"
TASKS = REPO_ROOT / "evals/e2e/tasks"
FIXTURE = REPO_ROOT / "evals/e2e/fixtures/stage-notes"
RULE = "stage-number-alone"


def run_apply(checkout: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", str(CANDIDATE), str(checkout), *flags], capture_output=True, text=True)


class CandidateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.checkout = self.root / "checkout"
        (self.checkout / "scripts").mkdir(parents=True)
        self.script = self.checkout / "scripts" / "text_review.py"
        self.script.write_text(SHIPPED.read_text(encoding="utf-8"), encoding="utf-8")

    def applied(self):
        """Apply the candidate to the copy and load the copy as a module."""
        self.assertEqual(run_apply(self.checkout).returncode, 0)
        spec = importlib.util.spec_from_file_location("text_review_candidate", self.script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def advisories(self, module, text: str, kind: str = "ticket-comment") -> list[str]:
        found, advisories = module.check_text(text, kind, False)
        self.assertEqual(found, [])
        return [item["text"] for item in advisories if item["rule"] == RULE]

    def reference_text(self, task_id: str, name: str) -> str:
        repo = self.root / f"repo-{task_id}"
        repo.mkdir()
        env = {**os.environ, "PYTHONPATH": str(TASKS / "reference"), "PYTHONDONTWRITEBYTECODE": "1"}
        subprocess.run([sys.executable, "-B", str(TASKS / "reference" / task_id / "apply.py"), str(repo)], cwd=repo, env=env,
                       check=True, capture_output=True, text=True)
        return (repo / "out" / name).read_text(encoding="utf-8")

    def test_후보는_T29와_T31의_번호만_쓴_초안을_표시하고_세_과제의_참조_해법은_표시하지_않는다(self):
        """step 0과 steps 3 to 8, Phase 1과 item 1처럼 번호만 쓴 단계는 stage-number-alone으로 표시되고, 제목을 번호와 함께 쓴 참조 해법과 수량만 있는 T30 글은 표시되지 않는다."""
        # given
        module = self.applied()
        drafts = {name: (FIXTURE / "notes" / name).read_text(encoding="utf-8")
                  for name in ("comment-draft-demo-j.txt", "reply-draft-demo-k.txt", "comment-draft-demo-l.txt")}
        references = [self.reference_text("T29", "ticket-comment-demo-j.txt"),
                      self.reference_text("T30", "review-reply-demo-k.txt"),
                      self.reference_text("T31", "ticket-comment-demo-l.txt")]

        # when
        flagged = {name: bool(self.advisories(module, text)) for name, text in drafts.items()}
        referenced = [self.advisories(module, text) for text in references]

        # then
        self.assertEqual(flagged, {"comment-draft-demo-j.txt": True, "reply-draft-demo-k.txt": False,
                                   "comment-draft-demo-l.txt": True})
        self.assertEqual(referenced, [[], [], []])

    def test_후보는_제목이_번호_옆에_있는_표기는_표시하지_않고_제목을_모르면_못_가리는_잘못은_통과시킨다(self):
        """제목이 뒤나 앞에 붙은 번호는 표시하지 않아 오탐을 막고, 제목과 번호가 어긋나거나 순서가 바뀌거나 한 번호가 둘을 가리키는 글은 패턴으로 가릴 수 없어 통과한다."""
        # given
        module = self.applied()
        titled = ["Run step 0 (Check and build) first.", "Run Check and build (step 0) first.",
                  "Step 3: Compare comes next.", "Rollout (Phase 2) starts once the review passes.",
                  "Begin with item 1 (Schema extension).", "Keep a copy in `step 4` of the log."]
        undecidable = ["Run 0 Check and build first, then 4 Compare, 3 Enable reads.",
                       "Run 0 Check and build first, then 4 Enable reads, 3 Compare.",
                       "Rollout (Phase 1) starts once the review passes. Begin with 1 Schema extension.",
                       "Keep nesting at a depth of at most 3 levels and list at most 3 items."]

        # when
        flagged = [self.advisories(module, text) for text in titled + undecidable]

        # then
        self.assertEqual(flagged, [[]] * len(flagged))

    def test_후보를_두_번_적용해도_두_번째는_아무것도_바꾸지_않는다(self):
        """이미 적용된 사본에 다시 적용하면 파일이 한 바이트도 바뀌지 않고 already applied라고 알려, 같은 줄이 두 번 들어가지 않는다."""
        # given
        self.assertEqual(run_apply(self.checkout).returncode, 0)
        once = self.script.read_bytes()

        # when
        second = run_apply(self.checkout)

        # then
        self.assertEqual((second.returncode, second.stdout.strip(), self.script.read_bytes() == once), (0, "already applied", True))
        self.assertEqual(once.decode("utf-8").count("def stage_number_alone("), 1)

    def test_후보는_의도한_줄만_바꾸고_dry_run은_아무것도_쓰지_않는다(self):
        """원본에서 지워지는 줄은 advisories 대입 한 줄뿐이고 나머지는 추가이며, --dry-run은 같은 변경을 diff로만 보여 주고 파일을 그대로 둔다."""
        # given
        original = SHIPPED.read_text(encoding="utf-8")
        dry = run_apply(self.checkout, "--dry-run")
        untouched = self.script.read_text(encoding="utf-8") == original

        # when
        self.assertEqual(run_apply(self.checkout).returncode, 0)
        diff = list(difflib.unified_diff(original.splitlines(), self.script.read_text(encoding="utf-8").splitlines(), lineterm="", n=0))

        # then
        removed = [line[1:] for line in diff if line.startswith("-") and not line.startswith("---")]
        self.assertEqual(removed, ["    advisories = unchanged_only(lines)"])
        self.assertIn("+    advisories = unchanged_only(lines) + stage_number_alone(lines)", dry.stdout)
        self.assertTrue(untouched)

    def test_후보를_붙인_사본은_기존_표시를_그대로_내고_검토자_지시에_새_표시_줄과_설명을_싣는다(self):
        """새 규칙을 붙여도 다른 글의 advisories는 원본과 같고, FLAGGED_EXPLANATIONS 항목이 빠지면 조용히 사라지므로 검토자 지시에 표시된 줄과 설명이 들어간다."""
        # given
        spec = importlib.util.spec_from_file_location("text_review_shipped", SHIPPED)
        shipped = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(shipped)
        module = self.applied()
        text = "Nothing changes in the API.\n\n- Added `a_one`, `a_two`, and `a_three`.\n"
        staged = "Run step 0 first, then steps 3 to 8 in order.\n"

        # when
        same = module.check_text(text, "pr-description", False) == shipped.check_text(text, "pr-description", False)
        found, advisories = module.check_text(staged, "ticket-comment", False)
        assignment = module.build_assignment("ticket-comment", staged, [], [], [], None, advisories)

        # then
        self.assertTrue(same)
        self.assertEqual([item["rule"] for item in advisories], [RULE])
        self.assertIn("Run step 0 first, then steps 3 to 8 in order.", assignment)
        self.assertIn("by a number with no title", assignment)

    def test_기준_줄이_바뀐_점검_스크립트에는_적용하지_않고_파일을_그대로_둔다(self):
        """고정 줄을 한 번만 찾지 못하면 반쯤 고친 파일을 남기지 않고 종료 코드 2로 멈춘다."""
        # given
        broken = self.script.read_text(encoding="utf-8").replace("    advisories = unchanged_only(lines)\n", "")
        self.script.write_text(broken, encoding="utf-8")

        # when
        result = run_apply(self.checkout)

        # then
        self.assertEqual((result.returncode, self.script.read_text(encoding="utf-8") == broken), (2, True))
        self.assertIn("anchor found 0 times", result.stderr)


if __name__ == "__main__":
    unittest.main()
