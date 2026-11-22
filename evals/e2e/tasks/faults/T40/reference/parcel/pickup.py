"""Pickup fee for a courier visit that collects several parcels at once."""

from __future__ import annotations

from .errors import PickupLimitError, UnknownZone, ValidationError

PICKUP_FEE_PER_PARCEL_CENTS = {"A": 120, "B": 150, "C": 200}
PICKUP_LIMIT = 40


def pickup_fee_cents(parcel_count: int, zone: str) -> int:
    """Fee for collecting `parcel_count` parcels in one zone. One visit takes at most `PICKUP_LIMIT` parcels."""
    if zone not in PICKUP_FEE_PER_PARCEL_CENTS:
        raise UnknownZone(zone)
    if parcel_count < 1:
        raise ValidationError(f"parcel count must be at least 1: {parcel_count}")
    if parcel_count > PICKUP_LIMIT:
        raise PickupLimitError(f"pickup limit is {PICKUP_LIMIT} parcels, got {parcel_count}")
    return parcel_count * PICKUP_FEE_PER_PARCEL_CENTS[zone]
