import pytest

from inventory import audit
from inventory.errors import InsufficientStock, UnknownWarehouse, ValidationError
from inventory.models import Allocation


def test_receive_adds_to_one_warehouse(app):
    assert app.stock.receive("EAST", "GADGET", 4) == 4
    assert app.stock.total("GADGET") == 12


def test_receive_in_unknown_warehouse_fails(app):
    with pytest.raises(UnknownWarehouse):
        app.stock.receive("WEST", "WIDGET", 1)


def test_adjust_returns_the_difference_and_logs_it(app):
    assert app.stock.adjust("MAIN", "WIDGET", 17) == -3
    assert app.stock.quantity("MAIN", "WIDGET") == 17
    assert audit.entries_for(app.db, sku="WIDGET")[-1].kind == audit.KIND_ADJUST


def test_allocate_draws_from_the_lowest_priority_number_first(app):
    allocations = app.stock.allocate("WIDGET", 22, "test")
    assert allocations == [Allocation("MAIN", 20), Allocation("EAST", 2)]
    assert app.stock.quantity("EAST", "WIDGET") == 3


def test_allocate_fails_without_changing_anything(app):
    with pytest.raises(InsufficientStock) as excinfo:
        app.stock.allocate("GADGET", 9, "test")
    assert excinfo.value.available == 8
    assert app.stock.total("GADGET") == 8


def test_release_returns_units_to_their_warehouses(app):
    allocations = app.stock.allocate("WIDGET", 22, "test")
    app.stock.release("WIDGET", allocations, "test")
    assert app.stock.quantity("MAIN", "WIDGET") == 20
    assert app.stock.quantity("EAST", "WIDGET") == 5


def test_release_to_unknown_warehouse_changes_nothing(app):
    with pytest.raises(UnknownWarehouse):
        app.stock.release("WIDGET", [Allocation("MAIN", 1), Allocation("GONE", 1)], "test")
    assert app.stock.quantity("MAIN", "WIDGET") == 20


def test_release_rejects_non_positive_quantity(app):
    with pytest.raises(ValidationError):
        app.stock.release("WIDGET", [Allocation("MAIN", 0)], "test")


def test_audit_log_matches_stock_movement(app):
    app.stock.allocate("WIDGET", 22, "test")
    assert audit.net_movement(app.db, "WIDGET") == 25 - 22
