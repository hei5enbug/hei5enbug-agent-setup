from dockit.cli import main


def test_visit_and_visits_use_the_database(shared_db, capsys):
    assert main(["--db", str(shared_db), "visit", "guide"]) == 0
    assert main(["--db", str(shared_db), "visit", "guide"]) == 0
    assert main(["--db", str(shared_db), "visits"]) == 0
    assert capsys.readouterr().out.splitlines() == ["guide 1", "guide 2", "guide 2"]


def test_build_command_reports_the_files(tmp_path, capsys):
    assert main(["build", "--out", str(tmp_path / "site")]) == 0
    assert "Built 6 files" in capsys.readouterr().out
