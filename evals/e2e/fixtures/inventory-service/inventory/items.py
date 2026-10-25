"""Item catalog."""

from __future__ import annotations

from decimal import Decimal

from .errors import UnknownItem, ValidationError
from .models import Database, Item
from .money import quantize
from .validators import validate_name, validate_sku


class CatalogService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add_item(self, sku: str, name: str, unit_price: Decimal, category: str = "general") -> Item:
        sku = validate_sku(sku)
        if sku in self.db.items:
            raise ValidationError(f"item already exists: {sku}")
        if unit_price < 0:
            raise ValidationError("unit price must not be negative")
        item = Item(
            sku=sku,
            name=validate_name(name),
            unit_price=quantize(unit_price),
            category=category.strip().lower() or "general",
        )
        self.db.items[sku] = item
        return item

    def get_item(self, sku: str) -> Item:
        key = validate_sku(sku)
        try:
            return self.db.items[key]
        except KeyError:
            raise UnknownItem(key) from None

    def set_price(self, sku: str, unit_price: Decimal) -> Item:
        item = self.get_item(sku)
        if unit_price < 0:
            raise ValidationError("unit price must not be negative")
        item.unit_price = quantize(unit_price)
        return item

    def deactivate(self, sku: str) -> Item:
        item = self.get_item(sku)
        item.active = False
        return item

    def list_items(self, *, category: str | None = None, include_inactive: bool = False) -> list[Item]:
        wanted = category.strip().lower() if category else None
        items = [
            item
            for item in self.db.items.values()
            if (include_inactive or item.active) and (wanted is None or item.category == wanted)
        ]
        return sorted(items, key=lambda item: item.sku)

    def categories(self) -> list[str]:
        return sorted({item.category for item in self.db.items.values() if item.active})
