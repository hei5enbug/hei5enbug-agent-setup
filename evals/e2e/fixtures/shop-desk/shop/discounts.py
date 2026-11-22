"""Tier discounts."""

from __future__ import annotations

TIER_PERCENT = {"basic": 0, "silver": 5, "gold": 10}


def tier_discount_cents(tier: str, subtotal_cents: int) -> int:
    return subtotal_cents * TIER_PERCENT.get(tier, 0) // 100
