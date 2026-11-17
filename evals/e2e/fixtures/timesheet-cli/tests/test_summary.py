from timesheet.summary import project_totals


def test_minutes_are_summed_per_project_in_name_order():
    entries = [
        {"project": "beta", "minutes": 30},
        {"project": "alpha", "minutes": 20},
        {"project": "beta", "minutes": 15},
    ]
    assert project_totals(entries) == {"alpha": 20, "beta": 45}
