"""Warehouse registry. A lower priority number is drawn from first when an order is allocated."""

from __future__ import annotations

from .errors import UnknownWarehouse, ValidationError
from .models import Database, Warehouse
from .validators import validate_name, validate_warehouse_code


class WarehouseService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add_warehouse(self, code: str, name: str, priority: int = 100) -> Warehouse:
        code = validate_warehouse_code(code)
        if code in self.db.warehouses:
            raise ValidationError(f"warehouse already exists: {code}")
        if not 0 <= priority <= 1000:
            raise ValidationError("priority must be between 0 and 1000")
        warehouse = Warehouse(code=code, name=validate_name(name), priority=priority)
        self.db.warehouses[code] = warehouse
        self.db.stock.setdefault(code, {})
        return warehouse

    def get_warehouse(self, code: str) -> Warehouse:
        key = validate_warehouse_code(code)
        try:
            return self.db.warehouses[key]
        except KeyError:
            raise UnknownWarehouse(key) from None

    def list_warehouses(self) -> list[Warehouse]:
        return sorted(self.db.warehouses.values(), key=lambda w: (w.priority, w.code))

    def remove_warehouse(self, code: str) -> None:
        warehouse = self.get_warehouse(code)
        held = sum(self.db.stock.get(warehouse.code, {}).values())
        if held:
            raise ValidationError(f"warehouse {warehouse.code} still holds {held} units")
        del self.db.warehouses[warehouse.code]
        self.db.stock.pop(warehouse.code, None)
