import io
from datetime import date

import pytest

from shop.cli import main
from shop.dates import week_label


@pytest.mark.parametrize("day, label", [
    (date(2026, 1, 1), "2026-W00"),
    (date(2026, 1, 3), "2026-W00"),
    (date(2026, 1, 4), "2026-W01"),
    (date(2026, 2, 28), "2026-W08"),
    (date(2026, 3, 1), "2026-W09"),
    (date(2026, 12, 31), "2026-W52"),
    (date(2023, 1, 1), "2023-W01"),
])
def test_a_week_starts_on_sunday_and_days_before_the_first_sunday_are_week_zero(day, label):
    assert week_label(day) == label


def test_the_week_command_prints_the_label():
    out = io.StringIO()
    assert main(["week", "2026-03-01"], stdout=out, stderr=io.StringIO()) == 0
    assert out.getvalue() == "2026-W09\n"
