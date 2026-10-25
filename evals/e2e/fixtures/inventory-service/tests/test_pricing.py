from decimal import Decimal

import pytest

from inventory.pricing import PriceCalculator, bulk_discount_rate, line_total


@pytest.mark.parametrize(
    ("quantity", "rate"),
    [(1, "0"), (9, "0"), (10, "0.05"), (49, "0.05"), (50, "0.10"), (99, "0.10"), (100, "0.15"), (500, "0.15")],
)
def test_bulk_discount_tiers(quantity, rate):
    assert bulk_discount_rate(quantity) == Decimal(rate)


def test_line_total_applies_discount_and_rounds():
    assert line_total(Decimal("10.00"), 10) == Decimal("95.00")
    assert line_total(Decimal("0.40"), 3) == Decimal("1.20")
    assert line_total(Decimal("0.33"), 10) == Decimal("3.14")


def test_order_totals_add_tax_to_the_subtotal():
    totals = PriceCalculator(Decimal("0.08")).totals([Decimal("19.99"), Decimal("5.01")])
    assert (totals.subtotal, totals.tax, totals.total) == (Decimal("25.00"), Decimal("2.00"), Decimal("27.00"))


def test_empty_order_totals_are_zero():
    totals = PriceCalculator(Decimal("0.08")).totals([])
    assert totals.total == Decimal("0.00")
