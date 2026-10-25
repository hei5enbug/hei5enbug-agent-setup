import json

import pytest

from inventory.app import create_app
from inventory.config import Config
from inventory.errors import StorageError
from inventory.storage import JsonStore


def test_missing_file_loads_as_empty_database(tmp_path):
    db = JsonStore(tmp_path / "none.json").load()
    assert db.items == {} and db.orders == {} and db.next_order_id == 1


def test_round_trip_keeps_orders_and_allocations(app, data_file):
    order = app.orders.create_order("kim@example.com", [("WIDGET", 22)])
    app.save()

    reloaded = create_app(data_file, Config()).db

    assert reloaded.orders[order.id].total == order.total
    assert [(a.warehouse, a.quantity) for a in reloaded.orders[order.id].lines[0].allocations] == [
        ("MAIN", 20),
        ("EAST", 2),
    ]
    assert reloaded.stock["MAIN"]["WIDGET"] == 0
    assert len(reloaded.audit) == len(app.db.audit)


def test_corrupt_file_raises_storage_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(StorageError):
        JsonStore(path).load()


def test_newer_schema_is_refused(tmp_path):
    path = tmp_path / "new.json"
    path.write_text(json.dumps({"schema": 99}), encoding="utf-8")
    with pytest.raises(StorageError):
        JsonStore(path).load()


def test_save_leaves_no_temp_files(app, data_file):
    app.save()
    assert [p.name for p in data_file.parent.iterdir()] == ["inventory.json"]
