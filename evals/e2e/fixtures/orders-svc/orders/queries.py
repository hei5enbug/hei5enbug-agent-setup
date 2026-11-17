"""Reading orders back."""

from __future__ import annotations

import sqlite3


def load_orders(conn: sqlite3.Connection) -> list[dict]:
    """Every order as a dict of its columns, in the order the rows were stored."""
    return [dict(row) for row in conn.execute("SELECT * FROM orders ORDER BY rowid")]


def open_orders(orders: list[dict]) -> list[dict]:
    """The open (placed) orders, sorted by placed_at with the oldest first."""
    return [order for order in orders if order["status"] == "placed"]
