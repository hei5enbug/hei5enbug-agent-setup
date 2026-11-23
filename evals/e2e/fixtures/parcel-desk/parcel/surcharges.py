"""Surcharges on top of the base fee."""

from __future__ import annotations

from decimal import Decimal

from .errors import ValidationError
from .rounding import round_cents

FUEL_RATE = Decimal("0.08")
INSURANCE_RATE = Decimal("0.01")
MIN_INSURANCE_CENTS = 50


def fuel_surcharge_cents(base_cents: int) -> int:
    return round_cents(Decimal(base_cents) * FUEL_RATE)


def insurance_cents(declared_value_cents: int) -> int:
    """Insurance for a declared value: 1% with a minimum, and nothing when no value is declared."""
    if declared_value_cents < 0:
        raise ValidationError(f"declared value must not be negative: {declared_value_cents}")
    if declared_value_cents == 0:
        return 0
    return max(MIN_INSURANCE_CENTS, round_cents(Decimal(declared_value_cents) * INSURANCE_RATE))
