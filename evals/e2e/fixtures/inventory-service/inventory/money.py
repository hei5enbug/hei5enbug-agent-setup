"""Decimal helpers. Prices and totals always carry exactly two decimal places."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .errors import ValidationError

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def quantize(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def parse_money(text: str) -> Decimal:
    """Parse user input such as "12.5" into a non-negative two-place Decimal."""
    try:
        value = Decimal(text.strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValidationError(f"not a valid amount: {text!r}") from exc
    if not value.is_finite() or value < 0:
        raise ValidationError(f"amount must be a non-negative number: {text!r}")
    return quantize(value)


def format_money(value: Decimal) -> str:
    return f"{quantize(value):,.2f}"
