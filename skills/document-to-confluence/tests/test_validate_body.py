import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "validate_body.py"
SPEC = importlib.util.spec_from_file_location("validate_body", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def findings(markup, attachments=None):
    checker = MODULE.BodyChecker(attachments)
    checker.feed(markup)
    checker.close()
    return checker.findings


def rules(markup, attachments=None):
    return [finding["rule"] for finding in findings(markup, attachments)]


class LocalPathTest(unittest.TestCase):
    def test_tmp_path_in_text_is_reported(self):
        self.assertEqual(["local-path"], rules("<p>/tmp/private.txt</p>"))

    def test_var_tmp_path_is_reported(self):
        self.assertEqual(["local-path"], rules('<a href="/var/tmp/x.png">x</a>'))

    def test_https_url_containing_home_is_not_local(self):
        self.assertEqual([], rules('<a href="https://example.org/home/alice/file">public</a>'))

    def test_https_url_in_text_is_not_local(self):
        self.assertEqual([], rules("<p>See https://example.org/Users/alice/tmp/x</p>"))

    def test_http_url_is_not_local(self):
        self.assertEqual([], rules('<img width="1" height="1" src="http://cdn.example/home/img.png">'))

    def test_file_url_is_local(self):
        self.assertEqual(["local-path"], rules('<a href="file:///Volumes/data/x.png">x</a>'))

    def test_windows_drive_paths_are_local(self):
        self.assertEqual(["local-path"], rules("<p>C:\\Users\\alice\\x.png</p>"))
        self.assertEqual(["local-path"], rules("<p>D:/work/x.png</p>"))

    def test_home_directory_path_is_still_reported(self):
        self.assertEqual(["local-path"], rules("<p>/home/alice/x.png</p>"))
        self.assertEqual(["local-path"], rules("<p>/Users/alice/x.png</p>"))

    def test_time_like_text_is_not_a_drive_path(self):
        self.assertEqual([], rules("<p>회의 12:30/13:00</p>"))

    def test_relative_source_document_links_are_reported(self):
        for path in ("guide.md", "guide.markdown#part", "report.html", "scan.pdf", "spec.docx"):
            with self.subTest(path=path):
                self.assertEqual(["local-path"], rules(f'<a href="{path}">source</a>'))

    def test_remote_source_document_links_are_allowed(self):
        self.assertEqual([], rules('<a href="https://example.org/guide.pdf">guide</a>'))

    def test_uploaded_source_document_link_is_allowed(self):
        markup = '<a href="/wiki/download/attachments/1/guide.pdf">guide</a>'
        self.assertEqual([], rules(markup, {"guide.pdf"}))


class AttachmentNameTest(unittest.TestCase):
    def test_percent_encoded_name_matches_uploaded_name(self):
        markup = '<img width="1" height="1" src="/wiki/download/attachments/1/a%20b.png">'
        self.assertEqual([], rules(markup, {"a b.png"}))

    def test_unknown_attachment_is_still_reported(self):
        markup = '<img width="1" height="1" src="/wiki/download/attachments/1/other.png">'
        self.assertEqual(["missing-attachment"], rules(markup, {"a b.png"}))

    def test_plain_name_still_matches(self):
        markup = '<img width="1" height="1" src="/wiki/download/attachments/1/plain.png">'
        self.assertEqual([], rules(markup, {"plain.png"}))


class ExistingRulesTest(unittest.TestCase):
    def test_missing_dimension_and_bare_cell(self):
        markup = "<table><tr><td>bare</td></tr></table><img src=\"x.png\">"
        self.assertEqual(
            ["bare-table-cell", "img-missing-dimension", "img-missing-dimension"],
            rules(markup),
        )


if __name__ == "__main__":
    unittest.main()
