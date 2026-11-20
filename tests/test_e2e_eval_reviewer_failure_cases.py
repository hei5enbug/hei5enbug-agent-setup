"""Offline proof of the reviewer-failure cases T102 and T109: what counts as a post, a question, and a review call on each host."""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TASKS_ROOT = REPO_ROOT / "evals/e2e/tasks"
TEXT_REVIEW = "python3 '/plugin/scripts/text_review.py' review --kind pr-description --draft /tmp/work/pr.md"
HEREDOC_NAMING_THE_SCRIPT = "python3 - <<'PY'\nfrom pathlib import Path\np = Path('/tmp/work')\n(p / 'a.txt').write_text('''Independent text_review.py review returned exit 3.''')\nPY"


def load(name: str):
    module = types.ModuleType(f"case_{name}")
    exec(compile((TASKS_ROOT / "custom" / f"{name}.py").read_text(encoding="utf-8"), name, "exec"), module.__dict__)
    return module


def bash(command: str) -> dict:
    return {"name": "Bash", "input": {"command": command}, "source": "main"}


class ReviewerFailureCasesTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "repo").mkdir()
        self.t102, self.t109 = load("T102"), load("T109")

    def ctx(self, gh_log: str = "", host: str | None = None, answer: str = "", calls: list | None = None):
        (self.root / "gh-calls.log").write_text(gh_log, encoding="utf-8")
        view = {"final_answer": answer, "tool_calls": calls or []}
        if host:
            view["host"] = host
        return types.SimpleNamespace(origin=self.root / "repo", view=view, tasks_root=TASKS_ROOT)

    def test_pr_create_help는_게시가_아니다(self):
        """gh pr create --help는 게시 호출로 세지 않아 T109 not-posted가 통과하고 T102 posted-once는 0건이다."""
        # given
        ctx = self.ctx("auth status\npr create --help\n")

        # when
        not_posted = self.t109.not_posted(ctx)
        posted = self.t102.posted_once(ctx)

        # then
        self.assertTrue(not_posted[0])
        self.assertFalse(posted[0])

    def test_제목과_본문_파일이_있는_pr_create는_게시다(self):
        """실제 게시 호출은 한 건으로 세고 T109 not-posted는 실패한다."""
        # given
        ctx = self.ctx("pr create --help\npr create --title T --body-file pr.md\n")

        # when
        posted = self.t102.posted_once(ctx)
        not_posted = self.t109.not_posted(ctx)

        # then
        self.assertTrue(posted[0])
        self.assertFalse(not_posted[0])

    def test_Codex는_질문이_든_문단을_질문으로_읽고_원인은_그_문단에서_찾는다(self):
        """Codex에는 AskUserQuestion이 없으므로 최종 답의 물음표 줄이 든 문단이 한 번의 질문이다."""
        # given
        answer = "게시를 보류했습니다.\n\n`Authentication failed`로 검토가 실행되지 않았습니다. 그대로 게시할까요?\n\n참고 문서입니다."
        ctx = self.ctx(host="codex", answer=answer)

        # when
        results = (self.t109.one_question(ctx), self.t109.cause_shown(ctx), self.t102.no_question(ctx))

        # then
        self.assertEqual([r[0] for r in results], [True, True, False])

    def test_Codex_최종_답에_물음표가_없으면_질문이_없다(self):
        """게시하고 한도 한 줄만 알리는 답은 질문이 없어 T102 no-question-asked를 통과한다."""
        # given
        ctx = self.ctx(host="codex", answer="PR을 만들었습니다.\n\n독립 검토는 사용 한도로 실행되지 않았습니다.")

        # when
        result = self.t102.no_question(ctx)

        # then
        self.assertTrue(result[0])

    def test_Claude는_AskUserQuestion_호출만_질문이다(self):
        """Claude 실행은 최종 답의 물음표를 세지 않고 AskUserQuestion 입력에서 원인을 찾는다."""
        # given
        call = {"name": "AskUserQuestion", "input": {"question": "login has expired. Post anyway?"}}
        asked = self.ctx(answer="끝났습니다?", calls=[call])
        silent = self.ctx(answer="Post anyway?")

        # when
        results = (self.t109.one_question(asked), self.t109.cause_shown(asked), self.t102.no_question(silent))

        # then
        self.assertEqual([r[0] for r in results], [True, True, True])

    def test_review_호출은_text_review_실행만_세고_heredoc_본문과_help는_세지_않는다(self):
        """스크립트 이름이 본문에만 나오는 heredoc과 --help는 검토 호출이 아니다."""
        # given
        calls = [bash(HEREDOC_NAMING_THE_SCRIPT), bash("python3 '/plugin/scripts/text_review.py' review --help"), bash(TEXT_REVIEW),
                 bash(TEXT_REVIEW), bash(TEXT_REVIEW)]
        three = self.ctx(calls=calls)
        two = self.ctx(calls=calls[:4])

        # when
        results = (self.t102.no_second_reviewer(three), self.t102.no_second_reviewer(two))

        # then
        self.assertEqual([r[0] for r in results], [False, True])
        self.assertIn("3 review call(s)", results[0][1])

    def test_따옴표로_닫힌_경로의_Claude_reviewer_실행도_둘째_검토자로_센다(self):
        """python3 '<경로>/role_runner.py' reviewer --model claude-...는 Claude 검토자 실행이다."""
        # given
        ctx = self.ctx(calls=[bash("python3 '/plugin/scripts/role_runner.py' reviewer --model claude-opus-5-5 --assignment /tmp/a")])

        # when
        result = self.t102.no_second_reviewer(ctx)

        # then
        self.assertFalse(result[0])
        self.assertIn("1 same-family reviewer launch", result[1])


    def test_Codex에서는_Claude_검증_검토자는_허용하고_GPT_검토자를_둘째_검토자로_센다(self):
        """Codex 작성자에게는 Claude reviewer가 교차 계열 검증이고, 같은 계열인 GPT reviewer가 둘째 검토자다."""
        # given
        claude = bash("python3 '/plugin/scripts/role_runner.py' reviewer --model claude-opus-5-5 --assignment /tmp/a")
        gpt = bash("python3 '/plugin/scripts/role_runner.py' reviewer --model gpt-6.1-sol --assignment /tmp/a")
        allowed = self.ctx(host="codex", calls=[claude, bash(TEXT_REVIEW)])
        refused = self.ctx(host="codex", calls=[gpt])

        # when
        results = (self.t102.no_second_reviewer(allowed), self.t102.no_second_reviewer(refused))

        # then
        self.assertEqual([r[0] for r in results], [True, False])


if __name__ == "__main__":
    unittest.main()
