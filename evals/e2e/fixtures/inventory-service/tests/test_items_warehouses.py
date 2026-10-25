from decimal import Decimal

import pytest

from inventory.errors import UnknownItem, UnknownWarehouse, ValidationError


def test_add_item_normalises_fields(app):
    item = app.catalog.add_item("nut-1", "  Hex   Nut ", Decimal("0.125"), "Parts")
    assert (item.sku, item.name, item.unit_price, item.category) == ("NUT-1", "Hex Nut", Decimal("0.13"), "parts")


def test_duplicate_item_is_rejected(app):
    with pytest.raises(ValidationError):
        app.catalog.add_item("widget", "Another", Decimal("1"))


def test_unknown_item_raises(app):
    with pytest.raises(UnknownItem):
        app.catalog.get_item("NOPE")


def test_list_items_filters_by_category_and_activity(app):
    app.catalog.deactivate("BOLT")
    assert [i.sku for i in app.catalog.list_items()] == ["GADGET", "WIDGET"]
    assert [i.sku for i in app.catalog.list_items(category="hardware")] == ["GADGET", "WIDGET"]
    assert [i.sku for i in app.catalog.list_items(include_inactive=True, category="parts")] == ["BOLT"]


def test_set_price_requires_non_negative(app):
    assert app.catalog.set_price("WIDGET", Decimal("11")).unit_price == Decimal("11.00")
    with pytest.raises(ValidationError):
        app.catalog.set_price("WIDGET", Decimal("-1"))


def test_warehouses_are_listed_by_priority(app):
    app.warehouses.add_warehouse("NORTH", "North", priority=5)
    assert [w.code for w in app.warehouses.list_warehouses()] == ["NORTH", "MAIN", "EAST"]


def test_warehouse_with_stock_cannot_be_removed(app):
    with pytest.raises(ValidationError):
        app.warehouses.remove_warehouse("MAIN")
    app.warehouses.add_warehouse("TEMP", "Temporary")
    app.warehouses.remove_warehouse("TEMP")
    with pytest.raises(UnknownWarehouse):
        app.warehouses.get_warehouse("TEMP")
