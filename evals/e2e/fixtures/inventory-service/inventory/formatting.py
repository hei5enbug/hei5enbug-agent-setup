"""Plain-text rendering used by the CLI."""

from __future__ import annotations

from typing import Sequence

from .models import Item, Order, Warehouse
from .money import format_money
from .reports import LowStockEntry, WarehouseValuation


def render_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    lines = ["  ".join(header.ljust(widths[i]) for i, header in enumerate(headers)).rstrip()]
    lines.append("  ".join("-" * width for width in widths))
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return "\n".join(lines)


def render_items(items: Sequence[Item]) -> str:
    rows = [[item.sku, item.name, item.category, format_money(item.unit_price)] for item in items]
    return render_table(["SKU", "NAME", "CATEGORY", "PRICE"], rows)


def render_warehouses(warehouses: Sequence[Warehouse]) -> str:
    rows = [[w.code, w.name, str(w.priority)] for w in warehouses]
    return render_table(["CODE", "NAME", "PRIORITY"], rows)


def render_order(order: Order) -> str:
    lines = [f"Order #{order.id} ({order.status})", f"Customer: {order.customer}"]
    for line in order.lines:
        places = ", ".join(f"{a.warehouse}:{a.quantity}" for a in line.allocations)
        lines.append(f"  {line.sku} x{line.quantity} @ {format_money(line.unit_price)} = {format_money(line.line_total)} [{places}]")
    lines.append(f"Subtotal: {format_money(order.subtotal)}")
    lines.append(f"Tax: {format_money(order.tax)}")
    lines.append(f"Total: {format_money(order.total)}")
    return "\n".join(lines)


def render_orders(orders: Sequence[Order]) -> str:
    rows = [[str(o.id), o.status, o.customer, format_money(o.total)] for o in orders]
    return render_table(["ID", "STATUS", "CUSTOMER", "TOTAL"], rows)


def render_valuation(valuations: Sequence[WarehouseValuation]) -> str:
    lines = ["Valuation by warehouse:"]
    for valuation in valuations:
        lines.append(f"  {valuation.warehouse}: {format_money(valuation.total)}")
    return "\n".join(lines)


def render_low_stock(entries: Sequence[LowStockEntry], threshold: int) -> str:
    lines = [f"Low stock (below {threshold}):"]
    if not entries:
        lines.append("  none")
    for entry in entries:
        lines.append(f"  {entry.sku}  {entry.name}  qty {entry.quantity}")
    return "\n".join(lines)


def render_order_counts(counts: dict[str, int]) -> str:
    lines = ["Orders:"]
    for status, count in counts.items():
        lines.append(f"  {status}: {count}")
    return "\n".join(lines)
