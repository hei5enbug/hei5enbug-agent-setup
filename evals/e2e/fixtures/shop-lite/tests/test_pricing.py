import pytest

from shop.errors import InvalidQuantity
from shop.pricing import discount_cents, line_total, order_total, shipping_fee


def test_line_total_multiplies_price_by_quantity():
    assert line_total(250, 4) == 1000


def test_line_total_rejects_a_quantity_below_one():
    with pytest.raises(InvalidQuantity, match="at least 1"):
        line_total(250, 0)


def test_discount_rounds_down_to_whole_cents():
    assert discount_cents(1999, 10) == 199
    assert discount_cents(1000, 15) == 150


def test_discount_must_be_between_zero_and_one_hundred_percent():
    with pytest.raises(ValueError):
        discount_cents(1000, 101)
    with pytest.raises(ValueError):
        discount_cents(1000, -1)


def test_shipping_is_free_from_the_threshold():
    assert shipping_fee(4999) == 500
    assert shipping_fee(5000) == 0


def test_order_total_sums_lines_and_adds_shipping_below_the_threshold():
    assert order_total([(1000, 2), (500, 1)]) == 2500 + 500


def test_order_total_decides_shipping_after_the_discount():
    assert order_total([(6000, 1)]) == 6000
    assert order_total([(6000, 1)], percent=20) == 4800 + 500
