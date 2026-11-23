import io
import json

from tally.cli import main


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_busiest_prints_the_team_with_the_most_hours_that_day():
    assert run("busiest", "2026-11-21") == (0, "alpha 4.0\n", "")


def test_a_tie_goes_to_the_team_whose_name_comes_first(tmp_path, monkeypatch):
    data = tmp_path / "entries.json"
    data.write_text(json.dumps({"entries": [
        {"team": "beta", "day": "2026-11-20", "hours": 3.0}, {"team": "alpha", "day": "2026-11-20", "hours": 3.0}]}), encoding="utf-8")
    monkeypatch.setenv("TALLY_DATA", str(data))
    assert run("busiest", "2026-11-20") == (0, "alpha 3.0\n", "")


def test_a_day_without_entries_prints_no_entries_and_exits_zero():
    assert run("busiest", "2026-12-01") == (0, "no entries\n", "")
