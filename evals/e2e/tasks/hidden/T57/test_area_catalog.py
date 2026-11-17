from decimal import Decimal

import pytest

from inventory.errors import UnknownItem, ValidationError
from inventory.models import Item
from inventory.validators import validate_tag


def test_item_tags_default_to_a_separate_empty_list_per_item():
    first, second = Item("A1", "A", Decimal("1.00")), Item("B1", "B", Decimal("1.00"))
    first.tags.append("x")
    assert second.tags == [] and Item("C1", "C", Decimal("1.00")).tags == []


@pytest.mark.parametrize("raw, cleaned", [("Sale", "sale"), ("  New-Arrival ", "new-arrival"), ("0day", "0day")])
def test_validate_tag_cleans_the_value(raw, cleaned):
    assert validate_tag(raw) == cleaned


@pytest.mark.parametrize("raw", ["", "  ", "-sale", "sa le", "sale!", "x" * 25, "세일"])
def test_validate_tag_rejects_bad_values(raw):
    with pytest.raises(ValidationError):
        validate_tag(raw)


def test_add_tag_keeps_tags_sorted_normalized_and_idempotent(app):
    app.catalog.add_tag("widget", "Sale")
    app.catalog.add_tag("WIDGET", "new")
    item = app.catalog.add_tag("WIDGET", " SALE ")
    assert item.tags == ["new", "sale"]
    assert app.catalog.get_item("WIDGET").tags == ["new", "sale"]


def test_a_sixth_distinct_tag_is_rejected_with_the_sku_in_the_message(app):
    for tag in ("a", "b", "c", "d", "e"):
        app.catalog.add_tag("WIDGET", tag)
    app.catalog.add_tag("WIDGET", "e")
    with pytest.raises(ValidationError, match="item WIDGET can have at most 5 tags"):
        app.catalog.add_tag("WIDGET", "f")
    assert app.catalog.get_item("WIDGET").tags == ["a", "b", "c", "d", "e"]


def test_add_tag_rejects_an_unknown_item_and_a_bad_tag_without_changing_anything(app):
    with pytest.raises(UnknownItem):
        app.catalog.add_tag("NOPE", "sale")
    with pytest.raises(ValidationError):
        app.catalog.add_tag("WIDGET", "bad tag")
    assert app.catalog.get_item("WIDGET").tags == []


def test_remove_tag_removes_one_tag_and_rejects_a_missing_one(app):
    app.catalog.add_tag("WIDGET", "sale")
    app.catalog.add_tag("WIDGET", "new")
    assert app.catalog.remove_tag("WIDGET", "SALE").tags == ["new"]
    with pytest.raises(ValidationError, match="item WIDGET has no tag sale"):
        app.catalog.remove_tag("WIDGET", "sale")


def test_list_items_filters_by_tag_and_combines_with_category(app):
    app.catalog.add_tag("WIDGET", "sale")
    app.catalog.add_tag("GADGET", "sale")
    app.catalog.add_tag("BOLT", "sale")
    assert [item.sku for item in app.catalog.list_items(tag="Sale")] == ["BOLT", "GADGET", "WIDGET"]
    assert [item.sku for item in app.catalog.list_items(tag="sale", category="hardware")] == ["GADGET", "WIDGET"]
    assert app.catalog.list_items(tag="none") == []


def test_tag_counts_cover_active_items_only_and_sort_by_tag(app):
    app.catalog.add_tag("WIDGET", "sale")
    app.catalog.add_tag("GADGET", "sale")
    app.catalog.add_tag("GADGET", "new")
    app.catalog.add_tag("BOLT", "zzz")
    app.catalog.deactivate("BOLT")
    counts = app.catalog.tag_counts()
    assert counts == {"new": 1, "sale": 2}
    assert list(counts) == ["new", "sale"]
