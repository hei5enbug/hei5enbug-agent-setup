import dataclasses
import io
import json
from decimal import Decimal

import pytest

from inventory.app import create_app
from inventory.cli import main
from inventory.config import Config
from inventory.errors import ConfigError
from inventory.shipping import ShippingPolicy

POLICY = ShippingPolicy(
    flat_fee=Decimal("5.00"), free_threshold=Decimal("100.00"), express_surcharge=Decimal("12.00")
)
TAX_ENV = {"INVENTORY_TAX_RATE": "0.10"}


def seeded_app(path, environ=TAX_ENV, stock=100):
    app = create_app(path, Config.from_env(environ))
    app.warehouses.add_warehouse("MAIN", "Main warehouse", priority=10)
    app.catalog.add_item("WIDGET", "Widget", Decimal("10.00"), "hardware")
    app.stock.receive("MAIN", "WIDGET", stock)
    return app


def run_cli(path, *argv, environ=TAX_ENV):
    out, err = io.StringIO(), io.StringIO()
    code = main(["--data", str(path), *argv], environ=environ, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_standard_quote_is_free_from_the_threshold():
    assert POLICY.quote(Decimal("99.99")) == Decimal("5.00")
    assert POLICY.quote(Decimal("100.00")) == Decimal("0.00")
    assert POLICY.quote(Decimal("500"), "standard") == Decimal("0.00")


def test_express_adds_the_surcharge_even_when_shipping_is_free():
    assert POLICY.quote(Decimal("99.99"), "express") == Decimal("17.00")
    assert POLICY.quote(Decimal("100.00"), "express") == Decimal("12.00")


def test_unknown_method_is_a_value_error():
    with pytest.raises(ValueError):
        POLICY.quote(Decimal("10"), "overnight")


def test_policy_is_frozen_and_has_documented_defaults():
    with pytest.raises(dataclasses.FrozenInstanceError):
        POLICY.flat_fee = Decimal("1")
    default = ShippingPolicy()
    assert (default.flat_fee, default.free_threshold, default.express_surcharge) == (
        Decimal("5.00"),
        Decimal("100.00"),
        Decimal("12.00"),
    )


def test_config_reads_the_three_variables():
    policy = Config.from_env(
        {
            "INVENTORY_SHIPPING_FEE": "7.50",
            "INVENTORY_FREE_SHIPPING_MIN": "250",
            "INVENTORY_EXPRESS_SURCHARGE": "20",
        }
    ).shipping_policy
    assert (policy.flat_fee, policy.free_threshold, policy.express_surcharge) == (
        Decimal("7.50"),
        Decimal("250"),
        Decimal("20"),
    )
    assert Config.from_env({}).shipping_policy == ShippingPolicy()


@pytest.mark.parametrize(
    "name", ["INVENTORY_SHIPPING_FEE", "INVENTORY_FREE_SHIPPING_MIN", "INVENTORY_EXPRESS_SURCHARGE"]
)
@pytest.mark.parametrize("value", ["abc", "-1"])
def test_bad_shipping_variables_raise_config_error(name, value):
    with pytest.raises(ConfigError):
        Config.from_env({name: value})


def test_order_total_includes_shipping_but_tax_ignores_it(tmp_path):
    app = seeded_app(tmp_path / "d.json")
    standard = app.orders.create_order("kim@example.com", [("WIDGET", 5)])
    express = app.orders.create_order("kim@example.com", [("WIDGET", 5)], shipping="express")
    assert (standard.subtotal, standard.tax) == (Decimal("50.00"), Decimal("5.00"))
    assert (standard.shipping_method, standard.shipping_fee, standard.total) == (
        "standard",
        Decimal("5.00"),
        Decimal("60.00"),
    )
    assert (express.shipping_method, express.shipping_fee, express.total) == (
        "express",
        Decimal("17.00"),
        Decimal("72.00"),
    )


def test_free_shipping_applies_on_the_discounted_subtotal(tmp_path):
    app = seeded_app(tmp_path / "d.json")
    just_below = app.orders.create_order("kim@example.com", [("WIDGET", 10)])
    free = app.orders.create_order("kim@example.com", [("WIDGET", 11)])
    assert just_below.subtotal == Decimal("95.00") and just_below.shipping_fee == Decimal("5.00")
    assert free.subtotal == Decimal("104.50") and free.shipping_fee == Decimal("0.00")
    assert free.total == Decimal("104.50") + Decimal("10.45")


def test_policy_comes_from_the_config_of_the_app(tmp_path):
    environ = {**TAX_ENV, "INVENTORY_SHIPPING_FEE": "9.00", "INVENTORY_FREE_SHIPPING_MIN": "1000"}
    app = seeded_app(tmp_path / "d.json", environ)
    order = app.orders.create_order("kim@example.com", [("WIDGET", 11)])
    assert order.shipping_fee == Decimal("9.00")


def test_invalid_method_fails_without_touching_stock(tmp_path):
    app = seeded_app(tmp_path / "d.json")
    with pytest.raises(ValueError):
        app.orders.create_order("kim@example.com", [("WIDGET", 5)], shipping="overnight")
    assert app.stock.total("WIDGET") == 100
    assert app.db.orders == {}


def test_shipping_survives_save_and_load(tmp_path):
    path = tmp_path / "d.json"
    app = seeded_app(path)
    order = app.orders.create_order("kim@example.com", [("WIDGET", 5)], shipping="express")
    app.save()
    loaded = create_app(path, Config.from_env(TAX_ENV)).orders.get_order(order.id)
    assert (loaded.shipping_method, loaded.shipping_fee, loaded.total) == ("express", Decimal("17.00"), Decimal("72.00"))


def test_files_written_before_shipping_existed_still_load(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "items": [{"sku": "WIDGET", "name": "Widget", "unit_price": "10.00", "category": "hardware", "active": True}],
                "warehouses": [{"code": "MAIN", "name": "Main warehouse", "priority": 10}],
                "stock": {"MAIN": {"WIDGET": 95}},
                "orders": [
                    {
                        "id": 1,
                        "customer": "kim@example.com",
                        "status": "placed",
                        "lines": [
                            {
                                "sku": "WIDGET",
                                "quantity": 5,
                                "unit_price": "10.00",
                                "line_total": "50.00",
                                "allocations": [{"warehouse": "MAIN", "quantity": 5}],
                            }
                        ],
                        "created_at": "2026-01-02T03:04:05+00:00",
                        "subtotal": "50.00",
                        "tax": "5.00",
                        "total": "55.00",
                        "shipped_at": None,
                        "cancelled_at": None,
                    }
                ],
                "audit": [],
                "next_order_id": 2,
            }
        ),
        encoding="utf-8",
    )
    order = create_app(path, Config.from_env(TAX_ENV)).orders.get_order(1)
    assert order.shipping_method == "standard"
    assert order.shipping_fee == Decimal("0")
    assert order.total == Decimal("55.00")


