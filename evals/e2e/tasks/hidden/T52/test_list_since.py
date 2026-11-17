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
    store.add(date(2026, 11, 5), "beta", 10)
    store.add(date(2026, 11, 9), "alpha", 15)


def test_since_keeps_entries_on_or_after_the_date():
    seed()
    assert run("list", "--since", "2026-11-05") == (0, "2 2026-11-05 beta 10\n3 2026-11-09 alpha 15\n")


def test_since_combines_with_the_date_option():
    seed()
    assert run("list", "--since", "2026-11-05", "--on", "2026-11-09") == (0, "3 2026-11-09 alpha 15\n")


def test_since_reads_the_date_the_way_the_other_options_do(capsys):
    seed()
    assert main(["list", "--since", "11/05/2026"]) == 1
    assert "YYYY-MM-DD" in capsys.readouterr().err
