#!/usr/bin/env python3
"""check_format.py가 설계 문서의 정확한 형식 규칙만 위반으로 보고하고 판단 항목은 후보로만 두는지 검사한다."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
SCRIPT = SKILL / "scripts" / "check_format.py"
LONG = "x" * 130
URL_LINE = f"See https://example.com/very/long/path {'y' * 100}"


def document(total: int, extra_first: str = "") -> str:
    """A clean Markdown document of exactly `total` lines: a title, a blank line, then paragraphs."""
    lines = ["# 제목", ""]
    while len(lines) < total:
        lines.append(f"문장 {len(lines)}." if len(lines) % 2 == 0 else "")
    lines[-1] = lines[-1] or "마지막 문장."
    if extra_first:
        lines[2] = extra_first
    return "\n".join(lines) + "\n"


class CheckFormatCase(unittest.TestCase):
    def check(self, text: str, *arguments: str) -> tuple[int, dict]:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "design.md"
            path.write_text(text, encoding="utf-8")
            completed = subprocess.run([sys.executable, str(SCRIPT), str(path), *arguments], capture_output=True,
                                       text=True, timeout=30, check=False)
        return completed.returncode, json.loads(completed.stdout) if completed.stdout else {}

    def rules(self, outcome: dict) -> list[tuple[str, int]]:
        return [(item["rule"], item["line"]) for item in outcome["violations"]]


class ExactRuleTests(CheckFormatCase):
    def test_표_행과_URL_줄은_제외하고_긴_산문_줄과_네_번째_제목_수준만_위반으로_보고한다(self) -> None:
        """130자 산문, 130자 표 행, URL이 든 130자 줄, #### 제목이 있으면 산문 줄과 제목 수준만 보고하고 1로 끝난다."""
        # given
        text = f"# 제목\n\n{LONG}\n\n| a | b |\n|---|---|\n| {LONG} | x |\n\n{URL_LINE}\n\n#### 깊은 제목\n"

        # when
        code, outcome = self.check(text)

        # then
        self.assertEqual((1, [("long_line", 3), ("heading_level", 11)]), (code, self.rules(outcome)))

    def test_문장_뒤_공백과_표_앞_빈_줄_누락을_함께_보고하고_깨끗한_파일은_0으로_끝난다(self) -> None:
        """줄 끝 공백과 표 앞 빈 줄 누락은 둘 다 보고하고 1, 40줄의 깨끗한 파일은 0이다."""
        # given
        broken = "# 제목\n\n문장 하나. \n| a | b |\n|---|---|\n| 1 | 2 |\n"
        clean = document(40)

        # when
        broken_code, broken_outcome = self.check(broken)
        clean_code, clean_outcome = self.check(clean)

        # then
        self.assertEqual((1, [("blank_line", 4), ("trailing_space", 3)]),
                         (broken_code, sorted(self.rules(broken_outcome), key=lambda item: item[0])))
        self.assertEqual((0, 40, []), (clean_code, clean_outcome["lines"], clean_outcome["violations"]))

    def test_서른_자를_넘는_한국어_제목은_후보로만_나열하고_0으로_끝난다(self) -> None:
        """34자 한국어 제목은 candidates에만 오르고 위반이 없어 종료 코드가 0이다."""
        # given
        heading = "가" * 34
        text = f"# {heading}\n\n본문 한 줄.\n"

        # when
        code, outcome = self.check(text)

        # then
        self.assertEqual((0, [], [("long_korean_heading", 1)]),
                         (code, outcome["violations"], [(item["rule"], item["line"]) for item in outcome["candidates"]]))

    def test_서른_자를_넘는_영어_제목은_후보로도_세지_않는다(self) -> None:
        """한글이 없는 긴 제목은 판단 대상이 아니므로 후보가 비어 있다."""
        # given
        text = f"# {'a' * 40}\n\nbody.\n"

        # when
        code, outcome = self.check(text)

        # then
        self.assertEqual((0, []), (code, outcome["candidates"]))

    def test_520줄_파일은_옵션_없이는_줄_수를_보고하고_1_템플릿_옵션이면_0으로_끝난다(self) -> None:
        """깨끗한 520줄 파일은 --template 없이 line_count 위반이고 --template이면 위반이 없다."""
        # given
        text = document(520)

        # when
        plain_code, plain = self.check(text)
        template_code, template = self.check(text, "--template")

        # then
        self.assertEqual((520, 1, [("line_count", 520)]), (plain["lines"], plain_code, self.rules(plain)))
        self.assertEqual((0, []), (template_code, template["violations"]))

    def test_정확히_120자_산문_줄과_정확히_500줄_파일은_위반이_아니다(self) -> None:
        """경계값 120자와 500줄은 허용한다."""
        # given
        text = document(500, extra_first="z" * 120)

        # when
        code, outcome = self.check(text)

        # then
        self.assertEqual((500, 0, []), (outcome["lines"], code, outcome["violations"]))


