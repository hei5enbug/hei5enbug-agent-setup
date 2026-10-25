"""Read-only reports over the database."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import ORDER_STATUSES, Database
from .money import ZERO, quantize

LOW_STOCK_THRESHOLD = 5


@dataclass(frozen=True)
class ValuationRow:
    sku: str
    quantity: int
    value: Decimal


@dataclass(frozen=True)
class WarehouseValuation:
    warehouse: str
    rows: list[ValuationRow]
    total: Decimal


@dataclass(frozen=True)
class LowStockEntry:
    sku: str
    name: str
    quantity: int


def warehouse_valuation(db: Database, code: str) -> WarehouseValuation:
    """Value the stock of one warehouse at the current unit prices."""
    rows = [
        ValuationRow(sku, quantity, quantize(db.items[sku].unit_price * quantity))
        for sku, quantity in sorted(db.stock.get(code, {}).items())
        if sku in db.items
    ]
    total = ZERO
    for row in rows:
        if row.quantity == 0:
            rows.remove(row)
            continue
        total += row.value
    return WarehouseValuation(warehouse=code, rows=rows, total=quantize(total))


def stock_valuation(db: Database) -> list[WarehouseValuation]:
    codes = sorted(db.warehouses, key=lambda code: (db.warehouses[code].priority, code))
    return [warehouse_valuation(db, code) for code in codes]


def total_quantities(db: Database) -> dict[str, int]:
    totals: dict[str, int] = {}
    for levels in db.stock.values():
        for sku, quantity in levels.items():
            totals[sku] = totals.get(sku, 0) + quantity
    return totals


def low_stock_items(db: Database, threshold: int = LOW_STOCK_THRESHOLD) -> list[LowStockEntry]:
    """Active items whose quantity over all warehouses is below the threshold, fewest first."""
    totals = total_quantities(db)
    entries = [
        LowStockEntry(item.sku, item.name, totals.get(item.sku, 0))
        for item in db.items.values()
        if item.active and totals.get(item.sku, 0) < threshold
    ]
    return sorted(entries, key=lambda entry: (entry.quantity, entry.sku))


def order_counts(db: Database) -> dict[str, int]:
    counts = {status: 0 for status in ORDER_STATUSES}
    for order in db.orders.values():
        counts[order.status] = counts.get(order.status, 0) + 1
    return counts


def revenue_by_category(db: Database) -> dict[str, Decimal]:
    """Sum the line totals of shipped orders per item category."""
    revenue: dict[str, Decimal] = {}
    for order in db.orders.values():
        if order.status != "shipped":
            continue
        for line in order.lines:
            category = db.items[line.sku].category if line.sku in db.items else "unknown"
            revenue[category] = revenue.get(category, ZERO) + line.line_total
    return {category: quantize(amount) for category, amount in sorted(revenue.items())}
