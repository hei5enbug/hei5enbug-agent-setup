import pytest

from parcel.errors import ValidationError
from parcel.surcharges import fuel_surcharge_cents, insurance_cents


def test_fuel_surcharge_is_eight_percent_of_the_base_fee():
    assert fuel_surcharge_cents(900) == 72
    assert fuel_surcharge_cents(1350) == 108


def test_insurance_is_one_percent_of_the_declared_value():
    assert insurance_cents(20_000) == 200


def test_insurance_has_a_minimum():
    assert insurance_cents(1_000) == 50


def test_nothing_declared_costs_nothing():
    assert insurance_cents(0) == 0


def test_negative_declared_value_is_rejected():
    with pytest.raises(ValidationError):
        insurance_cents(-1)
