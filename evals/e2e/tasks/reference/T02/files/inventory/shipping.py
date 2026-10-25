"""Shipping fee policy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .money import quantize

SHIPPING_METHODS = ("standard", "express")


@dataclass(frozen=True)
class ShippingPolicy:
    flat_fee: Decimal = Decimal("5.00")
    free_threshold: Decimal = Decimal("100.00")
    express_surcharge: Decimal = Decimal("12.00")

    def quote(self, subtotal: Decimal, method: str = "standard") -> Decimal:
        """Fee for an order with this subtotal. Express adds its surcharge even when standard shipping is free."""
        if method not in SHIPPING_METHODS:
            raise ValueError(f"unknown shipping method: {method!r}")
        fee = Decimal("0.00") if subtotal >= self.free_threshold else self.flat_fee
        if method == "express":
            fee += self.express_surcharge
        return quantize(fee)
