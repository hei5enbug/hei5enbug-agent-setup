import pytest

from parcel.errors import UnknownZone, ValidationError
from parcel.rates import base_fee_cents, billable_grams


def test_weight_is_billed_in_500_gram_steps():
    assert billable_grams(1) == 500
    assert billable_grams(500) == 500
    assert billable_grams(501) == 1000
    assert billable_grams(1200) == 1500
    assert billable_grams(30_000) == 30_000


def test_weight_outside_the_limits_is_rejected():
    with pytest.raises(ValidationError):
        billable_grams(0)
    with pytest.raises(ValidationError):
        billable_grams(30_001)


def test_base_fee_follows_the_billed_weight_and_the_zone_rate():
    assert base_fee_cents(1200, "A") == 900
    assert base_fee_cents(1200, "B") == 1350
    assert base_fee_cents(500, "C") == 600


def test_unknown_zone_is_rejected():
    with pytest.raises(UnknownZone):
        base_fee_cents(100, "Z")
