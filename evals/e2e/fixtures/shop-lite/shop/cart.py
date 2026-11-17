"""A cart that collects lines and prices them."""

from __future__ import annotations

from .pricing import order_total


class Cart:
    def __init__(self) -> None:
        self._lines: dict[str, tuple[int, int]] = {}

    def add(self, sku: str, unit_price: int, quantity: int = 1) -> None:
        """Add units of a sku; adding a sku again adds to its quantity."""
        _, current = self._lines.get(sku, (unit_price, 0))
        self._lines[sku] = (unit_price, current + quantity)

    def lines(self) -> list[tuple[str, int, int]]:
        """The (sku, unit price, quantity) lines in the order their sku was first added."""
        return [(sku, price, quantity) for sku, (price, quantity) in self._lines.items()]

    def total(self, percent: int = 0) -> int:
        return order_total([(price, quantity) for _, price, quantity in self.lines()], percent)
