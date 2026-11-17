import io

import pytest

from shop.cart import Cart
from shop.cli import main
from shop.pricing import discount_cents, order_total


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    return main(list(argv), stdout=out, stderr=err), out.getvalue(), err.getvalue()


def test_fractional_percent_takes_its_exact_share():
    assert discount_cents(1000, 12.5) == 125


def test_a_fractional_discount_with_part_of_a_cent_rounds_down():
    assert discount_cents(999, 12.5) == 124
    assert discount_cents(1001, 0.5) == 5


def test_the_discount_is_a_whole_number_of_cents():
    assert isinstance(discount_cents(999, 12.5), int)


def test_order_total_and_cart_take_a_fractional_percent():
    assert order_total([(2000, 5)], percent=12.5) == 8750
    cart = Cart()
    cart.add("mug", 2000, 5)
    assert cart.total(percent=12.5) == 8750


def test_quote_takes_a_fractional_discount():
    assert run("quote", "1000x1", "--discount", "12.5") == (0, "Total: $13.75\n", "")


def test_the_percent_range_is_still_enforced_for_fractions():
    with pytest.raises(ValueError):
        discount_cents(1000, 100.5)
    with pytest.raises(ValueError):
        discount_cents(1000, -0.5)
