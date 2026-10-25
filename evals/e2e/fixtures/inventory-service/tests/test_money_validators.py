from decimal import Decimal

import pytest

from inventory.errors import ValidationError
from inventory.money import format_money, parse_money, quantize
from inventory.validators import validate_name, validate_quantity, validate_sku, validate_warehouse_code


def test_parse_money_rounds_to_cents():
    assert parse_money("12.345") == Decimal("12.35")
    assert parse_money(" 7 ") == Decimal("7.00")


@pytest.mark.parametrize("text", ["abc", "-1", "NaN", "Infinity", ""])
def test_parse_money_rejects_bad_input(text):
    with pytest.raises(ValidationError):
        parse_money(text)


def test_format_money_groups_thousands():
    assert format_money(Decimal("1234567.5")) == "1,234,567.50"


def test_quantize_rounds_half_up():
    assert quantize(Decimal("0.005")) == Decimal("0.01")


def test_sku_is_normalised_and_checked():
    assert validate_sku(" ab-12 ") == "AB-12"
    with pytest.raises(ValidationError):
        validate_sku("a b")


def test_warehouse_code_must_start_with_a_letter():
    assert validate_warehouse_code("east") == "EAST"
    with pytest.raises(ValidationError):
        validate_warehouse_code("1ST")


def test_quantity_bounds():
    assert validate_quantity(3) == 3
    assert validate_quantity(0, allow_zero=True) == 0
    for bad in (0, -2, 2_000_000, True, 1.5):
        with pytest.raises(ValidationError):
            validate_quantity(bad)


def test_name_is_collapsed_and_limited():
    assert validate_name("  Big   Widget ") == "Big Widget"
    with pytest.raises(ValidationError):
        validate_name("x" * 81)
