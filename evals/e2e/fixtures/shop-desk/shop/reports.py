"""Reports over the stored orders."""

from __future__ import annotations

import os

from . import settings, store


def net_cents(order: dict) -> int:
    return order["subtotal_cents"] - order["discount_cents"]


def sales_report(path: str | os.PathLike[str]) -> list[dict]:
    """One row per customer: order count, net amount, and the tax on it at the configured rate."""
    rows: dict[int, dict] = {}
    for order in store.load(path)["orders"]:
        row = rows.setdefault(order["customer_id"], {"customer_id": order["customer_id"], "orders": 0, "net_cents": 0})
        row["orders"] += 1
        row["net_cents"] += net_cents(order)
    for row in rows.values():
        row["tax_cents"] = row["net_cents"] * settings.get("tax_percent") // 100
    return [rows[key] for key in sorted(rows)]


def customers_by_spend(orders: list[dict]) -> list[tuple[int, int]]:
    """Return (customer_id, spent_cents) pairs sorted by spend, highest first."""
    totals: dict[int, int] = {}
    for order in orders:
        totals[order["customer_id"]] = totals.get(order["customer_id"], 0) + net_cents(order)
    return list(totals.items())
