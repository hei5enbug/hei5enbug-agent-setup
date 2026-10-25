from decimal import Decimal

import pytest

from inventory.errors import InsufficientStock, InvalidOrderState, UnknownItem, UnknownOrder, ValidationError


def test_create_order_allocates_stock_and_prices_lines(app):
    order = app.orders.create_order("kim@example.com", [("WIDGET", 22), ("BOLT", 10)])

    assert order.status == "placed"
    assert order.subtotal == Decimal("212.80")
    assert order.tax == Decimal("21.28")
    assert order.total == Decimal("234.08")
    assert [(a.warehouse, a.quantity) for a in order.lines[0].allocations] == [("MAIN", 20), ("EAST", 2)]
    assert app.stock.total("WIDGET") == 3


def test_duplicate_lines_are_merged(app):
    order = app.orders.create_order("kim@example.com", [("widget", 2), ("WIDGET", 3)])
    assert [(line.sku, line.quantity) for line in order.lines] == [("WIDGET", 5)]


def test_order_ids_increase(app):
    first = app.orders.create_order("kim@example.com", [("BOLT", 1)])
    second = app.orders.create_order("lee@example.com", [("BOLT", 1)])
    assert (first.id, second.id) == (1, 2)


def test_failed_order_restores_stock_taken_for_earlier_lines(app):
    with pytest.raises(InsufficientStock):
        app.orders.create_order("kim@example.com", [("WIDGET", 25), ("GADGET", 9)])
    assert app.stock.total("WIDGET") == 25
    assert app.db.orders == {}
    assert app.db.next_order_id == 1


def test_order_validation(app):
    with pytest.raises(ValidationError):
        app.orders.create_order("  ", [("BOLT", 1)])
    with pytest.raises(ValidationError):
        app.orders.create_order("kim@example.com", [])
    with pytest.raises(UnknownItem):
        app.orders.create_order("kim@example.com", [("NOPE", 1)])


def test_inactive_items_cannot_be_ordered(app):
    app.catalog.deactivate("BOLT")
    with pytest.raises(ValidationError):
        app.orders.create_order("kim@example.com", [("BOLT", 1)])


def test_cancel_returns_stock_to_the_warehouses_it_came_from(app):
    order = app.orders.create_order("kim@example.com", [("WIDGET", 22)])
    app.stock.receive("MAIN", "WIDGET", 7)

    cancelled = app.orders.cancel_order(order.id)

    assert cancelled.status == "cancelled"
    assert cancelled.cancelled_at is not None
    assert app.stock.quantity("MAIN", "WIDGET") == 27
    assert app.stock.quantity("EAST", "WIDGET") == 5


def test_cancel_twice_is_rejected(app):
    order = app.orders.create_order("kim@example.com", [("BOLT", 1)])
    app.orders.cancel_order(order.id)
    with pytest.raises(InvalidOrderState):
        app.orders.cancel_order(order.id)


def test_shipped_orders_cannot_be_cancelled(app):
    order = app.orders.create_order("kim@example.com", [("BOLT", 1)])
    app.orders.ship_order(order.id)
    with pytest.raises(InvalidOrderState):
        app.orders.cancel_order(order.id)
    assert app.stock.total("BOLT") == 99


def test_unknown_order_raises(app):
    with pytest.raises(UnknownOrder):
        app.orders.get_order(99)


def test_list_orders_filters_by_status(app):
    first = app.orders.create_order("kim@example.com", [("BOLT", 1)])
    second = app.orders.create_order("lee@example.com", [("BOLT", 2)])
    app.orders.cancel_order(first.id)
    assert [o.id for o in app.orders.list_orders("placed")] == [second.id]
    assert [o.id for o in app.orders.list_orders()] == [first.id, second.id]