class BlockStructureTests(CheckFormatCase):
    def test_코드_울타리_안의_긴_줄_후행_공백_제목_표시는_검사하지_않는다(self) -> None:
        """울타리 안의 130자 줄, 줄 끝 공백, #### 줄은 위반이 아니다."""
        # given
        text = f"# 제목\n\n```text\n{LONG}   \n#### 코드 속 제목\n```\n"

        # when
        code, outcome = self.check(text)

        # then
        self.assertEqual((0, []), (code, outcome["violations"]))

    def test_인라인_코드가_든_긴_줄은_산문_줄_검사에서_제외한다(self) -> None:
        """백틱 구간이 있는 130자 줄은 보고하지 않는다."""
        # given
        text = f"# 제목\n\n`code` {LONG}\n"

        # when
        code, outcome = self.check(text)

        # then
        self.assertEqual((0, []), (code, outcome["violations"]))

    def test_제목과_코드_블록과_목록_앞뒤_빈_줄_누락을_각각_보고한다(self) -> None:
        """제목 뒤, 코드 블록 앞뒤, 문단 바로 뒤 목록 앞의 빈 줄 누락을 줄 번호와 함께 보고한다."""
        # given
        text = "# 제목\n문장.\n\n문장 둘.\n```text\nx\n```\n문장 셋.\n\n소개:\n- 항목\n"

        # when
        code, outcome = self.check(text)

        # then
        self.assertEqual((1, [("blank_line", 1), ("blank_line", 5), ("blank_line", 7), ("blank_line", 11)]),
                         (code, self.rules(outcome)))

    def test_목록_항목_바로_뒤의_들여쓰지_않은_줄은_항목의_이어쓰기로_보고하지_않는다(self) -> None:
        """목록 뒤 빈 줄 없는 평문 줄은 CommonMark에서 같은 항목이므로 위반이 아니다."""
        # given
        text = "# 제목\n\n- 항목\n이어지는 줄\n\n문단.\n"

        # when
        code, outcome = self.check(text)

        # then
        self.assertEqual((0, []), (code, outcome["violations"]))

    def test_목록_바로_뒤에_표나_제목이_오면_그_블록_앞의_빈_줄_누락으로_보고한다(self) -> None:
        """목록 직후의 제목은 블록 앞 빈 줄 누락으로 보고한다."""
        # given
        text = "# 제목\n\n- 항목\n## 다음\n\n문단.\n"

        # when
        code, outcome = self.check(text)

        # then
        self.assertEqual((1, [("blank_line", 4)]), (code, self.rules(outcome)))

    def test_같은_목록의_중첩_항목과_들여쓴_이어쓰기는_새_목록으로_보지_않는다(self) -> None:
        """중첩 항목과 들여쓴 줄 사이에 빈 줄이 없어도 위반이 아니다."""
        # given
        text = "# 제목\n\n- 항목\n  - 하위 항목\n  이어쓰기\n- 다음 항목\n"

        # when
        code, outcome = self.check(text)

        # then
        self.assertEqual((0, []), (code, outcome["violations"]))

    def test_들여쓰기_코드_블록과_머리말은_검사하지_않는다(self) -> None:
        """빈 줄 뒤 네 칸 들여쓴 130자 줄과 맨 앞 머리말의 줄 끝 공백은 보고하지 않는다."""
        # given
        text = f"---\ntitle: x   \n---\n\n# 제목\n\n    {LONG}\n"

        # when
        code, outcome = self.check(text)

        # then
        self.assertEqual((0, []), (code, outcome["violations"]))


class UsageTests(CheckFormatCase):
    def test_파일이_없으면_사용법_오류로_2로_끝난다(self) -> None:
        """존재하지 않는 경로는 읽지 못해 종료 코드 2다."""
        # given
        missing = str(SKILL / "no-such-file.md")

        # when
        completed = subprocess.run([sys.executable, str(SCRIPT), missing], capture_output=True, text=True, timeout=30,
                                   check=False)

        # then
        self.assertEqual(2, completed.returncode)

    def test_인자가_없으면_사용법_오류로_2로_끝난다(self) -> None:
        """경로를 주지 않으면 종료 코드 2다."""
        # given
        # when
        completed = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=30,
                                   check=False)

        # then
        self.assertEqual(2, completed.returncode)

    def test_스킬_폴더만_받으면_위반을_찾지_못해_0으로_끝나고_패키징_검사를_막지_않는다(self) -> None:
        """package_skill은 scripts/check_*.py에 스킬 폴더 하나만 넘겨 실행하므로 이 경우 pass와 0이다."""
        # given
        folder = str(SKILL)

        # when
        completed = subprocess.run([sys.executable, str(SCRIPT), folder], capture_output=True, text=True, timeout=30,
                                   check=False)

        # then
        self.assertEqual((0, "pass"), (completed.returncode, json.loads(completed.stdout)["status"]))


if __name__ == "__main__":
    unittest.main()
