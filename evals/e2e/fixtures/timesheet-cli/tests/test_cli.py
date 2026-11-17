import io

from timesheet.cli import main


def run(*argv):
    buffer = io.StringIO()
    code = main(list(argv), stdout=buffer)
    return code, buffer.getvalue()


def test_add_then_list_shows_the_entry():
    assert run("add", "2026-11-02", "alpha", "30") == (0, "1 2026-11-02 alpha 30\n")
    assert run("list") == (0, "1 2026-11-02 alpha 30\n")


def test_list_on_a_date_keeps_only_that_day():
    run("add", "2026-11-02", "alpha", "30")
    run("add", "2026-11-03", "beta", "45")
    assert run("list", "--on", "2026-11-03") == (0, "2 2026-11-03 beta 45\n")


def test_totals_sum_each_project():
    run("add", "2026-11-02", "alpha", "30")
    run("add", "2026-11-03", "alpha", "15")
    assert run("totals") == (0, "alpha 45\n")


def test_a_malformed_date_is_an_error(capsys):
    assert main(["list", "--on", "11/03/2026"]) == 1
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_export_writes_a_csv_file_into_the_export_folder(home):
    run("add", "2026-11-02", "alpha", "30")
    code, text = run("export")
    assert code == 0
    written = list((home / "out").glob("export*.csv"))
    assert len(written) == 1
    assert "alpha" in written[0].read_text(encoding="utf-8")
    assert text.strip() == str(written[0])
