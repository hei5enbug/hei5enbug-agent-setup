import unittest

from demo_export import export_report
from demo_export.report import render_csv


class ExportReportTest(unittest.TestCase):
    def test_csv_has_header_and_rows(self):
        rows = [{"id": 1, "name": "a", "total": 5}]
        self.assertEqual(render_csv(rows), b"id,name,total\n1,a,5\n")

    def test_export_report_delegates_to_render_csv(self):
        rows = [{"id": 1, "name": "a", "total": 5}]
        self.assertEqual(export_report(rows), render_csv(rows))

    def test_unknown_format_is_rejected(self):
        with self.assertRaises(ValueError):
            export_report([], fmt="xml")
