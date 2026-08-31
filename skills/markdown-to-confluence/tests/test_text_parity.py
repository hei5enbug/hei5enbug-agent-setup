from contextlib import redirect_stdout
import importlib.util
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "text_parity.py"
SPEC = importlib.util.spec_from_file_location("text_parity", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TextParityTest(unittest.TestCase):
    def assert_parity(self, source, body):
        self.assertEqual(
            MODULE.source_text(source, [], False),
            MODULE.body_text(body),
        )

    def test_inline_link_keeps_only_visible_label(self):
        self.assert_parity(
            "Read [OpenAI](https://openai.com).",
            '<p>Read <a href="https://openai.com">OpenAI</a>.</p>',
        )

    def test_supported_formatting_and_inline_code(self):
        self.assert_parity(
            "## Result\n\n- Keep **bold**, `a_b`, and \\*literal\\* text.",
            "<h2>Result</h2><ul><li>Keep <strong>bold</strong>, "
            "<code>a_b</code>, and *literal* text.</li></ul>",
        )

    def test_difference_reports_first_divergence(self):
        source = MODULE.source_text("Alpha beta", [], False)
        body = MODULE.body_text("<p>Alpha zeta</p>")

        difference = MODULE.first_difference(source, body, 4)

        self.assertEqual(5, difference["index"])

    def test_fenced_code_is_unsupported(self):
        with self.assertRaisesRegex(MODULE.UnsupportedInput, "fenced code"):
            MODULE.source_text("```python\nprint('x')\n```", [], False)

    def test_nested_link_destination_is_unsupported(self):
        with self.assertRaisesRegex(MODULE.UnsupportedInput, "nested parentheses"):
            MODULE.source_text("[label](https://example.com/a_(b))", [], False)

    def test_drop_removes_replaced_diagram_before_validation(self):
        source = "# Title\n\n```mermaid\ngraph TD\n```\n\nDone."
        normalized = MODULE.source_text(
            source,
            [r"```mermaid.*?```"],
            True,
        )

        self.assertEqual("Done.", normalized)

    def test_cli_reports_unsupported_source_as_input_error(self):
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.md"
            body = Path(directory) / "body.html"
            source.write_text("```python\nprint('x')\n```", encoding="utf-8")
            body.write_text("<pre><code>print('x')</code></pre>", encoding="utf-8")

            with redirect_stdout(output):
                status = MODULE.main([str(source), str(body)])

        self.assertEqual(2, status)
        self.assertFalse(json.loads(output.getvalue())["ok"])


if __name__ == "__main__":
    unittest.main()
