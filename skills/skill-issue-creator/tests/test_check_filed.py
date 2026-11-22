#!/usr/bin/env python3
"""check_filed.py가 기록된 gh 응답과 표준 입력 본문에서 제목, 태그, 절 순서, 날 마크업을 판정하는지 검사한다."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
SCRIPT = SKILL / "scripts" / "check_filed.py"
REPO = "demo-org/demo-plugin"
TITLE = "demo-skill: report the gap"
GOOD_SECTIONS = ("Summary", "Observations", "Gap in current rules", "Proposal", "Acceptance criteria", "Evidence")
FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
record = json.loads(open(os.environ["RECORDED_GH"], encoding="utf-8").read())
kind = "api" if sys.argv[1] == "api" else "view"
entry = record[kind]
if entry.get("exit"):
    sys.exit(entry["exit"])
sys.stdout.write(entry["stdout"])
"""


def markdown(headings: tuple[str, ...] = GOOD_SECTIONS, extra: str = "") -> str:
    return "\n\n".join(f"## {name}\n\n- text of {name}" for name in headings) + extra + "\n"


def html(headings: tuple[str, ...] = GOOD_SECTIONS, extra: str = "") -> str:
    return "\n".join(f"<h2>{name}</h2>\n<p>text of {name}</p>" for name in headings) + extra


def jira(headings: tuple[str, ...] = GOOD_SECTIONS) -> str:
    return "\n\n".join(f"h2. {name}\n\ntext of {name}" for name in headings) + "\n"


def plain(headings: tuple[str, ...] = GOOD_SECTIONS) -> str:
    return "\n\n".join(f"{name}\n\ntext of {name}" for name in headings) + "\n"


class CheckFiledCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        gh = self.base / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8")
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        self.record = self.base / "recorded.json"
        self.env = {**os.environ, "PATH": f"{self.base}{os.pathsep}{os.environ['PATH']}",
                    "RECORDED_GH": str(self.record)}

    def record_issue(self, body: str, rendered: str, labels: tuple[str, ...] = ("enhancement",),
                     title: str = TITLE) -> None:
        issue = {"number": 7, "title": title, "labels": [{"name": name} for name in labels], "body": body,
                 "url": f"https://github.com/{REPO}/issues/7"}
        self.record.write_text(json.dumps({"view": {"stdout": json.dumps(issue)}, "api": {"stdout": rendered}}),
                               encoding="utf-8")

    def record_failure(self) -> None:
        self.record.write_text(json.dumps({"view": {"exit": 1}, "api": {"exit": 1}}), encoding="utf-8")

    def run_github(self, *labels: str, title: str = TITLE) -> tuple[int, dict]:
        arguments = ["github", "--repo", REPO, "--number", "7", "--title", title]
        for label in labels:
            arguments += ["--label", label]
        return self.run_script(arguments)

    def run_script(self, arguments: list[str], stdin: str = "") -> tuple[int, dict]:
        completed = subprocess.run([sys.executable, str(SCRIPT), *arguments], input=stdin, text=True,
                                   capture_output=True, env=self.env, check=False)
        output = json.loads(completed.stdout) if completed.stdout.strip() else {}
        return completed.returncode, output

    @staticmethod
    def statuses(outcome: dict) -> dict[str, str]:
        return {item["id"]: item["status"] for item in outcome["checks"]}

    @staticmethod
    def kinds(outcome: dict) -> set[str]:
        return {item["kind"] for item in outcome["findings"]}


