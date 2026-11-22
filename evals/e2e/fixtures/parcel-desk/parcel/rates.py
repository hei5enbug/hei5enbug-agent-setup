"""Base fee: weight is billed in steps, and each zone has a rate per 500 g."""

from __future__ import annotations

from .errors import UnknownZone, ValidationError

WEIGHT_STEP_GRAMS = 500
MAX_WEIGHT_GRAMS = 30_000
RATE_PER_500_GRAMS_CENTS = {"A": 300, "B": 450, "C": 600}


def billable_grams(weight_grams: int) -> int:
    """Round the weight up to the next billing step."""
    if weight_grams < 1 or weight_grams > MAX_WEIGHT_GRAMS:
        raise ValidationError(f"weight must be between 1 and {MAX_WEIGHT_GRAMS} g: {weight_grams}")
    steps = -(-weight_grams // WEIGHT_STEP_GRAMS)
    return steps * WEIGHT_STEP_GRAMS


def base_fee_cents(weight_grams: int, zone: str) -> int:
    if zone not in RATE_PER_500_GRAMS_CENTS:
        raise UnknownZone(zone)
    return billable_grams(weight_grams) * RATE_PER_500_GRAMS_CENTS[zone] // 500
