import json
from decimal import Decimal

import pytest

from inventory.app import create_app
from inventory.config import Config
from inventory.errors import StorageError
from inventory.models import Item
from inventory.serialization import SCHEMA_VERSION, item_from_dict, item_to_dict
from inventory.storage import JsonStore


def test_item_dict_round_trip_keeps_tags():
    item = Item("W1", "Widget", Decimal("1.00"), tags=["new", "sale"])
    data = item_to_dict(item)
    assert data["tags"] == ["new", "sale"]
    assert item_from_dict(data).tags == ["new", "sale"]


def test_an_old_item_without_tags_reads_as_an_empty_list():
    data = {"sku": "W1", "name": "Widget", "unit_price": "1.00"}
    assert item_from_dict(data).tags == []


def test_the_schema_is_two_and_new_files_say_so(app, data_file):
    app.catalog.add_tag("WIDGET", "sale")
    app.save()
    stored = json.loads(data_file.read_text(encoding="utf-8"))
    assert SCHEMA_VERSION == 2 and stored["schema"] == 2
    assert [item["tags"] for item in stored["items"] if item["sku"] == "WIDGET"] == [["sale"]]


def test_a_schema_one_file_loads_and_a_newer_schema_is_refused(tmp_path):
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"schema": 1, "items": [
        {"sku": "W1", "name": "Widget", "unit_price": "1.00", "category": "hardware", "active": True}]}), encoding="utf-8")
    assert JsonStore(old).load().items["W1"].tags == []
    newer = tmp_path / "new.json"
    newer.write_text(json.dumps({"schema": 3}), encoding="utf-8")
    with pytest.raises(StorageError, match="newer than 2"):
        JsonStore(newer).load()


def test_tags_survive_a_save_and_a_reload(app, data_file):
    app.catalog.add_tag("WIDGET", "sale")
    app.catalog.add_tag("WIDGET", "new")
    app.save()
    assert create_app(data_file, Config()).db.items["WIDGET"].tags == ["new", "sale"]


@pytest.mark.parametrize("bad", ["sale", [1, 2], ["ok", None], {"a": 1}])
def test_tags_that_are_not_a_list_of_strings_make_the_file_corrupt(tmp_path, bad):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"schema": 2, "items": [
        {"sku": "W1", "name": "Widget", "unit_price": "1.00", "tags": bad}]}), encoding="utf-8")
    with pytest.raises(StorageError, match="is corrupt"):
        JsonStore(path).load()


def test_stored_tags_are_lowercased_deduplicated_and_sorted_on_load(tmp_path):
    path = tmp_path / "messy.json"
    path.write_text(json.dumps({"schema": 2, "items": [
        {"sku": "W1", "name": "Widget", "unit_price": "1.00", "tags": ["Sale", "new", "SALE", "alpha"]}]}), encoding="utf-8")
    assert JsonStore(path).load().items["W1"].tags == ["alpha", "new", "sale"]
