"""The parcel to ship and the quote for it."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Parcel:
    weight_grams: int
    zone: str
    declared_value_cents: int = 0


@dataclass(frozen=True)
class Quote:
    billed_grams: int
    base_cents: int
    fuel_cents: int
    insurance_cents: int

    @property
    def total_cents(self) -> int:
        return self.base_cents + self.fuel_cents + self.insurance_cents
