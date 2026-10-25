from decimal import Decimal

import pytest

from inventory import audit
from inventory.app import create_app
from inventory.config import Config
from inventory.errors import InvalidOrderState, UnknownOrder, ValidationError


def build(path):
    app = create_app(path, Config(tax_rate=Decimal("0.10")))
    app.warehouses.add_warehouse("MAIN", "Main warehouse", priority=10)
    app.warehouses.add_warehouse("EAST", "East depot", priority=20)
    app.catalog.add_item("WIDGET", "Widget", Decimal("10.00"))
    app.catalog.add_item("BOLT", "Bolt", Decimal("1.00"))
    app.stock.receive("MAIN", "WIDGET", 6)
    app.stock.receive("EAST", "WIDGET", 10)
    app.stock.receive("EAST", "BOLT", 50)
    order = app.orders.create_order("kim@example.com", [("WIDGET", 12), ("BOLT", 20)])
    return app, order


def allocations(order, sku):
    line = next(line for line in order.lines if line.sku == sku)
    return [(a.warehouse, a.quantity) for a in line.allocations]


def test_stock_goes_back_to_the_last_allocated_warehouse_first(tmp_path):
    app, order = build(tmp_path / "d.json")
    assert allocations(order, "WIDGET") == [("MAIN", 6), ("EAST", 6)]
    result = app.orders.cancel_item(order.id, "WIDGET", 4)
    assert result is app.orders.get_order(order.id)
    assert app.stock.quantity("EAST", "WIDGET") == 8
    assert app.stock.quantity("MAIN", "WIDGET") == 0
    assert allocations(result, "WIDGET") == [("MAIN", 6), ("EAST", 2)]


def test_cancelling_more_than_the_last_allocation_spills_over(tmp_path):
    app, order = build(tmp_path / "d.json")
    result = app.orders.cancel_item(order.id, "WIDGET", 8)
    assert app.stock.quantity("EAST", "WIDGET") == 10
    assert app.stock.quantity("MAIN", "WIDGET") == 2
    assert allocations(result, "WIDGET") == [("MAIN", 4)]
    assert next(line for line in result.lines if line.sku == "WIDGET").quantity == 4


def test_totals_use_the_new_quantity_and_discount_tier(tmp_path):
    app, order = build(tmp_path / "d.json")
    assert (order.subtotal, order.tax, order.total) == (Decimal("133.00"), Decimal("13.30"), Decimal("146.30"))
    result = app.orders.cancel_item(order.id, "WIDGET", 4)
    assert (result.subtotal, result.tax, result.total) == (Decimal("99.00"), Decimal("9.90"), Decimal("108.90"))
    line = next(line for line in result.lines if line.sku == "WIDGET")
    assert line.line_total == Decimal("80.00")


def test_cancelling_a_whole_line_removes_it_and_keeps_the_order(tmp_path):
    app, order = build(tmp_path / "d.json")
    result = app.orders.cancel_item(order.id, "BOLT", 20)
    assert [line.sku for line in result.lines] == ["WIDGET"]
    assert result.status == "placed"
    assert app.stock.quantity("EAST", "BOLT") == 50


def test_cancelling_the_last_line_cancels_the_order(tmp_path):
    app, order = build(tmp_path / "d.json")
    app.orders.cancel_item(order.id, "BOLT", 20)
    result = app.orders.cancel_item(order.id, "WIDGET", 12)
    assert result.status == "cancelled"
    assert result.cancelled_at is not None
    assert result.lines == []
    assert result.total == Decimal("0.00")
    assert app.stock.quantity("MAIN", "WIDGET") == 6 and app.stock.quantity("EAST", "WIDGET") == 10
    with pytest.raises(InvalidOrderState):
        app.orders.cancel_order(order.id)


@pytest.mark.parametrize("quantity", [0, -1, 13])
def test_bad_quantities_are_validation_errors_and_change_nothing(tmp_path, quantity):
    app, order = build(tmp_path / "d.json")
    before = app.stock.total("WIDGET")
    with pytest.raises(ValidationError):
        app.orders.cancel_item(order.id, "WIDGET", quantity)
    assert app.stock.total("WIDGET") == before
    assert next(line for line in order.lines if line.sku == "WIDGET").quantity == 12


def test_a_sku_that_is_not_in_the_order_is_rejected(tmp_path):
    app, order = build(tmp_path / "d.json")
    app.catalog.add_item("NUT", "Nut", Decimal("1.00"))
    with pytest.raises(ValidationError):
        app.orders.cancel_item(order.id, "NUT", 1)


def test_only_placed_orders_can_be_partly_cancelled(tmp_path):
    app, order = build(tmp_path / "d.json")
    app.orders.ship_order(order.id)
    with pytest.raises(InvalidOrderState):
        app.orders.cancel_item(order.id, "WIDGET", 1)
    other = app.orders.create_order("lee@example.com", [("BOLT", 1)])
    app.orders.cancel_order(other.id)
    with pytest.raises(InvalidOrderState):
        app.orders.cancel_item(other.id, "BOLT", 1)
    with pytest.raises(UnknownOrder):
        app.orders.cancel_item(999, "BOLT", 1)


def test_audit_entries_use_the_cancel_item_reference(tmp_path):
    app, order = build(tmp_path / "d.json")
    app.orders.cancel_item(order.id, "WIDGET", 8)
    entries = audit.entries_for(app.db, reference=f"order-{order.id}:cancel-item")
    assert sum(entry.delta for entry in entries) == 8
    assert {(entry.warehouse, entry.delta) for entry in entries} == {("EAST", 6), ("MAIN", 2)}
    assert all(entry.kind == "release" for entry in entries)


def test_the_result_survives_save_and_load(tmp_path):
    path = tmp_path / "d.json"
    app, order = build(path)
    app.orders.cancel_item(order.id, "WIDGET", 8)
    app.save()
    loaded = create_app(path, Config(tax_rate=Decimal("0.10")))
    reloaded = loaded.orders.get_order(order.id)
    assert allocations(reloaded, "WIDGET") == [("MAIN", 4)]
    assert reloaded.total == app.orders.get_order(order.id).total
    assert loaded.stock.quantity("MAIN", "WIDGET") == 2
