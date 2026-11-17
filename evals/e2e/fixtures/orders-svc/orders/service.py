"""Placing and changing orders."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Callable

from . import settings
from .errors import OrderRejected, UnknownCustomer, UnknownOrder
from .money import percent_of

Line = tuple[str, int, int]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


class OrderService:
    def __init__(self, conn: sqlite3.Connection, now: Callable[[], str] = utc_now) -> None:
        self.conn = conn
        self.now = now

    def place_order(self, customer_id: str, lines: list[Line], discount_percent: int = 0) -> str:
        """Place an order of (sku, unit price in cents, quantity) lines and return its id."""
        if self.conn.execute("SELECT 1 FROM customers WHERE customer_id = ?", (customer_id,)).fetchone() is None:
            raise UnknownCustomer(f"unknown customer {customer_id}")
        if not lines:
            raise OrderRejected("an order needs at least one line")
        if len(lines) > settings.get("orders", "max_lines"):
            raise OrderRejected(f"an order holds at most {settings.get('orders', 'max_lines')} lines")
        if not 0 <= discount_percent <= settings.get("discounts", "max_percent"):
            raise OrderRejected(f"discount must be between 0 and {settings.get('discounts', 'max_percent')} percent")
        if any(quantity < 1 for _, _, quantity in lines):
            raise OrderRejected("a quantity must be at least 1")
        subtotal = sum(price * quantity for _, price, quantity in lines)
        order_id = f"ord-{self.conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0] + 1:04d}"
        with self.conn:
            self.conn.execute("INSERT INTO orders VALUES (?, ?, 'placed', ?, ?)",
                              (order_id, customer_id, self.now(), percent_of(subtotal, discount_percent)))
            self.conn.executemany("INSERT INTO lines VALUES (?, ?, ?, ?)",
                                  [(order_id, sku, price, quantity) for sku, price, quantity in lines])
        return order_id

    def get_order(self, order_id: str) -> dict:
        row = self.conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        if row is None:
            raise UnknownOrder(f"unknown order {order_id}")
        return dict(row)

    def lines_of(self, order_id: str) -> list[Line]:
        rows = self.conn.execute("SELECT sku, unit_price_cents, quantity FROM lines WHERE order_id = ? ORDER BY rowid",
                                 (order_id,))
        return [(row["sku"], row["unit_price_cents"], row["quantity"]) for row in rows]

    def orders_of(self, customer_id: str) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM orders WHERE customer_id = ? ORDER BY rowid", (customer_id,))
        return [dict(row) for row in rows]

    def _move(self, order_id: str, status: str) -> None:
        if self.get_order(order_id)["status"] != "placed":
            raise OrderRejected(f"{order_id} is not a placed order")
        with self.conn:
            self.conn.execute("UPDATE orders SET status = ? WHERE order_id = ?", (status, order_id))

    def cancel_order(self, order_id: str) -> None:
        self._move(order_id, "cancelled")

    def ship_order(self, order_id: str) -> None:
        self._move(order_id, "shipped")

    def set_line(self, order_id: str, sku: str, quantity: int, unit_price_cents: int | None = None) -> None:
        """Set the quantity of a line, or add the line when it is new and a unit price is given."""
        self.get_order(order_id)
        if quantity < 1:
            raise OrderRejected("a quantity must be at least 1")
        exists = self.conn.execute("SELECT 1 FROM lines WHERE order_id = ? AND sku = ?", (order_id, sku)).fetchone()
        with self.conn:
            if exists:
                self.conn.execute("UPDATE lines SET quantity = ? WHERE order_id = ? AND sku = ?", (quantity, order_id, sku))
            elif unit_price_cents is None:
                raise OrderRejected(f"{order_id} has no line {sku}")
            else:
                self.conn.execute("INSERT INTO lines VALUES (?, ?, ?, ?)", (order_id, sku, unit_price_cents, quantity))
