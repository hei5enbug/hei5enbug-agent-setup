from decimal import Decimal

from inventory import reports


def test_warehouse_valuation_prices_each_row(app):
    valuation = reports.warehouse_valuation(app.db, "MAIN")
    assert [(r.sku, r.quantity, r.value) for r in valuation.rows] == [
        ("GADGET", 8, Decimal("204.00")),
        ("WIDGET", 20, Decimal("200.00")),
    ]
    assert valuation.total == Decimal("404.00")


def test_stock_valuation_follows_warehouse_priority(app):
    assert [v.warehouse for v in reports.stock_valuation(app.db)] == ["MAIN", "EAST"]
    assert reports.stock_valuation(app.db)[1].total == Decimal("90.00")


def test_low_stock_uses_totals_over_all_warehouses(app):
    app.orders.create_order("kim@example.com", [("WIDGET", 22)])
    entries = reports.low_stock_items(app.db)
    assert [(e.sku, e.quantity) for e in entries] == [("WIDGET", 3)]


def test_low_stock_threshold_is_exclusive(app):
    assert [e.sku for e in reports.low_stock_items(app.db, threshold=8)] == []
    assert [e.sku for e in reports.low_stock_items(app.db, threshold=9)] == ["GADGET"]


def test_inactive_items_are_not_reported_as_low(app):
    app.stock.adjust("MAIN", "GADGET", 1)
    app.catalog.deactivate("GADGET")
    assert reports.low_stock_items(app.db) == []


def test_order_counts_cover_every_status(app):
    first = app.orders.create_order("kim@example.com", [("BOLT", 1)])
    second = app.orders.create_order("lee@example.com", [("BOLT", 1)])
    app.orders.cancel_order(first.id)
    app.orders.ship_order(second.id)
    assert reports.order_counts(app.db) == {"placed": 0, "shipped": 1, "cancelled": 1}


def test_revenue_counts_shipped_orders_only(app):
    shipped = app.orders.create_order("kim@example.com", [("WIDGET", 10), ("BOLT", 5)])
    app.orders.create_order("lee@example.com", [("GADGET", 2)])
    app.orders.ship_order(shipped.id)
    assert reports.revenue_by_category(app.db) == {"hardware": Decimal("95.00"), "parts": Decimal("2.00")}
