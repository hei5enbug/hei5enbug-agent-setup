from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock


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
    if mode in ("split", "split3", "splitlimit", "splitmixed"):
        try:
            os.close(os.open(os.path.join(out, "first"), os.O_CREAT | os.O_EXCL))
            mode = {"split": "findings", "split3": "exit3"}.get(mode, "usage")
        except FileExistsError:
            mode = {"splitmixed": "auth"}.get(mode, "none")
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
    if mode == "usage":
        print(os.environ.get("FAKE_LIMIT_TEXT", "You have reached your usage limit"), file=sys.stderr if os.environ.get("FAKE_LIMIT_STDERR") else sys.stdout)
        sys.exit(1)
    if mode == "auth":
        print("authentication failed", file=sys.stderr)
        sys.exit(1)
    if mode == "silent":
        sys.exit(1)
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


def rules_of(result, key="findings"):
    return [(item["rule"], item["line"]) for item in json.loads(result.stdout)[key]]


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
        self.assertEqual({"findings": [], "advisories": []}, json.loads(result.stdout))

    def test_목록_항목_하나에_식별자_코드_세_개_이상이면_발견이_아니라_identifier_list_권고로_보고한다(self):
        """올릴 곳의 규칙이 요구하는 이름 나열 줄에서 점검이 멈추면 검토자가 판단할 수 없으므로, 종료 코드 0과 권고로 낸다."""
        # given
        text = "intro\n- Added `demo_a`, `demo_b`, and `demo_c` columns\n- Added `one` and `two`\n"
        # when
        result = self.check(text, "--kind", "pr-description")
        # then
        self.assertEqual(0, result.returncode)
        self.assertEqual([], rules_of(result))
        self.assertEqual([("identifier-list", 2)], rules_of(result, "advisories"))

    def test_최종_보고가_통과하면_정규화한_해시를_내고_다른_종류와_실패한_점검에는_내지_않는다(self):
        # given
        text = CLEAN_DRAFT
        padded = "\n\n" + CLEAN_DRAFT.replace("\n\n", "  \n\n\n\n") + "\n\n"
        # when
        passed = self.check(text, "--kind", "final-report")
        padded_result = self.check(padded, "--kind", "final-report")
        other = self.check(text, "--kind", "pr-description")
        failed = self.check("- Ran `make check`.\n- Ran `make check`.\n", "--kind", "final-report")
        # then
        digest = json.loads(passed.stdout)["final_report_sha256"]
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertEqual(digest, json.loads(padded_result.stdout)["final_report_sha256"])
        self.assertNotIn("final_report_sha256", json.loads(other.stdout))
        self.assertEqual(1, failed.returncode)
        self.assertNotIn("final_report_sha256", json.loads(failed.stdout))

    def test_모델_이름과_effort는_글만_보는_점검에서_발견으로_보고하지_않는다(self):
        """도구 표시는 패턴 점검이 아니라 규칙과 독립 검토로 거른다고 정했으므로, 모델 이름이 든 글도 점검은 통과한다."""
        # given
        text = "Document review by demo-model-x at effort high applied 3 findings.\n"
        # when
        result = self.check(text, "--kind", "pr-description")
        # then
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertEqual({"findings": [], "advisories": []}, json.loads(result.stdout))

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

    def test_최종_보고도_식별자_목록_줄이_있으면_발견_없이_통과하고_해시를_낸다(self):
        """최종 보고의 점검 통과 해시가 권고 때문에 빠지면 보고를 올릴 수 없으므로, 권고가 있어도 해시를 낸다."""
        # given
        text = "Fixed the parser.\n\n- Added `demo_a`, `demo_b`, and `demo_c` columns\n"
        # when
        result = self.check(text, "--kind", "final-report")
        # then
        payload = json.loads(result.stdout)
        self.assertEqual(0, result.returncode)
        self.assertEqual([("identifier-list", 3)], rules_of(result, "advisories"))
        self.assertRegex(payload["final_report_sha256"], r"^[0-9a-f]{64}$")

    def test_issue_body_종류는_식별자_목록에_발견도_권고도_내지_않는다(self):
        # given
        text = "- Touch `a_1`, `b_2`, and `c_3`\n"
        # when
        issue = self.check(text, "--kind", "issue-body")
        pull_request = self.check(text, "--kind", "pr-description")
        # then
        self.assertEqual({"findings": [], "advisories": []}, json.loads(issue.stdout))
        self.assertEqual([("identifier-list", 1)], rules_of(pull_request, "advisories"))

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

    def test_바뀌지_않는다는_주장만_하는_문장은_발견이_아니라_unchanged_only_권고로_보고한다(self):
        """독자가 틀리게 행동할 수 있어 필요한 바뀌지 않는다는 문장이 점검 단계에서 글 게시를 막지 않도록, 권고로만 보고하고 종료 코드 0을 낸다."""
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
                self.assertEqual(0, result.returncode)
                self.assertEqual([], json.loads(result.stdout)["findings"])
                self.assertEqual([("unchanged-only", 1)], rules_of(result, "advisories"))

    def test_바뀌지_말라는_명령문은_발견도_권고도_아니다(self):
        """변경하지 말라는 지시를 바뀌지 않는다는 주장으로 오인해 표시하지 않도록, does와 did만 주장으로 본다."""
        # given
        text = "Do not change the schema before the backup finishes.\n"
        # when
        result = self.check(text)
        # then
        self.assertEqual(0, result.returncode)
        self.assertEqual({"findings": [], "advisories": []}, json.loads(result.stdout))

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
        self.assertEqual(160, len(json.loads(result.stdout)["advisories"][0]["text"]))

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

    def test_최종_보고를_뺀_모든_종류의_과제에만_도구_표시를_지울_거리로_보고하라는_항목이_있다(self):
        """작성자가 모델 이름과 effort를 적은 글을 검토자가 통과시키면 안 되지만 최종 보고에는 그 항목이 없어야 하므로, 종류별 과제를 비교한다."""
        for kind in KINDS:
            with self.subTest(kind):
                # given
                self.draft.write_text(CLEAN_DRAFT, encoding="utf-8")
                # when
                result = self.review("none", kind=kind)
                # then
                self.assertEqual(0, result.returncode, result.stdout)
                self.assertEqual(kind != "final-report", "Tool mark item of the cut pass" in self.assignment())

    def test_도구_표시_항목은_제목과_첫_문장에도_적용하고_서명_한_줄만_남긴다고_적는다(self):
        """REVIEWER_INSTRUCTIONS가 제목과 커밋 제목을 지울 수 없다고 하므로 항목이 그 예외를 풀고, 서명 한 줄 말고는 규칙이 요구해도 남기지 않는다고 적어야 한다."""
        # given
        self.draft.write_text(CLEAN_DRAFT, encoding="utf-8")
        # when
        result = self.review("none", kind="commit-message")
        # then
        self.assertEqual(0, result.returncode, result.stdout)
        item = self.assignment().split("Tool mark item of the cut pass", 1)[1].split("Answer with one JSON", 1)[0]
        for fragment in ("inside a title, a heading, a commit subject, or the opening sentence", "never the whole element",
                         "last-line agent signature", "no other signature, credit, or provenance line is excepted",
                         "request asks the text to name a tool"):
            self.assertIn(" ".join(fragment.split()), " ".join(item.split()))

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
        """식별자 목록을 권고로 내린 뒤에도 같은 점검 단계 정지가 나머지 세 규칙에는 남아야 하므로, 규칙마다 확인한다."""
        cases = {
            "repeated-check": ("- Ran `make check`.\n- Ran `make check`.\n", ()),
            "ticket-key": ("Fixes ABC-123.\n", ("--no-ticket-keys",)),
            "same-page-links": ("See https://example.com/a and https://example.com/a#b.\n", ()),
        }
        for rule, (text, flags) in cases.items():
            with self.subTest(rule):
                # given
                self.draft.write_text(text, encoding="utf-8")
                # when
                result = self.review("none", *flags)
                # then
                self.assertEqual(1, result.returncode)
                payload = json.loads(result.stdout)
                self.assertEqual("check", payload["stage"])
                self.assertEqual(rule, payload["findings"][0]["rule"])
                self.assertFalse((self.out / "started").exists())

    def test_식별자_목록_줄은_점검에서_멈추지_않고_검토자_과제에_그_규칙의_설명과_함께_들어간다(self):
        """식별자 목록이 점검에서 멈추면 검토자와 메모가 판단할 수 없고, '바뀌지 않는다' 설명이 붙으면 검토자가 요구된 이름을 지울 거리로 보므로, 이 규칙의 설명만 붙여 검토자를 실행한다."""
        # given
        self.draft.write_text("The lock now covers the refresh.\n\n- Added `demo_a`, `demo_b`, and `demo_c`.\n", encoding="utf-8")
        # when
        result = self.review("none", kind="review-reply")
        # then
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertTrue((self.out / "started").exists())
        text = self.assignment()
        self.assertIn("## Lines the text check flagged", text)
        self.assertIn("```\n- Added `demo_a`, `demo_b`, and `demo_c`.\n```", text)
        self.assertIn("three or more identifier names", text)
        self.assertIn("Never report it when the destination's writing rules require those names", text)
        self.assertNotIn("say only that something is unchanged", text)

    def test_바뀌지_않는다는_줄만_있으면_그_규칙의_설명만_붙고_두_규칙의_줄이_섞이면_각_설명이_자기_줄_앞에_붙는다(self):
        """설명이 규칙마다 따로여야 검토자가 식별자 줄에 '바뀌지 않는다' 기준을 적용하지 않으므로, 있는 규칙의 설명만 그 규칙의 줄 앞에 둔다."""
        # given
        unchanged = "The cache does not change."
        names = "- Added `demo_a`, `demo_b`, and `demo_c`."
        self.draft.write_text(unchanged + "\n", encoding="utf-8")
        # when
        self.review("none")
        only = self.assignment()
        self.draft.write_text(f"{unchanged}\n\n{names}\n", encoding="utf-8")
        self.review("none")
        mixed = self.assignment()
        # then
        self.assertIn("say only that something is unchanged", only)
        self.assertNotIn("identifier names", only)
        unchanged_at = mixed.index("say only that something is unchanged")
        names_at = mixed.index("three or more identifier names")
        self.assertLess(unchanged_at, mixed.index(f"```\n{unchanged}\n```"))
        self.assertLess(mixed.index(f"```\n{unchanged}\n```"), names_at)
        self.assertLess(names_at, mixed.index(f"```\n{names}\n```"))

    def test_바뀌지_않는다는_문장은_점검에서_멈추지_않고_검토자_과제에_표시한_줄로_들어간다(self):
        """권고가 점검 단계에서 검토자에게 닿기 전에 멈추면 검토자와 메모가 판단할 수 없으므로, 과제에 표시한 줄 구역을 넣어 검토자를 실행한다."""
        # given
        self.draft.write_text("The cache does not change.\n", encoding="utf-8")
        # when
        result = self.review("none")
        # then
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertTrue((self.out / "started").exists())
        text = self.assignment()
        self.assertIn("## Lines the text check flagged", text)
        self.assertIn("```\nThe cache does not change.\n```", text)

    def test_표시한_줄이_없으면_과제에_표시한_줄_구역이_없다(self):
        """권고가 없는데 구역이 들어가면 검토자가 없는 줄을 찾으려 하므로, 권고가 있을 때만 구역을 넣는다."""
        # given
        mode = "none"
        # when
        self.review(mode)
        # then
        self.assertNotIn("Lines the text check flagged", self.assignment())

    def test_git이_없어_준비가_실패하면_트레이스백이_아니라_error를_내고_종료_코드_3을_낸다(self):
        """준비 단계의 OSError가 종료 코드 1의 트레이스백이 되면 평가 도구가 발견으로 읽으므로, 판정 없음으로 종료 코드 3을 낸다."""
        # given
        empty = self.root / "empty-bin"
        empty.mkdir()
        # when
        result = run_script(
            "review", "--kind", "pr-description", "--draft", str(self.draft), "--runner", str(self.runner),
            env={"FAKE_OUT": str(self.out), "FAKE_MODE": "none", "PATH": str(empty)},
        )
        # then
        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("error", json.loads(result.stdout))
        self.assertNotIn("Traceback", result.stderr)

    def test_실행기_바깥_제한_시간은_실행기의_순차_단계_전체보다_길다(self):
        """실행기가 단계마다 전체 제한 시간을 쓰므로 바깥 제한이 짧으면 실행기가 정리하기 전에 죽으므로, 바깥 제한은 제한 시간의 4배 이상이다."""
        # given
        spec = importlib.util.spec_from_file_location("text_review_under_test", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        seen = {}

        def capture(command, **kwargs):
            if "timeout" in kwargs:
                seen["timeout"] = kwargs["timeout"]
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        timeout = 90
        args = module.build_parser().parse_args(
            ["review", "--kind", "other", "--draft", "-", "--timeout", str(timeout), "--runner", str(self.runner)])
        # when
        with mock.patch.object(module.subprocess, "run", capture):
            with self.assertRaises(module.TextReviewError):
                module.run_reviewer(args, "assignment", "gpt-6.1-sol")
        # then
        self.assertGreaterEqual(seen["timeout"], 4 * timeout)

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

    def test_최종_보고_검토가_통과하면_해시를_내고_발견이_있거나_다른_종류이면_내지_않는다(self):
        # given
        digest = self.load_digest(CLEAN_DRAFT)
        # when
        passed = self.review("none", kind="final-report")
        found = self.review("findings", kind="final-report")
        other = self.review("none")
        # then
        self.assertEqual(digest, json.loads(passed.stdout)["final_report_sha256"])
        self.assertNotIn("final_report_sha256", json.loads(found.stdout))
        self.assertNotIn("final_report_sha256", json.loads(other.stdout))

    def load_digest(self, text):
        spec = importlib.util.spec_from_file_location("text_review_digest", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.report_digest(text)

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

    def test_실행기가_사용량_한도_메시지를_내고_실패하면_종료_코드_4와_usage_limit_사유와_그_메시지를_낸다(self):
        """사용량 한도를 다른 검토 실패와 같은 종료 코드 3으로 내면 글을 올릴 때마다 같은 질문을 되풀이한다."""
        messages = [("You have reached your usage limit", ""), ("You've hit your usage limit. Try again later.", ""),
                    ("Claude usage limit reached", "1")]
        for text, on_stderr in messages:
            with self.subTest(text=text, on_stderr=bool(on_stderr)):
                # given
                env = {"FAKE_LIMIT_TEXT": text, "FAKE_LIMIT_STDERR": on_stderr}
                # when
                result = run_script("review", "--kind", "pr-description", "--draft", str(self.draft), "--runner",
                                    str(self.runner), env={"FAKE_OUT": str(self.out), "FAKE_MODE": "usage", **env})
                # then
                payload = json.loads(result.stdout)
                self.assertEqual(4, result.returncode, result.stdout)
                self.assertEqual("usage_limit", payload["reason"])
                self.assertIn(text, payload["error"])
                self.assertNotIn("findings", payload)

    def test_사용량_한도가_아닌_실행기_실패는_종료_코드_3으로_내고_표준_오류의_원인을_담는다(self):
        """인증 실패를 사용량 한도로 오인해 묻지 않고 올리면 안 되며, 원인이 detail에 보여야 사용자가 조치한다."""
        # given
        mode = "auth"
        # when
        result = self.review(mode)
        # then
        payload = json.loads(result.stdout)
        self.assertEqual(3, result.returncode)
        self.assertNotIn("reason", payload)
        self.assertIn("authentication failed", payload["error"])

    def test_실행기가_아무것도_출력하지_않으면_detail은_출력이_없다고_밝힌다(self):
        """원인이 빈 채 `exited with 1:`로 끝나면 사용자가 원인을 알 수 없고, 상태 줄만 있어도 그 줄을 원인으로 되풀이하지 않는다."""
        for mode in ("silent", "exit3"):
            with self.subTest(mode=mode):
                # given / when
                result = self.review(mode)
                # then
                payload = json.loads(result.stdout)
                self.assertEqual(3, result.returncode)
                self.assertTrue(payload["error"].endswith("the runner gave no output"), payload["error"])

    def test_검토가_둘이고_하나만_사용량_한도이면_종료_코드_3이다(self):
        """한 검토가 한도가 아닌 이유로 실패하거나 깨끗하게 끝났으면 한도 결과로 건너뛰지 않고 묻는다."""
        for mode, needle in (("splitlimit", None), ("splitmixed", "authentication failed")):
            with self.subTest(mode=mode):
                # given
                out = self.root / f"out-{mode}"
                out.mkdir()
                # when
                result = run_script("review", "--kind", "pr-description", "--draft", str(self.draft), "--runner",
                                    str(self.runner), "--reviews", "2", env={"FAKE_OUT": str(out), "FAKE_MODE": mode})
                # then
                payload = json.loads(result.stdout)
                self.assertEqual(3, result.returncode, result.stdout)
                self.assertNotIn("reason", payload)
                if needle:
                    self.assertIn(needle, payload["error"])

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
