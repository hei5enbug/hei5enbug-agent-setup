import pytest

from parcel.errors import UnknownZone, ValidationError
from parcel.pickup import pickup_fee_cents


def test_pickup_fee_is_per_parcel():
    assert pickup_fee_cents(3, "A") == 360
    assert pickup_fee_cents(1, "C") == 200


def test_pickup_needs_at_least_one_parcel():
    with pytest.raises(ValidationError):
        pickup_fee_cents(0, "A")


def test_pickup_in_an_unknown_zone_is_rejected():
    with pytest.raises(UnknownZone):
        pickup_fee_cents(1, "Z")
