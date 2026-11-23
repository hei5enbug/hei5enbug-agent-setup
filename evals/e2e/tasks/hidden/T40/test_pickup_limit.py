import pytest

from parcel.errors import ParcelError, PickupLimitError
from parcel.pickup import pickup_fee_cents


def test_the_limit_itself_is_allowed():
    assert pickup_fee_cents(40, "A") == 4800


def test_one_above_the_limit_is_rejected_with_the_count_in_the_message():
    with pytest.raises(PickupLimitError) as excinfo:
        pickup_fee_cents(41, "A")
    assert str(excinfo.value) == "pickup limit is 40 parcels, got 41"


def test_far_above_the_limit_is_rejected():
    with pytest.raises(PickupLimitError) as excinfo:
        pickup_fee_cents(1000, "C")
    assert str(excinfo.value) == "pickup limit is 40 parcels, got 1000"


def test_the_limit_error_is_a_parcel_error():
    assert issubclass(PickupLimitError, ParcelError)


def test_fees_below_the_limit_are_unchanged():
    assert pickup_fee_cents(39, "B") == 5850
    assert pickup_fee_cents(1, "C") == 200
