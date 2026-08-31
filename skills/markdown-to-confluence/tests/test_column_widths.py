from contextlib import redirect_stdout
import importlib.util
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "column_widths.py"
SPEC = importlib.util.spec_from_file_location("column_widths", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def options(**overrides):
    values = {
        "total": 1000,
        "char_width": 17.0,
        "padding": 46,
        "min_width": 110,
        "wide_char": 1.0,
        "narrow_char": 0.5,
        "floors": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ColumnWidthsTest(unittest.TestCase):
    def test_integer_widths_sum_to_requested_total(self):
        widths, _ = MODULE.column_widths([["A"], ["B"], ["C"]], options())

        self.assertEqual(1000, sum(widths))
        self.assertTrue(all(isinstance(width, int) for width in widths))

    def test_impossible_floor_total_fails(self):
        with self.assertRaisesRegex(MODULE.InputError, "floors total"):
            MODULE.column_widths(
                [["A"], ["B"]],
                options(floors={0: 900, 1: 900}),
            )

    def test_image_column_requires_explicit_floor(self):
        with self.assertRaisesRegex(MODULE.InputError, "explicit --floor"):
            MODULE.column_widths(
                [["![chart](chart.png)"], ["Notes"]],
                options(),
            )

    def test_image_floor_is_preserved(self):
        widths, details = MODULE.column_widths(
            [["![chart](chart.png)"], ["Notes"]],
            options(floors={0: 400}),
        )

        self.assertEqual(1000, sum(widths))
        self.assertGreaterEqual(widths[0], 400)
        self.assertEqual(400, details[0]["floor"])

    def test_cli_reports_impossible_floors_as_input_error(self):
        output = StringIO()
        arguments = [
            "--columns", "-", "--total", "1000",
            "--floor", "0=900", "--floor", "1=900",
        ]

        with patch("sys.stdin", StringIO('[["A"], ["B"]]')), redirect_stdout(output):
            status = MODULE.main(arguments)

        self.assertEqual(2, status)
        self.assertFalse(json.loads(output.getvalue())["ok"])


if __name__ == "__main__":
    unittest.main()
