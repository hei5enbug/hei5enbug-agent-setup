"""Conversion between the in-memory records and the JSON document written by the storage layer."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from .models import Allocation, AuditEntry, Database, Item, Order, OrderLine, Warehouse

SCHEMA_VERSION = 1


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def item_to_dict(item: Item) -> dict[str, Any]:
    return {
        "sku": item.sku,
        "name": item.name,
        "unit_price": str(item.unit_price),
        "category": item.category,
        "active": item.active,
    }


def item_from_dict(data: dict[str, Any]) -> Item:
    return Item(
        sku=data["sku"],
        name=data["name"],
        unit_price=Decimal(data["unit_price"]),
        category=data.get("category", "general"),
        active=data.get("active", True),
    )


def line_to_dict(line: OrderLine) -> dict[str, Any]:
    return {
        "sku": line.sku,
        "quantity": line.quantity,
        "unit_price": str(line.unit_price),
        "line_total": str(line.line_total),
        "allocations": [{"warehouse": a.warehouse, "quantity": a.quantity} for a in line.allocations],
    }


def line_from_dict(data: dict[str, Any]) -> OrderLine:
    return OrderLine(
        sku=data["sku"],
        quantity=data["quantity"],
        unit_price=Decimal(data["unit_price"]),
        line_total=Decimal(data["line_total"]),
        allocations=[Allocation(a["warehouse"], a["quantity"]) for a in data.get("allocations", [])],
    )


def order_to_dict(order: Order) -> dict[str, Any]:
    return {
        "id": order.id,
        "customer": order.customer,
        "status": order.status,
        "lines": [line_to_dict(line) for line in order.lines],
        "created_at": _iso(order.created_at),
        "subtotal": str(order.subtotal),
        "tax": str(order.tax),
        "total": str(order.total),
        "shipped_at": _iso(order.shipped_at),
        "cancelled_at": _iso(order.cancelled_at),
    }


def order_from_dict(data: dict[str, Any]) -> Order:
    return Order(
        id=data["id"],
        customer=data["customer"],
        status=data["status"],
        lines=[line_from_dict(line) for line in data["lines"]],
        created_at=datetime.fromisoformat(data["created_at"]),
        subtotal=Decimal(data["subtotal"]),
        tax=Decimal(data["tax"]),
        total=Decimal(data["total"]),
        shipped_at=_dt(data.get("shipped_at")),
        cancelled_at=_dt(data.get("cancelled_at")),
    )


def audit_to_dict(entry: AuditEntry) -> dict[str, Any]:
    return {
        "at": entry.at.isoformat(),
        "kind": entry.kind,
        "sku": entry.sku,
        "warehouse": entry.warehouse,
        "delta": entry.delta,
        "reference": entry.reference,
    }


def audit_from_dict(data: dict[str, Any]) -> AuditEntry:
    return AuditEntry(
        at=datetime.fromisoformat(data["at"]),
        kind=data["kind"],
        sku=data["sku"],
        warehouse=data["warehouse"],
        delta=data["delta"],
        reference=data["reference"],
    )


def database_to_dict(db: Database) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "items": [item_to_dict(item) for item in db.items.values()],
        "warehouses": [
            {"code": w.code, "name": w.name, "priority": w.priority} for w in db.warehouses.values()
        ],
        "stock": {code: dict(levels) for code, levels in db.stock.items()},
        "orders": [order_to_dict(order) for order in db.orders.values()],
        "audit": [audit_to_dict(entry) for entry in db.audit],
        "next_order_id": db.next_order_id,
    }


def database_from_dict(data: dict[str, Any]) -> Database:
    items = {entry["sku"]: item_from_dict(entry) for entry in data.get("items", [])}
    warehouses = {
        entry["code"]: Warehouse(entry["code"], entry["name"], entry.get("priority", 100))
        for entry in data.get("warehouses", [])
    }
    orders = {entry["id"]: order_from_dict(entry) for entry in data.get("orders", [])}
    return Database(
        items=items,
        warehouses=warehouses,
        stock={code: dict(levels) for code, levels in data.get("stock", {}).items()},
        orders=orders,
        audit=[audit_from_dict(entry) for entry in data.get("audit", [])],
        next_order_id=data.get("next_order_id", max(orders, default=0) + 1),
    )
