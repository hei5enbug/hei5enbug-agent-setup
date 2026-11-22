"""The one place where a fraction of a cent becomes whole cents."""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal


def round_cents(value: Decimal) -> int:
    """Return `value` as whole cents. The fraction is dropped."""
    return int(value.to_integral_value(rounding=ROUND_DOWN))
