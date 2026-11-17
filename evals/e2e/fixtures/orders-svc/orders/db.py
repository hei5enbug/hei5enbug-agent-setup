"""The SQLite connection and schema."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "orders.db"
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS customers (customer_id TEXT PRIMARY KEY, name TEXT NOT NULL, tier TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS orders (order_id TEXT NOT NULL, customer_id TEXT NOT NULL, status TEXT NOT NULL, "
    "placed_at TEXT NOT NULL, discount_cents INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS lines (order_id TEXT NOT NULL, sku TEXT NOT NULL, unit_price_cents INTEGER NOT NULL, "
    "quantity INTEGER NOT NULL)",
)


def connect(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    target = Path(path or os.environ.get("ORDERS_DB") or DEFAULT_DB_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=10)
    conn.row_factory = sqlite3.Row
    with conn:
        for statement in SCHEMA:
            conn.execute(statement)
    return conn
