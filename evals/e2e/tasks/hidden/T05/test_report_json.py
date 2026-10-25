import io
import json
from decimal import Decimal

import pytest

from inventory.app import create_app
from inventory.cli import main
from inventory.config import Config


def seeded(path):
    app = create_app(path, Config(tax_rate=Decimal("0.10")))
    app.warehouses.add_warehouse("MAIN", "Main warehouse", priority=10)
    app.warehouses.add_warehouse("EAST", "East depot", priority=20)
    app.catalog.add_item("WIDGET", "Widget", Decimal("10.00"))
    app.catalog.add_item("GADGET", "Gadget", Decimal("25.50"))
    app.catalog.add_item("BOLT", "Bolt", Decimal("0.40"))
    app.stock.receive("MAIN", "WIDGET", 20)
    app.stock.receive("MAIN", "GADGET", 8)
    app.stock.receive("EAST", "WIDGET", 5)
    app.stock.receive("EAST", "BOLT", 100)
    app.orders.create_order("kim@example.com", [("WIDGET", 22)])
    shipped = app.orders.create_order("lee@example.com", [("BOLT", 10)])
    app.orders.ship_order(shipped.id)
    cancelled = app.orders.create_order("park@example.com", [("BOLT", 1)])
    app.orders.cancel_order(cancelled.id)
    app.save()


def report(path, *extra):
    out, err = io.StringIO(), io.StringIO()
    code = main(["--data", str(path), "report", *extra], environ={}, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_json_report_has_the_documented_shape(tmp_path):
    path = tmp_path / "d.json"
    seeded(path)
    code, out, _ = report(path, "--format", "json")
    assert code == 0
    data = json.loads(out)
    assert list(data["valuation"]) == ["MAIN", "EAST"]
    assert data["valuation"] == {"MAIN": "204.00", "EAST": "66.00"}
    assert data["low_stock"] == [{"sku": "WIDGET", "name": "Widget", "quantity": 3}]
    assert data["orders"] == {"placed": 1, "shipped": 1, "cancelled": 1}


def test_json_output_is_a_single_json_document(tmp_path):
    path = tmp_path / "d.json"
    seeded(path)
    out = report(path, "--format", "json")[1]
    assert out.lstrip().startswith("{") and json.loads(out)


def test_text_is_still_the_default_and_matches_explicit_text(tmp_path):
    path = tmp_path / "d.json"
    seeded(path)
    default = report(path)[1]
    assert "Valuation by warehouse:" in default and "MAIN: 204.00" in default
    assert report(path, "--format", "text")[1] == default


def test_unknown_format_is_rejected(tmp_path):
    path = tmp_path / "d.json"
    seeded(path)
    with pytest.raises(SystemExit) as raised:
        report(path, "--format", "xml")
    assert raised.value.code == 2


def test_empty_database_gives_empty_json_sections(tmp_path):
    data = json.loads(report(tmp_path / "none.json", "--format", "json")[1])
    assert data == {"valuation": {}, "low_stock": [], "orders": {"placed": 0, "shipped": 0, "cancelled": 0}}