class GitHubModeTests(CheckFiledCase):
    def test_렌더된_본문에_별표_굵게_표시가_남으면_날_마크업을_보고하고_순서는_통과시키며_1로_끝난다(self) -> None:
        """AC1: demo-org/demo-plugin#7의 렌더 결과에 **bold**가 그대로 보이면 raw_markup만 실패한다."""
        # given
        self.record_issue(markdown(), html(extra="\n<p>**bold** text</p>"))

        # when
        code, outcome = self.run_github("enhancement")

        # then
        self.assertEqual(1, code)
        self.assertEqual({"title": "pass", "tags": "pass", "section_order": "pass", "raw_markup": "fail"},
                         self.statuses(outcome))
        self.assertEqual({"bold_marker"}, self.kinds(outcome))

    def test_라벨이_없고_근거가_수용_기준보다_앞서면_태그와_순서_실패를_함께_보고하고_1로_끝난다(self) -> None:
        """AC2: enhancement 라벨이 없고 Evidence가 Acceptance criteria 앞이면 두 검사가 모두 실패한다."""
        # given
        swapped = ("Summary", "Observations", "Gap in current rules", "Proposal", "Evidence", "Acceptance criteria")
        self.record_issue(markdown(swapped), html(swapped), labels=("bug",))

        # when
        code, outcome = self.run_github("enhancement")

        # then
        self.assertEqual(1, code)
        statuses = self.statuses(outcome)
        self.assertEqual(("fail", "fail", "pass"), (statuses["tags"], statuses["section_order"], statuses["raw_markup"]))

    def test_gh가_실패하면_검사를_통과로_세지_않고_검증_불가로_보고하며_3으로_끝난다(self) -> None:
        """AC2: gh 호출이 실패하면 모든 검사가 unverified이고 종료 코드는 3이다."""
        # given
        self.record_failure()

        # when
        code, outcome = self.run_github("enhancement")

        # then
        self.assertEqual(3, code)
        self.assertEqual("unverified", outcome["status"])
        self.assertEqual({"unverified"}, set(self.statuses(outcome).values()))

    def test_세_번째_제목이_새_스킬_제안용일_때도_순서_검사를_통과한다(self) -> None:
        """AC2: 세 번째 제목이 Why no existing skill covers it이어도 순서 검사는 통과한다."""
        # given
        headings = ("Summary", "Observations", "Why no existing skill covers it", "Proposal", "Acceptance criteria",
                    "Evidence")
        self.record_issue(markdown(headings), html(headings))

        # when
        code, outcome = self.run_github("enhancement")

        # then
        self.assertEqual(0, code)
        self.assertEqual("pass", outcome["status"])

    def test_제목이_다르면_제목_검사만_실패한다(self) -> None:
        """제목 불일치는 다른 검사를 통과로 두면서 제목만 실패시킨다."""
        # given
        self.record_issue(markdown(), html(), title="another title")

        # when
        code, outcome = self.run_github("enhancement")

        # then
        self.assertEqual(1, code)
        self.assertEqual({"title": "fail", "tags": "pass", "section_order": "pass", "raw_markup": "pass"},
                         self.statuses(outcome))

    def test_렌더된_본문만_읽지_못하면_날_마크업만_검증_불가이고_나머지가_통과면_3으로_끝난다(self) -> None:
        """이슈는 읽혔지만 렌더 본문 호출이 실패하면 통과가 아니라 3이다."""
        # given
        self.record_issue(markdown(), html())
        record = json.loads(self.record.read_text(encoding="utf-8"))
        self.record.write_text(json.dumps({**record, "api": {"exit": 1}}), encoding="utf-8")

        # when
        code, outcome = self.run_github("enhancement")

        # then
        self.assertEqual(3, code)
        self.assertEqual("unverified", self.statuses(outcome)["raw_markup"])
        self.assertEqual("pass", self.statuses(outcome)["section_order"])

    def test_코드_안의_표시는_날_마크업으로_세지_않는다(self) -> None:
        """코드 블록 안의 ## 와 **는 렌더 결과의 날 마크업이 아니다."""
        # given
        self.record_issue(markdown(), html(extra="\n<pre><code>## heading and **bold**</code></pre>"))

        # when
        code, outcome = self.run_github("enhancement")

        # then
        self.assertEqual(0, code)
        self.assertEqual("pass", self.statuses(outcome)["raw_markup"])

    def test_렌더_본문에_이스케이프된_줄바꿈이_보이면_날_마크업으로_보고한다(self) -> None:
        """본문에 \\n 문자가 그대로 보이면 escaped_line_break를 보고한다."""
        # given
        self.record_issue(markdown(), html(extra="\n<p>first\\nsecond</p>"))

        # when
        code, outcome = self.run_github("enhancement")

        # then
        self.assertEqual(1, code)
        self.assertEqual({"escaped_line_break"}, self.kinds(outcome))


