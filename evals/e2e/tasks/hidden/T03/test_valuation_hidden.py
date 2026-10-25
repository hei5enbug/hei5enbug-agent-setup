import io
from decimal import Decimal

from inventory import reports
from inventory.app import create_app
from inventory.cli import main
from inventory.config import Config


def build(path, stock):
    app = create_app(path, Config(tax_rate=Decimal("0.10")))
    app.warehouses.add_warehouse("MAIN", "Main warehouse", priority=10)
    for sku, price in (("A-ONE", "10.00"), ("B-TWO", "5.00"), ("C-THREE", "2.00"), ("D-FOUR", "100.00")):
        app.catalog.add_item(sku, sku, Decimal(price))
    for sku, quantity in stock.items():
        app.stock.receive("MAIN", sku, quantity)
    return app


def expected_total(app, code="MAIN"):
    return sum((app.db.items[sku].unit_price * qty for sku, qty in app.db.stock[code].items()), Decimal("0"))


def test_item_after_an_emptied_one_is_still_counted(tmp_path):
    app = build(tmp_path / "d.json", {"A-ONE": 3, "B-TWO": 4, "C-THREE": 7, "D-FOUR": 1})
    app.orders.create_order("kim@example.com", [("B-TWO", 4)])
    assert app.stock.quantity("MAIN", "B-TWO") == 0
    valuation = reports.warehouse_valuation(app.db, "MAIN")
    assert valuation.total == Decimal("144.00") == expected_total(app)


def test_several_consecutive_empty_items(tmp_path):
    app = build(tmp_path / "d.json", {"A-ONE": 1, "B-TWO": 1, "C-THREE": 7, "D-FOUR": 2})
    app.db.stock["MAIN"]["A-ONE"] = 0
    app.db.stock["MAIN"]["B-TWO"] = 0
    valuation = reports.warehouse_valuation(app.db, "MAIN")
    assert valuation.total == Decimal("214.00")
    assert {row.sku for row in valuation.rows if row.quantity > 0} == {"C-THREE", "D-FOUR"}


def test_empty_item_first_and_last(tmp_path):
    app = build(tmp_path / "d.json", {"A-ONE": 1, "B-TWO": 2, "C-THREE": 3, "D-FOUR": 1})
    app.db.stock["MAIN"]["A-ONE"] = 0
    app.db.stock["MAIN"]["D-FOUR"] = 0
    assert reports.warehouse_valuation(app.db, "MAIN").total == Decimal("16.00")


def test_rows_add_up_to_the_total(tmp_path):
    app = build(tmp_path / "d.json", {"A-ONE": 3, "B-TWO": 4, "C-THREE": 7, "D-FOUR": 1})
    app.db.stock["MAIN"]["B-TWO"] = 0
    valuation = reports.warehouse_valuation(app.db, "MAIN")
    assert sum((row.value for row in valuation.rows), Decimal("0")) == valuation.total


def test_no_empty_items_gives_the_plain_sum(tmp_path):
    app = build(tmp_path / "d.json", {"A-ONE": 3, "B-TWO": 4, "C-THREE": 7, "D-FOUR": 1})
    assert reports.warehouse_valuation(app.db, "MAIN").total == Decimal("164.00")


def test_report_command_prints_the_corrected_total(tmp_path):
    path = tmp_path / "d.json"
    app = build(path, {"A-ONE": 3, "B-TWO": 4, "C-THREE": 7, "D-FOUR": 1})
    app.orders.create_order("kim@example.com", [("B-TWO", 4)])
    app.save()
    out = io.StringIO()
    assert main(["--data", str(path), "report"], environ={}, stdout=out, stderr=io.StringIO()) == 0
    assert "MAIN: 144.00" in out.getvalue()
