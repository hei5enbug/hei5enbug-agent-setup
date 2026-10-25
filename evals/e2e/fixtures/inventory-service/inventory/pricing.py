"""Price calculation: bulk discounts per line and tax on the order subtotal."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from .money import quantize

BULK_TIERS: tuple[tuple[int, Decimal], ...] = (
    (100, Decimal("0.15")),
    (50, Decimal("0.10")),
    (10, Decimal("0.05")),
)


@dataclass(frozen=True)
class OrderTotals:
    subtotal: Decimal
    tax: Decimal
    total: Decimal


def bulk_discount_rate(quantity: int) -> Decimal:
    """Return the discount rate for buying `quantity` units of one item on one line."""
    for threshold, rate in BULK_TIERS:
        if quantity >= threshold:
            return rate
    return Decimal("0")


def line_total(unit_price: Decimal, quantity: int) -> Decimal:
    gross = unit_price * quantity
    return quantize(gross * (Decimal("1") - bulk_discount_rate(quantity)))


class PriceCalculator:
    def __init__(self, tax_rate: Decimal) -> None:
        self.tax_rate = tax_rate

    def totals(self, line_totals: Sequence[Decimal]) -> OrderTotals:
        subtotal = quantize(sum(line_totals, Decimal("0")))
        tax = quantize(subtotal * self.tax_rate)
        return OrderTotals(subtotal=subtotal, tax=tax, total=subtotal + tax)