class BodyModeTests(CheckFiledCase):
    def body(self, fmt: str, text: str) -> tuple[int, dict]:
        return self.run_script(["body", "--format", fmt], stdin=text)

    def test_html_본문에_이스케이프된_엔티티가_있으면_보고하고_1로_끝난다(self) -> None:
        """AC3: html 본문의 &lt;h2&gt;는 escaped_entity로 보고된다."""
        # given
        text = html(extra="\n<p>&lt;h2&gt; Summary</p>")

        # when
        code, outcome = self.body("html", text)

        # then
        self.assertEqual(1, code)
        self.assertIn("escaped_entity", self.kinds(outcome))
        self.assertEqual("pass", self.statuses(outcome)["section_order"])

    def test_지라_위키_본문은_순서를_통과하고_날_마크업은_검증_불가로_보고하며_3으로_끝난다(self) -> None:
        """AC3: h2. 제목이 순서대로면 순서 검사는 통과하고 날 마크업은 unverified다."""
        # given
        text = jira()

        # when
        code, outcome = self.body("jira", text)

        # then
        self.assertEqual(3, code)
        self.assertEqual({"section_order": "pass", "raw_markup": "unverified"}, self.statuses(outcome))

    def test_일반_텍스트_본문도_제목_줄_순서만_검사하고_날_마크업은_검증_불가로_둔다(self) -> None:
        """plain은 제목 줄과 빈 줄로 순서를 읽고 날 마크업은 unverified다."""
        # given
        text = plain()

        # when
        code, outcome = self.body("plain", text)

        # then
        self.assertEqual(3, code)
        self.assertEqual({"section_order": "pass", "raw_markup": "unverified"}, self.statuses(outcome))

    def test_마크다운_본문의_제목이_뒤바뀌면_순서_실패로_1로_끝난다(self) -> None:
        """markdown 본문에서 Proposal이 Observations보다 앞이면 순서 검사가 실패한다."""
        # given
        swapped = ("Summary", "Proposal", "Observations", "Gap in current rules", "Acceptance criteria", "Evidence")

        # when
        code, outcome = self.body("markdown", markdown(swapped))

        # then
        self.assertEqual(1, code)
        self.assertEqual("fail", self.statuses(outcome)["section_order"])

    def test_마크다운_본문의_코드_울타리_안_제목은_절로_세지_않는다(self) -> None:
        """울타리 안의 ## Evidence 줄은 제목이 아니므로 Evidence가 없는 본문은 실패한다."""
        # given
        text = markdown(GOOD_SECTIONS[:-1]) + "\n```\n## Evidence\n```\n"

        # when
        code, outcome = self.body("markdown", text)

        # then
        self.assertEqual(1, code)
        self.assertIn("Evidence", outcome["checks"][0]["detail"])

    def test_깨끗한_마크다운_본문은_0으로_끝난다(self) -> None:
        """여섯 제목이 순서대로이고 날 마크업이 없으면 pass와 0이다."""
        # given
        text = markdown()

        # when
        code, outcome = self.body("markdown", text)

        # then
        self.assertEqual((0, "pass"), (code, outcome["status"]))


class UsageTests(CheckFiledCase):
    def test_서식_이름이_틀리면_사용법_오류로_2로_끝난다(self) -> None:
        """body의 --format에 모르는 값을 주면 종료 코드 2다."""
        # given
        arguments = ["body", "--format", "wiki"]

        # when
        code, _ = self.run_script(arguments, stdin=markdown())

        # then
        self.assertEqual(2, code)

    def test_번호가_숫자가_아니면_사용법_오류로_2로_끝난다(self) -> None:
        """github의 --number가 숫자가 아니면 종료 코드 2다."""
        # given
        arguments = ["github", "--repo", REPO, "--number", "seven", "--title", TITLE]

        # when
        code, _ = self.run_script(arguments)

        # then
        self.assertEqual(2, code)


class PackagingDetectorTests(CheckFiledCase):
    def test_스킬_폴더만_받으면_위반을_찾지_못해_0으로_끝나고_패키징_검사를_막지_않는다(self) -> None:
        """package_skill은 scripts/check_*.py에 스킬 폴더 하나만 넘겨 실행하므로 이 경우 pass와 0이다."""
        # given
        folder = str(SKILL)

        # when
        code, outcome = self.run_script([folder])

        # then
        self.assertEqual((0, "pass", []), (code, outcome["status"], outcome["checks"]))


if __name__ == "__main__":
    unittest.main()
