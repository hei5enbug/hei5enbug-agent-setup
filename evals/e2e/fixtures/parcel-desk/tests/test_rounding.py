from decimal import Decimal

from parcel.rounding import round_cents


def test_whole_cents_are_unchanged():
    assert round_cents(Decimal("10")) == 10


def test_a_small_fraction_is_dropped():
    assert round_cents(Decimal("10.2")) == 10


def test_a_large_fraction_is_dropped_too():
    assert round_cents(Decimal("10.7")) == 10


def test_zero_stays_zero():
    assert round_cents(Decimal("0")) == 0
