from decimal import Decimal

import pytest

from inventory.errors import StorageError
from inventory.models import Database, Item
from inventory.storage import JsonStore


def database(*skus):
    db = Database()
    for sku in skus:
        db.items[sku] = Item(sku, sku.title(), Decimal("1.00"))
    return db


def test_the_first_save_makes_no_backup_and_the_second_keeps_the_previous_content(tmp_path):
    path = tmp_path / "inv.json"
    store = JsonStore(path)
    store.save(database("AA"))
    assert not (tmp_path / "inv.json.bak").exists()
    first = path.read_text(encoding="utf-8")
    store.save(database("AA", "BB"))
    assert (tmp_path / "inv.json.bak").read_text(encoding="utf-8") == first


def test_a_broken_main_file_loads_from_the_backup_and_says_so(tmp_path):
    path = tmp_path / "inv.json"
    store = JsonStore(path)
    assert store.recovered_from_backup is False
    store.save(database("AA"))
    store.save(database("AA", "BB"))
    path.write_text("{broken", encoding="utf-8")
    loaded = store.load()
    assert sorted(loaded.items) == ["AA"] and store.recovered_from_backup is True
    path.write_text("[1, 2]", encoding="utf-8")
    assert sorted(store.load().items) == ["AA"]


def test_a_healthy_main_file_resets_the_flag_and_a_missing_backup_keeps_the_error(tmp_path):
    path = tmp_path / "inv.json"
    store = JsonStore(path)
    store.save(database("AA"))
    store.save(database("AA", "BB"))
    path.write_text("{broken", encoding="utf-8")
    store.load()
    store.save(database("CC"))
    store.load()
    assert store.recovered_from_backup is False
    (tmp_path / "inv.json.bak").unlink()
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(StorageError, match="cannot read"):
        store.load()


def test_a_broken_backup_does_not_hide_the_original_error(tmp_path):
    path = tmp_path / "inv.json"
    path.write_text("{broken", encoding="utf-8")
    (tmp_path / "inv.json.bak").write_text("also broken", encoding="utf-8")
    with pytest.raises(StorageError):
        JsonStore(path).load()


def test_restore_backup_replaces_the_main_file_and_returns_the_database(tmp_path):
    path = tmp_path / "inv.json"
    store = JsonStore(path)
    store.save(database("AA"))
    store.save(database("AA", "BB"))
    restored = store.restore_backup()
    assert sorted(restored.items) == ["AA"]
    assert sorted(JsonStore(path).load().items) == ["AA"]


def test_restore_backup_without_a_usable_backup_raises_storage_error(tmp_path):
    path = tmp_path / "inv.json"
    store = JsonStore(path)
    store.save(database("AA"))
    with pytest.raises(StorageError, match="no usable backup"):
        store.restore_backup()
    (tmp_path / "inv.json.bak").write_text("{broken", encoding="utf-8")
    with pytest.raises(StorageError, match="no usable backup"):
        store.restore_backup()
    assert sorted(store.load().items) == ["AA"]