def test_cli_creates_and_shows_an_express_order(tmp_path):
    path = tmp_path / "d.json"
    seeded_app(path).save()
    code, out, _ = run_cli(path, "order", "create", "--customer", "kim@example.com", "--line", "WIDGET=5", "--shipping", "express")
    assert code == 0 and "total 72.00" in out
    code, out, _ = run_cli(path, "order", "show", "1")
    assert code == 0
    lines = out.splitlines()
    assert "Shipping: 17.00 (express)" in lines
    assert lines.index("Shipping: 17.00 (express)") < lines.index("Total: 72.00")


def test_cli_defaults_to_standard_and_reads_environment(tmp_path):
    path = tmp_path / "d.json"
    seeded_app(path).save()
    environ = {**TAX_ENV, "INVENTORY_SHIPPING_FEE": "6.00"}
    assert run_cli(path, "order", "create", "--customer", "kim@example.com", "--line", "WIDGET=5", environ=environ)[0] == 0
    assert "Shipping: 6.00 (standard)" in run_cli(path, "order", "show", "1", environ=environ)[1].splitlines()


def test_cli_rejects_an_unknown_method(tmp_path):
    path = tmp_path / "d.json"
    seeded_app(path).save()
    with pytest.raises(SystemExit) as raised:
        run_cli(path, "order", "create", "--customer", "kim@example.com", "--line", "WIDGET=5", "--shipping", "overnight")
    assert raised.value.code == 2
