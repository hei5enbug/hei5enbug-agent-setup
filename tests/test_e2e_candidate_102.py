"""Tests of the issue 102 candidates: loop shapes of the independent text review, kept out of the shipped files and applied to a copy."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = REPO_ROOT / "evals/e2e/candidates/102/apply.py"
LOOP_STUB = REPO_ROOT / "evals/e2e/fixtures/loop-notes/tools/loop_runner.py"
FILES = ("scripts/text_review.py", "instructions/shared-text.md")
FIRST = "The parser now rejects empty input."
SECOND = "Empty input used to crash the importer."
THIRD = "The importer reports the line of a bad row."
REVISED = "Empty input is now rejected before the importer starts."
RUNNER = textwrap.dedent(
    """
    import json, os, sys
    argv = sys.argv[1:]
    value = lambda flag: argv[argv.index(flag) + 1]
    out = os.environ["FAKE_OUT"]
    if os.environ.get("FAKE_CALLS"):
        open(os.environ["FAKE_CALLS"], "a").write("x")
    assignment = open(value("--assignment"), encoding="utf-8").read()
    with open(os.path.join(out, "assignment.md"), "w", encoding="utf-8") as handle:
        handle.write(assignment)
    findings = json.loads(os.environ.get("FAKE_FINDINGS", "[]"))
    open(value("--result"), "w", encoding="utf-8").write("```json\\n" + json.dumps({"findings": findings}) + "\\n```\\n")
    print(json.dumps({"verified": True, "exit": 0}))
    """
)


def run_apply(checkout: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", str(CANDIDATE), str(checkout), *flags], capture_output=True, text=True)


def finding(kind: str, quote: str) -> dict:
    return {"type": kind, "quote": quote, "reason": "seeded"}


class CandidateCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.checkout = self.root / "checkout"
        for relative in FILES:
            target = self.checkout / relative
            target.parent.mkdir(parents=True)
            target.write_text((REPO_ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")
        self.out = self.root / "out"
        self.out.mkdir()
        self.runner = self.root / "runner.py"
        self.runner.write_text(RUNNER, encoding="utf-8")
        self.history = self.root / "history.json"

    def text(self, relative: str) -> str:
        return (self.checkout / relative).read_text(encoding="utf-8")

    def apply(self, name: str) -> None:
        self.assertEqual(run_apply(self.checkout, "--candidate", name).returncode, 0)

    def review(self, draft: str, findings: list[dict], *extra: str, runner: Path | None = None) -> tuple[int, dict]:
        path = self.root / "draft.md"
        path.write_text(draft, encoding="utf-8")
        done = subprocess.run(
            [sys.executable, "-B", str(self.checkout / "scripts/text_review.py"), "review", "--kind", "pr-description", "--draft", str(path),
             "--runner", str(runner or self.runner), *extra],
            capture_output=True, text=True, env={**os.environ, "FAKE_OUT": str(self.out), "FAKE_FINDINGS": json.dumps(findings)})
        return done.returncode, json.loads(done.stdout)

    def assignment(self) -> str:
        return (self.out / "assignment.md").read_text(encoding="utf-8")


class ChangedSentenceTest(CandidateCase):
    def first_run(self, draft: str, findings: list[dict]) -> None:
        self.apply("c")
        code, _ = self.review(draft, findings, "--history", str(self.history))
        self.assertEqual(code, 1 if findings else 0)

    def test_둘째_실행의_지시문은_바뀐_문장만_싣고_바뀌지_않은_문장의_지울_거리_지적만_버리며_다른_종류는_남긴다(self):
        """이전 실행 뒤 한 문장만 바뀌면 지시문의 바뀐 문장 목록은 그 한 문장이고, 바뀌지 않은 문장에 대한 removable은 버려지며 missing은 남는다."""
        # given
        before = f"{FIRST}\n\n{SECOND}\n\n{THIRD}\n"
        after = f"{FIRST}\n\n{SECOND}\n\n{REVISED}\n"
        self.first_run(before, [])

        # when
        code, result = self.review(after, [finding("removable", SECOND), finding("missing", SECOND), finding("removable", REVISED)],
                                   "--history", str(self.history))

        # then
        changed = self.assignment().split("### Changed since the previous run")[1].split("### Flagged by an earlier run")[0]
        self.assertEqual(changed.strip().strip("`").strip(), REVISED)
        self.assertEqual((code, [(item["type"], item["quote"]) for item in result["findings"]]),
                         (1, [("missing", SECOND), ("removable", REVISED)]))
        self.assertEqual([item["quote"] for item in result["dropped"]], [SECOND])

    def test_앞선_실행이_지적한_문장은_메모로_남기든_고치든_뒤_실행에서_지울_거리_지적이_버려지지_않는다(self):
        """앞선 실행이 지적한 문장은 메모와 함께 그대로 두어도, 고쳐 둔 뒤에도 다음 실행의 removable이 남아 같은 지적의 반복을 세션이 볼 수 있다."""
        # given
        before = f"{FIRST}\n\n{SECOND}\n\n{THIRD}\n"
        self.first_run(before, [finding("removable", SECOND)])
        code_kept, kept = self.review(before, [finding("removable", SECOND)], "--history", str(self.history), "--note", "needed")
        reworded = before.replace(SECOND, "Empty input crashed the importer before this change.")
        code_edit, _ = self.review(reworded, [], "--history", str(self.history))

        # when
        code_late, late = self.review(reworded, [finding("removable", "Empty input crashed the importer before this change.")],
                                      "--history", str(self.history))
        other = self.review(reworded, [finding("removable", THIRD)], "--history", str(self.history))[1]

        # then
        self.assertEqual((code_kept, [item["quote"] for item in kept["findings"]]), (1, [SECOND]))
        self.assertEqual(code_edit, 0)
        self.assertEqual((code_late, len(late["findings"]), "dropped" in late), (1, 1, False))
        self.assertEqual([item["quote"] for item in other["dropped"]], [THIRD])

    def test_첫_실행은_거르지_않고_기록만_쓰며_읽을_수_없는_기록은_종료_코드_2이고_검토자가_판정을_못_낸_실행은_기록을_바꾸지_않는다(self):
        """기록 파일이 없는 첫 실행은 모든 문장을 바뀐 것으로 보아 지적을 모두 남기고 기록을 쓰며, 깨진 기록은 2로 멈추고, 검토자가 실패한 실행은 기록을 그대로 둔다."""
        # given
        self.apply("c")
        draft = f"{FIRST}\n\n{SECOND}\n"
        failing = self.root / "failing.py"
        failing.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")

        # when
        code, result = self.review(draft, [finding("removable", SECOND)], "--history", str(self.history))
        stored = json.loads(self.history.read_text(encoding="utf-8"))
        failed_code, _ = self.review(f"{FIRST}\n", [], "--history", str(self.history), runner=failing)
        unchanged = json.loads(self.history.read_text(encoding="utf-8")) == stored
        self.history.write_text("not json", encoding="utf-8")
        broken = subprocess.run(
            [sys.executable, "-B", str(self.checkout / "scripts/text_review.py"), "review", "--kind", "pr-description", "--draft",
             str(self.root / "draft.md"), "--runner", str(self.runner), "--history", str(self.history)], capture_output=True, text=True)

        # then
        self.assertEqual((code, len(result["findings"]), stored["sentences"], stored["flagged"]), (1, 1, [FIRST, SECOND], [SECOND]))
        self.assertEqual((failed_code, unchanged), (3, True))
        self.assertEqual(broken.returncode, 2)
        self.assertIn("cannot read the history", broken.stderr)


class TwoReviewersTest(CandidateCase):
    def test_후보_b는_기본으로_검토자_둘을_부르고_reviews_1은_그대로_하나만_부른다(self):
        """기본 --reviews가 2로 바뀌어도 채점기처럼 --reviews 1을 주면 검토자는 하나다."""
        # given
        self.apply("b")
        calls = self.root / "calls.log"
        os.environ["FAKE_CALLS"] = str(calls)
        self.addCleanup(os.environ.pop, "FAKE_CALLS")

        # when
        self.review(f"{FIRST}\n", [])
        default = len(calls.read_text())
        self.review(f"{FIRST}\n", [], "--reviews", "1")
        explicit = len(calls.read_text()) - default

        # then
        self.assertEqual((default, explicit), (2, 1))


class LoopShapeTest(CandidateCase):
    """The session loop of the fixture tasks, run against the real script: apply each finding, run again, count the runs."""

    def session(self, label: str, mode: str, draft_name: str, *extra: str) -> tuple[int, list[dict], str]:
        draft = (REPO_ROOT / "evals/e2e/fixtures/loop-notes/notes" / draft_name).read_text(encoding="utf-8")
        log = self.root / f"stub-{label}.log"
        env = {**os.environ, "LOOP_STUB_MODE": mode, "LOOP_STUB_LOG": str(log)}
        runs = 0
        for _ in range(8):
            path = self.root / "draft.md"
            path.write_text(draft, encoding="utf-8")
            done = subprocess.run(
                [sys.executable, "-B", str(self.checkout / "scripts/text_review.py"), "review", "--kind", "pr-description", "--draft", str(path),
                 "--runner", str(LOOP_STUB), *extra], capture_output=True, text=True, env=env)
            runs += 1
            result = json.loads(done.stdout)
            if done.returncode == 0:
                break
            for item in result["findings"]:
                draft = draft.replace(item["quote"] + "\n\n", "").replace(item["quote"] + "\n", "")
        calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        return runs, calls, draft

    def test_후보_b는_서로_다른_문장을_보는_검토자_둘로_검토_실행_횟수를_줄인다(self):
        """한 검토자씩 부르면 지적 셋이 나뉘어 네 번 돌아야 끝나지만, 둘을 함께 부르면 세 번에 끝나고 두 경우 모두 올릴 글은 같다."""
        # given
        baseline = self.session("one", "split", "pr-draft-demo-m.md")
        self.apply("b")

        # when
        two = self.session("two", "split", "pr-draft-demo-m.md")

        # then
        self.assertEqual((baseline[0], len(baseline[1])), (4, 4))
        self.assertEqual((two[0], len(two[1])), (3, 6))
        self.assertEqual(baseline[2], two[2])

    def test_후보_c는_변하지_않은_문장의_늦은_지적을_버려_검토_실행_횟수를_줄이고_기록이_없으면_그대로다(self):
        """기록 없이 돌리면 늦은 지적이 세 번째 실행까지 이어지지만, 기록을 넘기면 그 지적이 버려져 두 번에 끝난다."""
        # given
        self.apply("c")
        without = self.session("without", "stale", "pr-draft-demo-n.md")

        # when
        with_history = self.session("with", "stale", "pr-draft-demo-n.md", "--history", str(self.history))

        # then
        self.assertEqual(without[0], 3)
        self.assertEqual(with_history[0], 2)
        self.assertIn("A refund equal to the charge is still accepted.", with_history[2])


class ApplyTest(CandidateCase):
    def test_후보는_고른_것만_바꾸고_두_번째_적용은_바꾸지_않으며_dry_run은_아무것도_쓰지_않는다(self):
        """a는 규칙 문서만, b는 스크립트의 기본 검토자 수만, c는 둘 다 바꾸고, 같은 조합을 다시 적용해도 파일이 그대로이며 --dry-run은 디스크를 건드리지 않는다."""
        # given
        original = {relative: self.text(relative) for relative in FILES}
        dry = run_apply(self.checkout, "--candidate", "a+b+c", "--dry-run")
        untouched = {relative: self.text(relative) for relative in FILES} == original

        # when
        self.apply("a")
        only_rules = {relative: self.text(relative) != original[relative] for relative in FILES}
        self.apply("b")
        self.apply("c")
        once = {relative: self.text(relative) for relative in FILES}
        again = run_apply(self.checkout, "--candidate", "a+b+c")

        # then
        self.assertTrue(untouched)
        self.assertIn("+DEFAULT_REVIEWS = 2", dry.stdout)
        self.assertEqual(only_rules, {"scripts/text_review.py": False, "instructions/shared-text.md": True})
        self.assertEqual((again.returncode, again.stdout.strip()), (0, "already applied"))
        self.assertEqual({relative: self.text(relative) for relative in FILES}, once)
        self.assertEqual(once["scripts/text_review.py"].count("DEFAULT_REVIEWS = 2"), 1)
        self.assertEqual(once["instructions/shared-text.md"].count("`--history <file>`"), 1)

    def test_한_파일의_기준_문장을_찾지_못하면_어느_파일도_바꾸지_않고_알_수_없는_후보는_거부한다(self):
        """규칙 문서의 기준 문장이 바뀌면 스크립트만 바뀐 반쪽 사본이 남지 않도록 종료 코드 2로 멈추고, a b c 밖의 이름이나 겹친 이름도 2로 거부한다."""
        # given
        rules = self.text("instructions/shared-text.md").replace("- Count only runs", "- Count runs")
        (self.checkout / "instructions/shared-text.md").write_text(rules, encoding="utf-8")
        script = self.text("scripts/text_review.py")

        # when
        stopped = run_apply(self.checkout, "--candidate", "a+b")
        unknown = run_apply(self.checkout, "--candidate", "d")
        repeated = run_apply(self.checkout, "--candidate", "b+b")

        # then
        self.assertEqual((stopped.returncode, unknown.returncode, repeated.returncode), (2, 2, 2))
        self.assertIn("anchor found 0 times", stopped.stderr)
        self.assertEqual((self.text("scripts/text_review.py"), self.text("instructions/shared-text.md")), (script, rules))


if __name__ == "__main__":
    unittest.main()
