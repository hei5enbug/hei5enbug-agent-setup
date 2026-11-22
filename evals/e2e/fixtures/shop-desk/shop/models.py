"""Plain data types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrderLine:
    sku: str
    quantity: int
    unit_cents: int

    @property
    def total_cents(self) -> int:
        return self.quantity * self.unit_cents
