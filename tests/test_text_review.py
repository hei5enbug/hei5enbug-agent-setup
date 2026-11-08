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
SCRIPT = REPO_ROOT / "scripts" / "text_review.py"
KINDS = (
    "pr-description", "review-reply", "issue-body", "ticket-comment", "commit-message",
    "chat-message", "shared-document", "final-report", "other",
)
DEFAULT_MODEL = "gpt-6.1-sol"

FAKE_RUNNER = textwrap.dedent(
    """
    import json, os, sys
    argv = sys.argv[1:]
    value = lambda flag: argv[argv.index(flag) + 1]
    capture = Path = None
    out = os.environ["FAKE_OUT"]
    with open(os.path.join(out, "started"), "a") as handle:
        handle.write("1\\n")
    mode = os.environ["FAKE_MODE"]
    if mode in ("split", "split3"):
        try:
            os.close(os.open(os.path.join(out, "first"), os.O_CREAT | os.O_EXCL))
            mode = "findings" if mode == "split" else "exit3"
        except FileExistsError:
            mode = "none"
    with open(os.path.join(out, "argv.json"), "w") as handle:
        json.dump(argv, handle)
    with open(os.path.join(out, "cwd.json"), "w") as handle:
        json.dump({"cwd": os.getcwd(), "git": os.path.isdir(os.path.join(os.getcwd(), ".git"))}, handle)
    with open(value("--assignment"), encoding="utf-8") as source:
        assignment = source.read()
    with open(os.path.join(out, "assignment.md"), "w", encoding="utf-8") as handle:
        handle.write(assignment)
    findings = {"findings": [{"type": "removable", "quote": "x", "reason": "y"}], "over_budget_facts": ["f1"]}
    clean = {"findings": []}
    if mode == "findings":
        open(value("--result"), "w").write("notes\\n```json\\n" + json.dumps(findings) + "\\n```\\n")
    elif mode == "none":
        open(value("--result"), "w").write("```json\\n" + json.dumps(clean) + "\\n```\\n")
    elif mode == "garbage":
        open(value("--result"), "w").write("```json\\n{not json\\n```\\n")
    elif mode == "badtype":
        open(value("--result"), "w").write('```json\\n{"findings": [{"type": "other", "quote": "a", "reason": "b"}]}\\n```\\n')
    print(json.dumps({"verified": mode != "exit3", "exit": 3 if mode == "exit3" else 0}))
    sys.exit(3 if mode == "exit3" else 0)
    """
)

CLEAN_DRAFT = "## Summary\n\nThe parser now rejects empty input.\n\n- Added a guard for empty input.\n- Updated the error text.\n"


def run_script(*args, stdin=None, env=None):
    merged = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], input=stdin, capture_output=True, text=True, env=merged, timeout=60,
    )


def rules_of(result):
    return [(item["rule"], item["line"]) for item in json.loads(result.stdout)["findings"]]


