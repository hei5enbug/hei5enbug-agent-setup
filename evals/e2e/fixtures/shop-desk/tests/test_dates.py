import re
from datetime import date

from shop.dates import week_label


def test_a_week_label_has_the_year_and_a_two_digit_week():
    assert re.fullmatch(r"\d{4}-W\d{2}", week_label(date(2026, 3, 4)))
