from pricing.api import quote

LINES = [
    {"sku": "A-1", "quantity": 2, "unit_cents": 250},
    {"sku": "B-7", "quantity": 1, "unit_cents": 125},
]


def test_quote_totals_the_lines_in_cents():
    assert quote(LINES) == {"currency": "USD", "total_cents": 625}


def test_quote_of_no_lines_is_zero():
    assert quote([]) == {"currency": "USD", "total_cents": 0}
