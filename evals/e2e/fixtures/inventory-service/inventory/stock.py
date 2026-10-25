"""Stock ledger: per-warehouse quantities, receiving, and the allocation of order lines to warehouses."""

from __future__ import annotations

from . import audit
from .clock import Clock, utcnow
from .errors import InsufficientStock, UnknownWarehouse, ValidationError
from .models import Allocation, Database
from .validators import validate_quantity, validate_sku


class StockLedger:
    def __init__(self, db: Database, clock: Clock = utcnow) -> None:
        self.db = db
        self.clock = clock

    def quantity(self, warehouse: str, sku: str) -> int:
        return self.db.stock.get(warehouse, {}).get(sku, 0)

    def total(self, sku: str) -> int:
        return sum(levels.get(sku, 0) for levels in self.db.stock.values())

    def levels(self, warehouse: str) -> dict[str, int]:
        if warehouse not in self.db.warehouses:
            raise UnknownWarehouse(warehouse)
        return dict(self.db.stock.get(warehouse, {}))

    def receive(self, warehouse: str, sku: str, quantity: int, reference: str = "receive") -> int:
        """Add units to one warehouse and return the new quantity there."""
        sku = validate_sku(sku)
        validate_quantity(quantity)
        self._require_warehouse(warehouse)
        levels = self.db.stock.setdefault(warehouse, {})
        levels[sku] = levels.get(sku, 0) + quantity
        audit.record(
            self.db, self.clock, kind=audit.KIND_RECEIVE, sku=sku, warehouse=warehouse, delta=quantity,
            reference=reference,
        )
        return levels[sku]

    def adjust(self, warehouse: str, sku: str, new_quantity: int, reference: str = "adjust") -> int:
        """Set the counted quantity of one item in one warehouse and return the difference."""
        sku = validate_sku(sku)
        validate_quantity(new_quantity, allow_zero=True)
        self._require_warehouse(warehouse)
        levels = self.db.stock.setdefault(warehouse, {})
        delta = new_quantity - levels.get(sku, 0)
        levels[sku] = new_quantity
        if delta:
            audit.record(
                self.db, self.clock, kind=audit.KIND_ADJUST, sku=sku, warehouse=warehouse, delta=delta,
                reference=reference,
            )
        return delta

    def allocate(self, sku: str, quantity: int, reference: str) -> list[Allocation]:
        """Take units from warehouses in priority order and return where each part came from."""
        validate_quantity(quantity)
        available = self.total(sku)
        if available < quantity:
            raise InsufficientStock(sku, quantity, available)
        allocations: list[Allocation] = []
        remaining = quantity
        for warehouse in sorted(self.db.warehouses.values(), key=lambda w: (w.priority, w.code)):
            if remaining == 0:
                break
            levels = self.db.stock.setdefault(warehouse.code, {})
            taken = min(levels.get(sku, 0), remaining)
            if taken == 0:
                continue
            levels[sku] -= taken
            remaining -= taken
            allocations.append(Allocation(warehouse.code, taken))
            audit.record(
                self.db, self.clock, kind=audit.KIND_ALLOCATE, sku=sku, warehouse=warehouse.code,
                delta=-taken, reference=reference,
            )
        return allocations

    def release(self, sku: str, allocations: list[Allocation], reference: str) -> None:
        """Put previously allocated units back into the warehouses they were taken from."""
        for allocation in allocations:
            if allocation.warehouse not in self.db.warehouses:
                raise UnknownWarehouse(allocation.warehouse)
            if allocation.quantity <= 0:
                raise ValidationError(f"cannot release {allocation.quantity} units of {sku}")
        for allocation in allocations:
            levels = self.db.stock.setdefault(allocation.warehouse, {})
            levels[sku] = levels.get(sku, 0) + allocation.quantity
            audit.record(
                self.db, self.clock, kind=audit.KIND_RELEASE, sku=sku, warehouse=allocation.warehouse,
                delta=allocation.quantity, reference=reference,
            )

    def _require_warehouse(self, code: str) -> None:
        if code not in self.db.warehouses:
            raise UnknownWarehouse(code)
