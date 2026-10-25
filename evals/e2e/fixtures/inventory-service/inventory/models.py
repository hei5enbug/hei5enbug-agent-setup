"""Plain data records shared by the services and the JSON storage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

ORDER_PLACED = "placed"
ORDER_SHIPPED = "shipped"
ORDER_CANCELLED = "cancelled"
ORDER_STATUSES = (ORDER_PLACED, ORDER_SHIPPED, ORDER_CANCELLED)


@dataclass
class Item:
    sku: str
    name: str
    unit_price: Decimal
    category: str = "general"
    active: bool = True


@dataclass(frozen=True)
class Warehouse:
    code: str
    name: str
    priority: int = 100


@dataclass(frozen=True)
class Allocation:
    """Units of one order line taken from one warehouse."""

    warehouse: str
    quantity: int


@dataclass
class OrderLine:
    sku: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    allocations: list[Allocation] = field(default_factory=list)


@dataclass
class Order:
    id: int
    customer: str
    status: str
    lines: list[OrderLine]
    created_at: datetime
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    shipped_at: datetime | None = None
    cancelled_at: datetime | None = None


@dataclass(frozen=True)
class AuditEntry:
    at: datetime
    kind: str
    sku: str
    warehouse: str
    delta: int
    reference: str


@dataclass
class Database:
    """Everything the service persists. Services mutate it and the app saves it."""

    items: dict[str, Item] = field(default_factory=dict)
    warehouses: dict[str, Warehouse] = field(default_factory=dict)
    stock: dict[str, dict[str, int]] = field(default_factory=dict)
    orders: dict[int, Order] = field(default_factory=dict)
    audit: list[AuditEntry] = field(default_factory=list)
    next_order_id: int = 1