class CheckTest(unittest.TestCase):
    def check(self, text, *flags):
        return run_script("check", *flags, "-", stdin=text)

    def test_규칙에_걸리지_않는_초안은_발견_없이_종료_코드_0을_낸다(self):
        # given
        text = CLEAN_DRAFT
        # when
        result = self.check(text)
        # then
        self.assertEqual(0, result.returncode)
        self.assertEqual({"findings": []}, json.loads(result.stdout))

    def test_목록_항목_하나에_식별자_코드_세_개_이상이면_identifier_list로_보고한다(self):
        # given
        text = "intro\n- Added `user_id`, `user_name`, and `user_email` columns\n- Added `one` and `two`\n"
        # when
        result = self.check(text)
        # then
        self.assertEqual(1, result.returncode)
        self.assertEqual([("identifier-list", 2)], rules_of(result))

    def test_공백이_있는_코드_조각은_식별자로_세지_않는다(self):
        # given
        text = "- Ran `git status`, `git diff`, and `git log --oneline`\n"
        # when
        result = self.check(text)
        # then
        self.assertEqual(0, result.returncode)

    def test_표와_문장은_identifier_list로_보고하지_않는다(self):
        # given
        text = "| a | `x_1`, `x_2`, `x_3` |\n|---|---|\n\nProse with `a`, `b`, and `c` here.\n"
        # when
        result = self.check(text)
        # then
        self.assertEqual(0, result.returncode)

    def test_issue_body_종류에는_identifier_list를_적용하지_않는다(self):
        # given
        text = "- Touch `a_1`, `b_2`, and `c_3`\n"
        # when
        issue = self.check(text, "--kind", "issue-body")
        pull_request = self.check(text, "--kind", "pr-description")
        # then
        self.assertEqual(0, issue.returncode)
        self.assertEqual([("identifier-list", 1)], rules_of(pull_request))

    def test_펜스_코드_블록_안의_내용은_모든_규칙에서_제외한다(self):
        # given
        text = (
            "```\n- `a_1`, `b_2`, `c_3`\n- Tests: one\n- Tests: two\nNothing changes.\nABC-123\n"
            "[a](https://example.com/x) [b](https://example.com/x#y)\n```\n"
            "~~~~\nABC-123 stays unchanged\n~~~~\n"
        )
        # when
        result = self.check(text, "--no-ticket-keys")
        # then
        self.assertEqual(0, result.returncode)

    def test_펜스가_닫히기_전의_더_짧은_펜스는_블록을_끝내지_않는다(self):
        # given
        text = "````\n```\nABC-123\n````\nABC-124\n"
        # when
        result = self.check(text, "--no-ticket-keys")
        # then
        self.assertEqual([("ticket-key", 5)], rules_of(result))

    def test_티켓_키는_no_ticket_keys_옵션이_있을_때만_보고한다(self):
        # given
        text = "Fixes ABC-123 today\n"
        # when
        without = self.check(text)
        with_flag = self.check(text, "--no-ticket-keys")
        # then
        self.assertEqual(0, without.returncode)
        self.assertEqual([("ticket-key", 1)], rules_of(with_flag))

    def test_UTF_8이나_SHA_256_같은_표준_이름은_티켓_키로_보지_않는다(self):
        # given
        text = "Encode as UTF-8, hash with SHA-256, dates in ISO-8601, see RFC-9110.\n"
        # when
        result = self.check(text, "--no-ticket-keys")
        # then
        self.assertEqual(0, result.returncode)

    def test_URL_안과_코드_조각_안의_티켓_키는_보고하지_않는다(self):
        # given
        text = "See https://example.com/browse/ABC-123 and `ABC-124` and [t](docs/ABC-125.md).\n"
        # when
        result = self.check(text, "--no-ticket-keys")
        # then
        self.assertEqual(0, result.returncode)

    def test_같은_점검을_이름_붙인_뒤의_목록_항목은_repeated_check로_보고한다(self):
        # given
        text = "- `pytest tests/a`: passed\n- Lint: ok\n- `pytest   tests/a` passed again\n- lint: ok again\n"
        # when
        result = self.check(text)
        # then
        self.assertEqual([("repeated-check", 3), ("repeated-check", 4)], rules_of(result))

    def test_서로_다른_점검과_다른_목록의_같은_이름은_repeated_check가_아니다(self):
        # given
        text = "- `pytest a`: ok\n- `pytest b`: ok\n\n## Next\n\n- `pytest a`: ok\n"
        # when
        result = self.check(text)
        # then
        self.assertEqual(0, result.returncode)

    def test_바뀌지_않는다는_주장만_하는_문장은_unchanged_only로_보고한다(self):
        # given
        sentences = [
            "The API is unchanged.", "Defaults remain still unchanged.", "The cache does not change.",
            "Callers did not change.", "There are no changes to the schema.", "Nothing changes for users.",
            "스키마는 변경 없다.", "동작이 바뀌지 않는다.", "나머지는 그대로다.", "나머지는 그대로입니다.",
        ]
        for sentence in sentences:
            with self.subTest(sentence=sentence):
                # when
                result = self.check(f"{sentence}\n")
                # then
                self.assertEqual([("unchanged-only", 1)], rules_of(result))

    def test_같은_페이지를_가리키는_링크_둘은_뒤의_것을_same_page_links로_보고한다(self):
        # given
        text = (
            "See [guide](https://example.com/guide) first.\n\n"
            "Then https://example.com/guide#setup too.\n"
            "Unrelated [other](https://example.com/other#a) and [again](https://example.com/other).\n"
        )
        # when
        result = self.check(text)
        # then
        self.assertEqual([("same-page-links", 3), ("same-page-links", 4)], rules_of(result))

    def test_조각이_없는_같은_링크_둘과_다른_페이지는_same_page_links가_아니다(self):
        # given
        text = "[a](https://example.com/a) [b](https://example.com/a) [c](https://example.com/b#x) [d](#top) [e](#end)\n"
        # when
        result = self.check(text)
        # then
        self.assertEqual(0, result.returncode)

    def test_발견한_줄의_본문은_160자로_자른다(self):
        # given
        text = "Nothing changes " + "x" * 300 + "\n"
        # when
        result = self.check(text)
        # then
        self.assertEqual(160, len(json.loads(result.stdout)["findings"][0]["text"]))

    def test_읽을_수_없는_파일과_알_수_없는_종류는_종료_코드_2를_낸다(self):
        # given
        missing = "/nonexistent-dir/draft.md"
        # when
        unreadable = run_script("check", missing)
        unknown_kind = run_script("check", "--kind", "poem", "-", stdin="x")
        # then
        self.assertEqual(2, unreadable.returncode)
        self.assertEqual(2, unknown_kind.returncode)


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.out = self.root / "out"
        self.out.mkdir()
        self.runner = self.root / "fake_runner.py"
        self.runner.write_text(FAKE_RUNNER, encoding="utf-8")
        self.draft = self.root / "draft.md"
        self.draft.write_text(CLEAN_DRAFT, encoding="utf-8")

    def review(self, mode, *extra, kind="pr-description"):
        return run_script(
            "review", "--kind", kind, "--draft", str(self.draft), "--runner", str(self.runner), *extra,
            env={"FAKE_OUT": str(self.out), "FAKE_MODE": mode},
        )

    def argv(self):
        return json.loads((self.out / "argv.json").read_text(encoding="utf-8"))

    def assignment(self):
        return (self.out / "assignment.md").read_text(encoding="utf-8")

    def test_검토자는_호출한_폴더가_아니라_git_저장소로_만든_비공개_임시_폴더에서_실행한다(self):
        """Codex는 git 저장소가 아닌 폴더에서 실행을 거부하고 검토자는 사용자 작업 공간을 볼 필요가 없으므로, 실행기는 git 저장소인 임시 폴더에서 돈다."""
        # given
        caller = self.root / "not-a-repo"
        caller.mkdir()
        # when
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "review", "--kind", "pr-description", "--draft", str(self.draft),
             "--runner", str(self.runner)],
            cwd=caller, capture_output=True, text=True, timeout=60,
            env={**os.environ, "FAKE_OUT": str(self.out), "FAKE_MODE": "none"},
        )
        # then
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        place = json.loads((self.out / "cwd.json").read_text(encoding="utf-8"))
        self.assertTrue(place["git"])
        self.assertNotEqual(str(caller.resolve()), str(Path(place["cwd"]).resolve()))

    def test_기본으로_검토자_하나를_실행하고_reviews_2이면_둘을_동시에_실행한다(self):
        """검토자 둘이 평가에서 통과율을 올리지 못하고 비용만 두 배였으므로 기본은 하나이고, --reviews로만 늘린다."""
        for extra, expected in (((), 1), (("--reviews", "2"), 2)):
            with self.subTest(extra=extra):
                # given
                (self.out / "started").unlink(missing_ok=True)
                # when
                result = self.review("none", *extra)
                # then
                self.assertEqual(0, result.returncode, result.stdout)
                self.assertEqual(expected, len((self.out / "started").read_text().split()))

    def test_검토자_하나라도_발견을_내면_그_발견으로_종료_코드_1을_낸다(self):
        """두 검토 중 하나만 깨끗하면 통과가 아니므로, 다른 검토의 발견을 돌려주고 종료 코드 1을 낸다."""
        # given
        mode = "split"
        # when
        result = self.review(mode, "--reviews", "2")
        # then
        self.assertEqual(1, result.returncode, result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(["x"], [item["quote"] for item in payload["findings"]])
        self.assertEqual(2, len(payload["runners"]))

    def test_한_검토가_판정을_못_내고_다른_검토가_깨끗하면_통과가_아니라_종료_코드_3을_낸다(self):
        """확인 검토 하나가 빠진 채 통과시키면 두 번 깨끗해야 한다는 조건이 무너지므로 판정 없음으로 끝낸다."""
        # given
        mode = "split3"
        # when
        result = self.review(mode, "--reviews", "2")
        # then
        self.assertEqual(3, result.returncode, result.stdout)
        self.assertNotIn("findings", json.loads(result.stdout))

    def test_두_검토가_같은_발견을_내면_한_번만_보고한다(self):
        """같은 문장에 같은 종류의 발견이 두 번 보이면 작성자가 같은 수정을 두 번 하므로 하나로 합친다."""
        # given
        mode = "findings"
        # when
        result = self.review(mode, "--reviews", "2")
        # then
        self.assertEqual(1, result.returncode)
        self.assertEqual(1, len(json.loads(result.stdout)["findings"]))

    def test_최종_보고의_독자에게는_커밋하지_않은_변경처럼_남은_일이_필요한_사실로_적힌다(self):
        """검토자가 커밋하지 않았다는 문장을 지우라고 하면 사용자가 남은 일을 모르게 되므로, 최종 보고의 독자 문장이 그 사실을 필요하다고 적는다."""
        # given
        self.draft.write_text(CLEAN_DRAFT, encoding="utf-8")
        # when
        result = self.review("none", kind="final-report")
        # then
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertIn("an uncommitted change", self.assignment())

    def test_과제는_올릴_곳의_규칙이_요구하는_내용을_지울_거리로_보고하지_말라고_한다(self):
        """팀 규칙이 요구하는 검사 결과까지 지우라는 보고가 나오면 작성자가 끝없이 고치게 되므로, 과제에 규칙 우선 문장이 들어간다."""
        # given
        self.draft.write_text(CLEAN_DRAFT, encoding="utf-8")
        # when
        result = self.review("none")
        # then
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertIn("never report as removable what they require", self.assignment())

    def test_과제에는_글_종류마다_독자가_함께_보는_것이_적혀_diff_되풀이_판단이_종류에_맞는다(self):
        """최종 보고의 독자는 diff를 보지 않았고 PR 설명의 독자는 diff를 보므로, 과제에 종류별 독자 문장이 들어간다."""
        for kind, phrase in (("final-report", "has not read the diff"), ("pr-description", "sees the diff")):
            with self.subTest(kind):
                # given
                self.draft.write_text(CLEAN_DRAFT, encoding="utf-8")
                # when
                result = self.review("none", kind=kind)
                # then
                self.assertEqual(0, result.returncode, result.stdout)
                self.assertIn(phrase, self.assignment())

    def test_점검_발견이_있으면_검토자_실행기를_시작하지_않고_종료_코드_1을_낸다(self):
        # given
        self.draft.write_text("- `a_1`, `b_2`, `c_3`\n", encoding="utf-8")
        # when
        result = self.review("none")
        # then
        self.assertEqual(1, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("check", payload["stage"])
        self.assertEqual("identifier-list", payload["findings"][0]["rule"])
        self.assertFalse((self.out / "started").exists())

    def test_검토자가_발견을_돌려주면_종료_코드_1과_발견_목록을_낸다(self):
        # given
        mode = "findings"
        # when
        result = self.review(mode)
        # then
        self.assertEqual(1, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("review", payload["stage"])
        self.assertEqual("pr-description", payload["kind"])
        self.assertEqual("removable", payload["findings"][0]["type"])
        self.assertEqual(["f1"], payload["over_budget_facts"])
        self.assertEqual({"exit": 0, "verified": True}, payload["runner"])

    def test_검토자가_발견을_돌려주지_않으면_종료_코드_0을_낸다(self):
        # given
        mode = "none"
        # when
        result = self.review(mode)
        # then
        self.assertEqual(0, result.returncode)
        self.assertEqual([], json.loads(result.stdout)["findings"])

    def test_실행기가_0이_아닌_코드로_끝나면_통과로_보지_않고_종료_코드_3을_낸다(self):
        # given
        mode = "exit3"
        # when
        result = self.review(mode)
        # then
        self.assertEqual(3, result.returncode)
        payload = json.loads(result.stdout)
        self.assertIn("error", payload)
        self.assertNotIn("findings", payload)
        self.assertEqual(3, payload["runner"]["exit"])

    def test_결과_파일이_없거나_해석할_수_없으면_통과로_보지_않고_종료_코드_3을_낸다(self):
        # given
        modes = ["missing", "garbage", "badtype"]
        for mode in modes:
            with self.subTest(mode=mode):
                # when
                result = self.review(mode)
                # then
                self.assertEqual(3, result.returncode)
                self.assertIn("error", json.loads(result.stdout))

    def test_배정서에는_초안과_모든_규칙_자료_메모가_들어간다(self):
        # given
        rules = [self.root / "rules_a.md", self.root / "rules_b.md"]
        sources = [self.root / "request.md", self.root / "diff.patch"]
        for index, path in enumerate([*rules, *sources]):
            path.write_text(f"body-{index}\n", encoding="utf-8")
        flags = []
        for path in rules:
            flags += ["--rules", str(path)]
        for path in sources:
            flags += ["--source", str(path)]
        flags += ["--note", "keep the restart sentence", "--note", "second reason"]
        # when
        result = self.review("none", *flags)
        # then
        self.assertEqual(0, result.returncode)
        text = self.assignment()
        for fragment in ["rules_a.md", "rules_b.md", "request.md", "diff.patch", "body-0", "body-1", "body-2", "body-3",
                         "keep the restart sentence", "second reason", "The parser now rejects empty input."]:
            self.assertIn(fragment, text)

    def test_길이_예산_줄은_예산을_줄_때만_초안_글자_수와_함께_들어간다(self):
        # given
        budget = "1500"
        # when
        self.review("none")
        without = self.assignment()
        self.review("none", "--budget", budget)
        with_budget = self.assignment()
        # then
        self.assertNotIn("Length budget:", without)
        self.assertIn(f"Length budget: {budget} characters", with_budget)
        self.assertIn(f"{len(CLEAN_DRAFT)} characters", with_budget)

    def test_파일을_감싸는_펜스는_파일_안의_백틱_연속보다_길다(self):
        # given
        source = self.root / "diff.patch"
        source.write_text("before\n`````\ninner\n`````\nafter\n", encoding="utf-8")
        # when
        self.review("none", "--source", str(source))
        # then
        self.assertIn("``````\nbefore\n`````\ninner\n`````\nafter\n``````", self.assignment())

    def test_종류별_기본_모델과_model_덮어쓰기가_실행기_인자에_전달된다(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                # when
                result = self.review("none", kind=kind)
                argv = self.argv()
                # then
                self.assertEqual(0, result.returncode)
                self.assertEqual("reviewer", argv[0])
                self.assertEqual(DEFAULT_MODEL, argv[argv.index("--model") + 1])
                self.assertEqual("600", argv[argv.index("--timeout") + 1])
        # when
        self.review("none", "--model", "claude-opus-5-5", "--timeout", "90")
        argv = self.argv()
        # then
        self.assertEqual("claude-opus-5-5", argv[argv.index("--model") + 1])
        self.assertEqual("90", argv[argv.index("--timeout") + 1])

    def test_임시_폴더는_실행_뒤에_지워진다(self):
        # given
        mode = "none"
        # when
        self.review(mode)
        argv = self.argv()
        # then
        self.assertFalse(Path(argv[argv.index("--assignment") + 1]).parent.exists())

    def test_사용법_오류는_종료_코드_2를_낸다(self):
        # given
        base = ["review", "--kind", "pr-description"]
        # when
        no_draft = run_script(*base)
        bad_budget = run_script(*base, "--draft", str(self.draft), "--budget", "0")
        unreadable_rules = run_script(*base, "--draft", str(self.draft), "--rules", "/nonexistent-dir/r.md")
        # then
        self.assertEqual(2, no_draft.returncode)
        self.assertEqual(2, bad_budget.returncode)
        self.assertEqual(2, unreadable_rules.returncode)


if __name__ == "__main__":
    unittest.main()
