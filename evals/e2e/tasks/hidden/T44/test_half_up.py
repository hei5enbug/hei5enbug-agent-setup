import io

import pytest

from shop.cli import main
from shop.pricing import discount_cents, order_total


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    return main(list(argv), stdout=out, stderr=err), out.getvalue(), err.getvalue()


def test_part_of_a_cent_below_half_rounds_down():
    assert discount_cents(1984, 10) == 198
    assert discount_cents(4, 10) == 0


def test_part_of_a_cent_of_half_or_more_rounds_up():
    assert discount_cents(1999, 10) == 200
    assert discount_cents(1995, 10) == 200
    assert discount_cents(5, 10) == 1


def test_exactly_half_rounds_up_for_an_even_and_an_odd_result():
    assert discount_cents(1985, 10) == 199
    assert discount_cents(1975, 10) == 198


def test_a_whole_cent_discount_is_unchanged():
    assert discount_cents(1000, 15) == 150


def test_order_total_uses_the_rounded_discount():
    assert order_total([(1999, 2)], percent=10) == 3598 + 500


def test_quote_uses_the_rounded_discount():
    assert run("quote", "1999x2", "--discount", "10") == (0, "Total: $40.98\n", "")


def test_the_percent_range_is_still_enforced():
    with pytest.raises(ValueError):
        discount_cents(1000, 101)
