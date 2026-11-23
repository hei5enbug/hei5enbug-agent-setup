from tally.report import format_row, team_hours


def test_team_hours_sums_per_team_and_sorts_by_name():
    entries = [{"team": "b", "hours": 1.0}, {"team": "a", "hours": 2.0}, {"team": "b", "hours": 0.5}]
    assert team_hours(entries) == {"a": 2.0, "b": 1.5}


def test_format_row_prints_one_decimal():
    assert format_row("a", 2) == "a 2.0"
