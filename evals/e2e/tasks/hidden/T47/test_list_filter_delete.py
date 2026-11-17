import io
from datetime import date

from timesheet import store
from timesheet.cli import main


def run(*argv):
    buffer = io.StringIO()
    code = main(list(argv), stdout=buffer)
    return code, buffer.getvalue()


def seed():
    store.add(date(2026, 11, 2), "alpha", 30)
    store.add(date(2026, 11, 3), "Alpha", 10)
    store.add(date(2026, 11, 3), "alpha", 15)


def test_project_filter_matches_the_exact_name_with_case():
    seed()
    assert run("list", "--project", "alpha") == (0, "1 2026-11-02 alpha 30\n3 2026-11-03 alpha 15\n")


def test_project_filter_combines_with_the_date_option():
    seed()
    assert run("list", "--project", "alpha", "--on", "2026-11-03") == (0, "3 2026-11-03 alpha 15\n")


def test_project_filter_with_no_match_prints_nothing_and_succeeds():
    seed()
    assert run("list", "--project", "gamma") == (0, "")


def test_delete_removes_the_entry_and_reports_it():
    seed()
    assert run("delete", "2") == (0, "deleted 2\n")
    assert [item["id"] for item in store.load()] == [1, 3]


def test_delete_of_an_unknown_id_is_an_error_on_stderr(capsys):
    seed()
    code = main(["delete", "9"])
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err.strip() == "no such entry: 9"
