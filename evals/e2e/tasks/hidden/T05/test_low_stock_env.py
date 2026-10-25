import io
import json
from decimal import Decimal

import pytest

from inventory.app import create_app
from inventory.cli import main
from inventory.config import Config
from inventory.errors import ConfigError


def seeded(path):
    app = create_app(path, Config())
    app.warehouses.add_warehouse("MAIN", "Main warehouse", priority=10)
    for sku, quantity in (("LOWA", 3), ("MIDB", 8), ("HIGHC", 12)):
        app.catalog.add_item(sku, f"Item {sku.lower()}", Decimal("1.00"))
        app.stock.receive("MAIN", sku, quantity)
    app.save()


def report_text(path, environ):
    out = io.StringIO()
    assert main(["--data", str(path), "report"], environ=environ, stdout=out, stderr=io.StringIO()) == 0
    return out.getvalue()


def test_default_threshold_is_five():
    assert Config.from_env({}).low_stock_threshold == 5


def test_environment_sets_the_threshold():
    assert Config.from_env({"INVENTORY_LOW_STOCK": "10"}).low_stock_threshold == 10
    assert Config.from_env({"INVENTORY_LOW_STOCK": "0"}).low_stock_threshold == 0


@pytest.mark.parametrize("value", ["abc", "-1", "2.5"])
def test_bad_values_raise_config_error(value):
    with pytest.raises(ConfigError):
        Config.from_env({"INVENTORY_LOW_STOCK": value})


def test_text_report_follows_the_threshold(tmp_path):
    path = tmp_path / "d.json"
    seeded(path)
    default = report_text(path, {})
    assert "LOWA" in default and "MIDB" not in default
    raised = report_text(path, {"INVENTORY_LOW_STOCK": "10"})
    assert "LOWA" in raised and "MIDB" in raised and "HIGHC" not in raised
    assert "LOWA" not in report_text(path, {"INVENTORY_LOW_STOCK": "0"})


def test_json_report_follows_the_threshold_too(tmp_path):
    path = tmp_path / "d.json"
    seeded(path)
    out = io.StringIO()
    code = main(["--data", str(path), "report", "--format", "json"], environ={"INVENTORY_LOW_STOCK": "10"},
                stdout=out, stderr=io.StringIO())
    assert code == 0
    assert [entry["sku"] for entry in json.loads(out.getvalue())["low_stock"]] == ["LOWA", "MIDB"]


def test_invalid_environment_makes_the_command_fail_with_exit_two(tmp_path):
    path = tmp_path / "d.json"
    seeded(path)
    err = io.StringIO()
    code = main(["--data", str(path), "report"], environ={"INVENTORY_LOW_STOCK": "many"}, stdout=io.StringIO(), stderr=err)
    assert code == 2 and "INVENTORY_LOW_STOCK" in err.getvalue()
