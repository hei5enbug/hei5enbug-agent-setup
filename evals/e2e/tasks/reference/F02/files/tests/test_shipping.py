from decimal import Decimal

import pytest

from inventory.config import Config
from inventory.shipping import ShippingPolicy


def test_free_shipping_from_the_threshold():
    policy = ShippingPolicy()
    assert policy.quote(Decimal("99.99")) == Decimal("5.00")
    assert policy.quote(Decimal("100.00")) == Decimal("0.00")


def test_express_surcharge_is_always_added():
    assert ShippingPolicy().quote(Decimal("100.00"), "express") == Decimal("12.00")


def test_unknown_method_is_rejected():
    with pytest.raises(ValueError):
        ShippingPolicy().quote(Decimal("1"), "overnight")


def test_order_total_includes_shipping(app):
    order = app.orders.create_order("kim@example.com", [("WIDGET", 2)], shipping="express")
    assert order.shipping_fee == Decimal("17.00")
    assert order.total == order.subtotal + order.tax + Decimal("17.00")


def test_config_reads_shipping_variables():
    assert Config.from_env({"INVENTORY_SHIPPING_FEE": "7"}).shipping_policy.flat_fee == Decimal("7")
