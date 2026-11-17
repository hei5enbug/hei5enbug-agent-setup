import pytest

from inventory import audit
from inventory.errors import InsufficientStock, UnknownWarehouse, ValidationError


def test_transfer_moves_units_and_keeps_the_total(app):
    app.stock.transfer("MAIN", "EAST", "WIDGET", 7)
    assert app.stock.quantity("MAIN", "WIDGET") == 13
    assert app.stock.quantity("EAST", "WIDGET") == 12
    assert app.stock.total("WIDGET") == 25


def test_transfer_into_a_warehouse_without_the_item_creates_its_level(app):
    app.stock.transfer("MAIN", "EAST", "GADGET", 3)
    assert app.stock.quantity("EAST", "GADGET") == 3
    assert app.stock.quantity("MAIN", "GADGET") == 5


def test_transfer_logs_an_out_entry_then_an_in_entry_with_the_reference(app):
    before = len(app.db.audit)
    app.stock.transfer("MAIN", "EAST", "WIDGET", 4, reference="move-1")
    out, entry_in = app.db.audit[before:]
    assert (out.kind, out.warehouse, out.delta, out.reference) == (audit.KIND_TRANSFER_OUT, "MAIN", -4, "move-1")
    assert (entry_in.kind, entry_in.warehouse, entry_in.delta, entry_in.reference) == (audit.KIND_TRANSFER_IN, "EAST", 4, "move-1")
    assert audit.KIND_TRANSFER_OUT == "transfer_out" and audit.KIND_TRANSFER_IN == "transfer_in"


def test_transfer_reference_defaults_to_transfer(app):
    app.stock.transfer("MAIN", "EAST", "WIDGET", 1)
    assert {entry.reference for entry in app.db.audit[-2:]} == {"transfer"}


def test_audit_net_movement_does_not_change(app):
    net = audit.net_movement(app.db, "WIDGET")
    app.stock.transfer("MAIN", "EAST", "WIDGET", 6)
    assert audit.net_movement(app.db, "WIDGET") == net


def test_transfer_of_more_than_the_source_holds_fails_and_changes_nothing(app):
    before = len(app.db.audit)
    with pytest.raises(InsufficientStock) as excinfo:
        app.stock.transfer("EAST", "MAIN", "WIDGET", 6)
    assert (excinfo.value.requested, excinfo.value.available) == (6, 5)
    assert app.stock.quantity("EAST", "WIDGET") == 5 and app.stock.quantity("MAIN", "WIDGET") == 20
    assert len(app.db.audit) == before


def test_transfer_to_the_same_warehouse_is_a_validation_error(app):
    with pytest.raises(ValidationError):
        app.stock.transfer("MAIN", "MAIN", "WIDGET", 1)


@pytest.mark.parametrize("source,target", [("WEST", "EAST"), ("MAIN", "WEST")])
def test_transfer_with_an_unknown_warehouse_fails(app, source, target):
    with pytest.raises(UnknownWarehouse):
        app.stock.transfer(source, target, "WIDGET", 1)


@pytest.mark.parametrize("quantity", [0, -2])
def test_transfer_rejects_a_quantity_below_one(app, quantity):
    with pytest.raises(ValidationError):
        app.stock.transfer("MAIN", "EAST", "WIDGET", quantity)
