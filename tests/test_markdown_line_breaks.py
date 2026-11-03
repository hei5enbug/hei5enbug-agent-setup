from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "markdown_line_breaks.py"
SPEC = importlib.util.spec_from_file_location("markdown_line_breaks", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def kinds(text, max_chars=120):
    return [(item["line"], item["kind"]) for item in MODULE.check(text, max_chars)]


class SoftBreakTest(unittest.TestCase):
    def test_br_없이_이어지는_문단의_줄은_soft_break_하나로_보고된다(self):
        # Given
        text = "first line\nsecond line\n"

        # When
        found = kinds(text)

        # Then
        self.assertEqual([(1, "soft-break")], found)

    def test_문단_마지막_줄의_br은_trailing_break_하나로_보고된다(self):
        # Given
        text = "first line<br>\nsecond line<br>\n"

        # When
        found = kinds(text)

        # Then
        self.assertEqual([(2, "trailing-break")], found)

    def test_diagram_펜스_안의_내용은_보고하지_않는다(self):
        # Given
        text = "```mermaid\nA --> B\nB --> C<br>\n```\n\n~~~\nx\ny<br>\n~~~\n"

        # When
        found = kinds(text)

        # Then
        self.assertEqual([], found)

    def test_올바른_줄바꿈과_연속된_목록_항목은_보고하지_않고_이어지는_목록_줄은_보고한다(self):
        # Given
        correct = "A.<br>\nB.\n"
        items = "- one\n- two\n"
        continued = "- item start\n  continues here\n"

        # When
        found = (kinds(correct), kinds(items), kinds(continued))

        # Then
        self.assertEqual(([], [], [(1, "soft-break")]), found)

    def test_표_제목_html_앞부분_빈_줄은_무시하고_빈_줄이_블록을_끝낸다(self):
        # Given
        text = "---\ntitle: x\nlong: y\n---\n# Heading\n| a | b |\n| - | - |\n<div>\nline\n\nnext\n"
        bare_table = "Name | Value\n--- | ---\nA | B\n\nnext\n"
        pipe_in_prose = "a | b\nc\n"

        # When
        found = (kinds(text), kinds(bare_table), kinds(pipe_in_prose))

        # Then
        self.assertEqual(([], [], [(1, "soft-break")]), found)


class LongLineTest(unittest.TestCase):
    LONG = "word " * 26

    def test_한도를_넘고_문장이_둘_이상인_줄만_long_line이고_0으로_끄면_보고하지_않는다(self):
        # Given
        two_sentences = "Done. Next " + self.LONG.strip() + "\n"
        one_sentence = self.LONG.strip() + ", e.g. " + self.LONG.strip() + ".\n"

        # When
        default = kinds(two_sentences)
        single = kinds(one_sentence)
        switched_off = kinds(two_sentences, 0)

        # Then
        self.assertEqual([(1, "long-line")], default)
        self.assertEqual([], single)
        self.assertEqual([], switched_off)

    def test_주소_때문에만_긴_줄은_보고하지_않는다(self):
        # Given
        url = "https://example.com/" + "a" * 150
        text = f"see [docs](https://example.com/{'b' * 150}) and {url} now\n"

        # When
        found = kinds(text)

        # Then
        self.assertEqual([], found)

    def test_끝의_br은_길이에_세지_않는다(self):
        # Given
        text = "x" * 118 + "<br>\ny\n"

        # When
        found = kinds(text)

        # Then
        self.assertEqual([], found)


class CommandLineTest(unittest.TestCase):
    def run_main(self, content, *extra):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "doc.md"
            if content is not None:
                path.write_text(content, encoding="utf-8")
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = MODULE.main([*extra, str(path)])
        return code, buffer.getvalue()

    def test_문제가_없으면_0으로_끝난다(self):
        # Given
        content = "A sentence.\n"

        # When
        code, output = self.run_main(content)

        # Then
        self.assertEqual(0, code)
        self.assertEqual([], json.loads(output)["findings"])

    def test_보고할_내용이_있으면_1로_끝나고_줄_번호와_종류와_줄을_출력한다(self):
        # Given
        content = "ok\n\nfirst\nsecond\n"

        # When
        code, output = self.run_main(content)

        # Then
        self.assertEqual(1, code)
        self.assertEqual([{"line": 3, "kind": "soft-break", "text": "first"}], json.loads(output)["findings"])

    def test_없는_파일은_2로_끝난다(self):
        # Given
        content = None

        # When
        code, _ = self.run_main(content)

        # Then
        self.assertEqual(2, code)


if __name__ == "__main__":
    unittest.main()
