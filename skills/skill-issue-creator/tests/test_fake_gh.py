#!/usr/bin/env python3
"""평가용 가짜 gh가 같은 평가 안에서 만든 이슈와 댓글을 되읽을 수 있게 상태를 유지하는지 검사한다."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
FAKE_GH = Path(os.environ.get("FAKE_GH_UNDER_TEST", SKILL / "evals" / "files" / "bin" / "gh"))
FIXTURE = SKILL / "evals" / "files" / "trackers" / "demo-org_demo-a.json"
REPO = "demo-org/demo-a"
BODY = "## Summary\nThe skill dropped a gap.\n\n## Proposal\n- Keep the gap.\n- Report it.\n"
ACTOR = "{user: .user.login, body}"


class FakeGhCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.log = self.base / "gh.log"
        self.env = {**os.environ, "FAKE_GH_LOG": str(self.log)}
        self.env.pop("FAKE_GH_STATE", None)
        self.env.pop("FAKE_GH_BREAK_FIRST_RENDER", None)

    def gh(self, *args: str, stdin: str = "", env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(FAKE_GH), *args], input=stdin, text=True, capture_output=True,
                              env={**self.env, **(env or {})}, check=False)

    def create(self, body: str = BODY, env: dict[str, str] | None = None) -> str:
        result = self.gh("issue", "create", "--repo", REPO, "--title", "demo title", "--label", "bug",
                         "--body-file", "-", stdin=body, env=env)
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout.strip()

    def rendered(self, number: int) -> str:
        result = self.gh("api", f"repos/{REPO}/issues/{number}", "-H", "Accept: application/vnd.github.html+json",
                         "--jq", ".body_html")
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout


class StatefulReadBackTests(FakeGhCase):
    def test_만든_이슈를_번호로_다시_읽으면_요청한_이슈의_제목과_본문을_돌려준다(self) -> None:
        """issue view 200은 고정 목록이 아니라 방금 만든 이슈를 돌려준다."""
        # given
        url = self.create()

        # when
        result = self.gh("issue", "view", "200", "--repo", REPO, "--json", "number,title,body,labels")

        # then
        self.assertEqual(f"https://github.com/{REPO}/issues/200", url)
        self.assertEqual({"number": 200, "title": "demo title", "body": BODY, "labels": [{"name": "bug"}]},
                         json.loads(result.stdout))

    def test_기존_이슈는_번호로_읽히고_만든_이슈는_목록에_더해진다(self) -> None:
        """fixture의 98번과 101번은 그대로 읽히고, issue list에는 만든 이슈가 더해진다."""
        # given
        self.create()

        # when
        view = self.gh("issue", "view", "101", "--repo", REPO, "--json", "number,author")
        listing = self.gh("issue", "list", "--repo", REPO, "--state", "all")

        # then
        self.assertEqual({"number": 101, "author": {"login": "demo-user"}}, json.loads(view.stdout))
        self.assertEqual([98, 101, 200], [issue["number"] for issue in json.loads(listing.stdout)])

    def test_없는_이슈_번호는_실패하고_고정_파일을_바꾸지_않는다(self) -> None:
        """존재하지 않는 번호를 읽으면 실패하고, 쓰기 명령은 fixture 파일을 바꾸지 않는다."""
        # given
        before = FIXTURE.read_text(encoding="utf-8")
        self.create()

        # when
        result = self.gh("issue", "view", "999", "--repo", REPO, "--json", "number")

        # then
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(before, FIXTURE.read_text(encoding="utf-8"))

    def test_본문_수정과_댓글은_다시_읽을_때_반영되고_기존_이슈는_목록에_한_번만_나온다(self) -> None:
        """issue edit은 본문을 바꾸고 issue comment는 마지막 댓글로 읽히며 98번이 둘로 갈라지지 않는다."""
        # given
        self.create()

        # when
        self.gh("issue", "edit", "200", "--repo", REPO, "--body-file", "-", stdin="## Summary\nEdited.\n")
        self.gh("issue", "comment", "98", "--repo", REPO, "--body-file", "-", stdin="Same gap, new case.\n")
        edited = self.gh("issue", "view", "200", "--repo", REPO, "--json", "body", "--jq", ".body")
        comment = self.gh("issue", "view", "98", "--repo", REPO, "--json", "comments", "--jq", ".comments[-1]")
        original = self.gh("issue", "view", "98", "--repo", REPO, "--json", "body", "--jq", ".body")
        listing = self.gh("issue", "list", "--repo", REPO)

        # then
        self.assertEqual("## Summary\nEdited.", edited.stdout.rstrip("\n"))
        self.assertEqual(("demo-user", "Same gap, new case.\n"),
                         (json.loads(comment.stdout)["author"]["login"], json.loads(comment.stdout)["body"]))
        self.assertIn("custom changelog template", original.stdout)
        self.assertEqual([98, 101, 200], [issue["number"] for issue in json.loads(listing.stdout)])

    def test_댓글_링크의_아이디로_댓글을_읽고_고친_뒤_다시_읽으면_고친_본문이_나온다(self) -> None:
        """issue comment가 #issuecomment-아이디 링크를 내고, gh api가 그 아이디의 댓글을 읽고 PATCH로 고친다."""
        # given
        link = self.gh("issue", "comment", "98", "--repo", REPO, "--body-file", "-", stdin="First draft.\n").stdout
        identifier = link.strip().rsplit("#issuecomment-", 1)[1]
        path = f"repos/{REPO}/issues/comments/{identifier}"

        # when
        before = self.gh("api", path, "--jq", ACTOR)
        self.gh("api", "-X", "PATCH", path, "-F", "body=@-", stdin="Corrected body.\n")
        after = self.gh("api", path, "--jq", ACTOR)

        # then
        self.assertTrue(link.startswith(f"https://github.com/{REPO}/issues/98#issuecomment-"))
        self.assertEqual({"user": "demo-user", "body": "First draft.\n"}, json.loads(before.stdout))
        self.assertEqual({"user": "demo-user", "body": "Corrected body.\n"}, json.loads(after.stdout))
        self.assertIn("Corrected body.", self.log.read_text(encoding="utf-8"))

    def test_edit_last는_마지막_댓글_본문을_바꾸고_같은_링크를_낸다(self) -> None:
        """--edit-last는 새 댓글을 만들지 않고 마지막 댓글의 본문만 바꾼다."""
        # given
        first = self.gh("issue", "comment", "98", "--repo", REPO, "--body-file", "-", stdin="One.\n").stdout

        # when
        again = self.gh("issue", "comment", "98", "--repo", REPO, "--edit-last", "--body-file", "-", stdin="Two.\n")
        view = self.gh("issue", "view", "98", "--repo", REPO, "--json", "comments", "--jq", ".comments")

        # then
        self.assertEqual(first, again.stdout)
        self.assertEqual(["Two.\n"], [comment["body"] for comment in json.loads(view.stdout)])

    def test_렌더링된_본문은_제목과_목록을_HTML로_바꾼다(self) -> None:
        """api 요청의 body_html은 ##과 - 목록을 태그로 바꾼 결과다."""
        # given
        self.create()

        # when
        html = self.rendered(200)

        # then
        self.assertIn("<h2>Summary</h2>", html)
        self.assertIn("<ul><li>Keep the gap.</li><li>Report it.</li></ul>", html)
        self.assertNotIn("##", html)

    def test_첫_렌더링을_깨뜨리면_원시_표기가_보이고_본문을_고치면_정상으로_렌더링된다(self) -> None:
        """FAKE_GH_BREAK_FIRST_RENDER=1로 만든 이슈는 편집 전까지 ##과 줄바꿈 표기를 그대로 보인다."""
        # given
        self.create(env={"FAKE_GH_BREAK_FIRST_RENDER": "1"})

        # when
        broken = self.rendered(200)
        self.gh("issue", "edit", "200", "--repo", REPO, "--body-file", "-", stdin=BODY)
        fixed = self.rendered(200)

        # then
        self.assertIn("## Summary\\n", broken)
        self.assertNotIn("<h2>", broken)
        self.assertIn("<h2>Summary</h2>", fixed)
        self.assertNotIn("##", fixed)

    def test_쓰기_명령은_본문과_함께_로그에_남고_다른_저장소_상태와_섞이지_않는다(self) -> None:
        """로그에는 명령과 본문이 남고, 다른 저장소의 번호 읽기는 영향을 받지 않는다."""
        # given
        self.create()

        # when
        other = self.gh("issue", "view", "200", "--repo", "demo-org/demo-g", "--json", "number")

        # then
        logged = self.log.read_text(encoding="utf-8")
        self.assertIn("gh issue create --repo demo-org/demo-a", logged)
        self.assertIn("The skill dropped a gap.", logged)
        self.assertNotEqual(0, other.returncode)


if __name__ == "__main__":
    unittest.main()
