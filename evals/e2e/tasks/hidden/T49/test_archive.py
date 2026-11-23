import io
from pathlib import Path

from tally.cli import main


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_archive_copies_the_entries_file_under_a_name_with_the_date_and_time(tmp_path, monkeypatch):
    monkeypatch.setenv("TALLY_NOW", "2026-11-16T09:05")
    target = tmp_path / "out" / "entries-20261116-0905.json"
    code, out, _ = run("archive", str(tmp_path / "out"))
    assert code == 0
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == Path("data/entries.json").read_text(encoding="utf-8")
    assert out.strip().endswith("entries-20261116-0905.json")


def test_two_archives_on_one_day_keep_both_copies(tmp_path, monkeypatch):
    monkeypatch.setenv("TALLY_NOW", "2026-11-16T09:05")
    run("archive", str(tmp_path))
    monkeypatch.setenv("TALLY_NOW", "2026-11-16T17:40")
    run("archive", str(tmp_path))
    assert sorted(path.name for path in tmp_path.iterdir()) == ["entries-20261116-0905.json", "entries-20261116-1740.json"]
