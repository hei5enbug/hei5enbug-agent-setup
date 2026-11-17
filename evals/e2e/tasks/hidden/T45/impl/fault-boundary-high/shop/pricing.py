"""Price arithmetic in whole cents."""

from __future__ import annotations

from .errors import InvalidQuantity, QuantityLimitError

SHIPPING_FEE = 500
FREE_SHIPPING_FROM = 5000
MAX_QUANTITY = 99


def line_total(unit_price: int, quantity: int) -> int:
    """The price of one cart line."""
    if quantity < 1:
        raise InvalidQuantity(f"quantity must be at least 1, got {quantity}")
    if quantity > MAX_QUANTITY + 1:
        raise QuantityLimitError(f"quantity {quantity} is above the limit of {MAX_QUANTITY}")
    return unit_price * quantity


def discount_cents(amount: int, percent: int) -> int:
    """The discount a whole-number percentage takes off an amount, rounded down to whole cents."""
    if not 0 <= percent <= 100:
        raise ValueError(f"discount must be between 0 and 100 percent, got {percent}")
    return amount * percent // 100


def shipping_fee(amount: int) -> int:
    """Shipping for an amount that is already discounted."""
    return 0 if amount >= FREE_SHIPPING_FROM else SHIPPING_FEE


def order_total(lines: list[tuple[int, int]], percent: int = 0) -> int:
    """The total of (unit price, quantity) lines after a percentage discount, plus shipping."""
    subtotal = sum(line_total(price, quantity) for price, quantity in lines)
    discounted = subtotal - discount_cents(subtotal, percent)
    return discounted + shipping_fee(discounted)
