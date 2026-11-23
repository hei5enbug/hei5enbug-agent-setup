from decimal import Decimal

from parcel.models import Parcel
from parcel.quote import build_quote
from parcel.rounding import round_cents
from parcel.surcharges import fuel_surcharge_cents, insurance_cents


def test_a_half_cent_rounds_up():
    assert round_cents(Decimal("10.5")) == 11
    assert round_cents(Decimal("0.5")) == 1


def test_below_half_rounds_down_and_above_half_rounds_up():
    assert round_cents(Decimal("10.49")) == 10
    assert round_cents(Decimal("10.51")) == 11
    assert round_cents(Decimal("10.9")) == 11
    assert round_cents(Decimal("0.49")) == 0


def test_whole_cents_are_unchanged():
    assert round_cents(Decimal("10")) == 10


def test_insurance_rounds_half_up():
    assert insurance_cents(20_050) == 201
    assert insurance_cents(20_049) == 200


def test_the_fuel_surcharge_rounds_half_up():
    assert fuel_surcharge_cents(1_007) == 81
    assert fuel_surcharge_cents(1_006) == 80


def test_a_quote_uses_the_new_rounding():
    quote = build_quote(Parcel(1200, "B", 20_050))
    assert (quote.fuel_cents, quote.insurance_cents, quote.total_cents) == (108, 201, 1659)
