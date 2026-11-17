import io
import re
import time

from timesheet import store
from timesheet.cli import main
from datetime import date


def run(*argv):
    buffer = io.StringIO()
    code = main(list(argv), stdout=buffer)
    return code, buffer.getvalue()


def rows(text):
    found = {}
    for line in text.splitlines():
        project, minutes = line.split()
        found[project] = int(minutes)
    return found


def seed():
    for day, project, minutes in [
        ("2026-11-07", "alpha", 5),
        ("2026-11-08", "alpha", 10),
        ("2026-11-09", "beta", 20),
        ("2026-11-14", "alpha", 40),
        ("2026-11-15", "beta", 80),
    ]:
        store.add(date.fromisoformat(day), project, minutes)


def test_weekly_sums_the_projects_of_the_week_that_starts_on_sunday():
    seed()
    code, text = run("weekly", "--on", "2026-11-11")
    assert code == 0
    assert rows(text) == {"alpha": 50, "beta": 20}


def test_weekly_puts_the_saturday_and_the_next_sunday_in_different_weeks():
    seed()
    assert rows(run("weekly", "--on", "2026-11-14")[1]) == {"alpha": 50, "beta": 20}
    assert rows(run("weekly", "--on", "2026-11-15")[1]) == {"beta": 80}
    assert rows(run("weekly", "--on", "2026-11-08")[1]) == {"alpha": 50, "beta": 20}


def test_weekly_rejects_a_malformed_date():
    assert run("weekly", "--on", "11/11/2026")[0] == 1


def test_two_exports_a_second_apart_keep_both_files_named_with_date_and_time(home):
    store.add(date(2026, 11, 2), "alpha", 30)
    run("export")
    time.sleep(1.1)
    run("export")
    names = sorted(path.name for path in (home / "out").glob("*.csv"))
    assert len(names) == 2
    assert "export.csv" not in names
    assert all(re.fullmatch(r"export-\d{8}-\d{6}\.csv", name) for name in names)
