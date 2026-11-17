"""Text reports."""

from __future__ import annotations

import sqlite3
from decimal import ROUND_HALF_UP, Decimal

from . import billing
from .dates import format_day
from .money import format_cents
from .service import OrderService

TAX_RATE = Decimal("0.0725")


def tax_cents(amount: int) -> int:
    return int((Decimal(amount) * TAX_RATE).to_integral_value(ROUND_HALF_UP))


def invoice_text(conn: sqlite3.Connection, order_id: str, bill: bool = False) -> str:
    service = OrderService(conn)
    order = service.get_order(order_id)
    lines = service.lines_of(order_id)
    subtotal = sum(price * quantity for _, price, quantity in lines)
    discounted = subtotal - order["discount_cents"]
    rows = [f"Order {order_id}  Date: {format_day(order['placed_at'])}"]
    if bill:
        rows.append(f"Bill to: {billing.bill_to(conn, order['customer_id'])}")
    rows += [f"{sku} x{quantity}: {format_cents(price * quantity)}" for sku, price, quantity in lines]
    rows += [f"Subtotal: {format_cents(subtotal)}", f"Discount: {format_cents(order['discount_cents'])}",
             f"Tax: {format_cents(tax_cents(discounted))}", f"Total: {format_cents(discounted + tax_cents(discounted))}"]
    return "\n".join(rows)
