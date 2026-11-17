import sys

from patch_tools import replace, write

repo = sys.argv[1]
replace(repo, "inventory/audit.py", 'KIND_RELEASE = "release"\n',
        'KIND_RELEASE = "release"\nKIND_TRANSFER_OUT = "transfer_out"\nKIND_TRANSFER_IN = "transfer_in"\n')
replace(repo, "inventory/stock.py", "    def _require_warehouse(self, code: str) -> None:", '''    def transfer(self, source: str, target: str, sku: str, quantity: int, reference: str = "transfer") -> None:
        """Move units of one item from one warehouse to another, logging an out entry and an in entry."""
        sku = validate_sku(sku)
        validate_quantity(quantity)
        if source == target:
            raise ValidationError("source and target warehouse must differ")
        self._require_warehouse(source)
        self._require_warehouse(target)
        available = self.quantity(source, sku)
        if available < quantity:
            raise InsufficientStock(sku, quantity, available)
        self.db.stock.setdefault(source, {})[sku] = available - quantity
        levels = self.db.stock.setdefault(target, {})
        levels[sku] = levels.get(sku, 0) + quantity
        audit.record(
            self.db, self.clock, kind=audit.KIND_TRANSFER_OUT, sku=sku, warehouse=source, delta=-quantity,
            reference=reference,
        )
        audit.record(
            self.db, self.clock, kind=audit.KIND_TRANSFER_IN, sku=sku, warehouse=target, delta=quantity,
            reference=reference,
        )

    def _require_warehouse(self, code: str) -> None:''')
write(repo, "tests/test_transfer.py", '''import pytest

from inventory import audit
from inventory.errors import InsufficientStock


def test_transfer_moves_units_between_warehouses(app):
    app.stock.transfer("MAIN", "EAST", "WIDGET", 7)
    assert (app.stock.quantity("MAIN", "WIDGET"), app.stock.quantity("EAST", "WIDGET")) == (13, 12)
    assert [entry.kind for entry in app.db.audit[-2:]] == [audit.KIND_TRANSFER_OUT, audit.KIND_TRANSFER_IN]


def test_transfer_of_too_many_units_changes_nothing(app):
    with pytest.raises(InsufficientStock):
        app.stock.transfer("EAST", "MAIN", "WIDGET", 6)
    assert app.stock.total("WIDGET") == 25
''')
