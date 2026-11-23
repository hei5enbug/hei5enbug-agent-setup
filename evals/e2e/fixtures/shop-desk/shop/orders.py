"""Placing orders."""

from __future__ import annotations

import os
from datetime import date

from . import catalog, customers, store
from .discounts import tier_discount_cents
from .errors import ValidationError
from .models import OrderLine


def parse_lines(text: str) -> list[tuple[str, int]]:
    """Parse `AB-100:2,CD-200:1` into (sku, quantity) pairs."""
    pairs = []
    for part in text.split(","):
        sku, _, quantity = part.partition(":")
        if not sku or not quantity.isdigit() or int(quantity) < 1:
            raise ValidationError(f"bad order line: {part!r}")
        pairs.append((sku, int(quantity)))
    return pairs


def place_order(path: str | os.PathLike[str], customer_id: int, lines: list[tuple[str, int]],
                placed_on: date | None = None, ref: str | None = None) -> dict:
    customer = customers.lookup_customer(path, customer_id)
    priced = [OrderLine(sku, quantity, catalog.price_cents(sku)) for sku, quantity in lines]
    subtotal = sum(line.total_cents for line in priced)
    discount = tier_discount_cents(customer["tier"], subtotal)
    data = store.load(path)
    order = {
        "id": len(data["orders"]) + 1,
        "ref": ref,
        "customer_id": customer_id,
        "lines": [{"sku": line.sku, "quantity": line.quantity, "unit_cents": line.unit_cents} for line in priced],
        "subtotal_cents": subtotal,
        "discount_cents": discount,
        "placed_on": (placed_on or date.today()).isoformat(),
    }
    data["orders"].append(order)
    store.save(path, data)
    return order
