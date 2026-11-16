from pricing.api import format_amount, quote

LINES = [
    {"sku": "A-1", "quantity": 2, "unit_cents": 250},
    {"sku": "B-7", "quantity": 1, "unit_cents": 125},
]


def test_quote_totals_the_lines_as_a_decimal_string():
    assert quote(LINES) == {"currency": "USD", "total": "6.25"}


def test_quote_of_no_lines_is_zero():
    assert quote([]) == {"currency": "USD", "total": "0.00"}


def test_format_amount_pads_the_cents():
    assert format_amount(5) == "0.05"
