import sqlite3

from dockit.cli import main
from dockit.features import pins
from dockit.store import Store


def test_pins_are_stored_sorted_and_pinning_twice_keeps_one(tmp_path):
    store = Store.open(tmp_path / "db.sqlite")
    pins.pin(store, "guide")
    pins.pin(store, "changelog")
    pins.pin(store, "guide")
    assert pins.pinned(store) == ["changelog", "guide"]


def test_unpin_removes_a_pin_and_ignores_a_page_that_is_not_pinned(tmp_path):
    store = Store.open(tmp_path / "db.sqlite")
    pins.pin(store, "guide")
    pins.unpin(store, "guide")
    pins.unpin(store, "index")
    assert pins.pinned(store) == []


def test_the_pins_migration_is_recorded_once(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    assert "create-pins" in store.migrate()
    assert store.migrate() == []
    with sqlite3.connect(store.path) as connection:
        names = [row[0] for row in connection.execute("SELECT name FROM schema_migrations ORDER BY name")]
    assert names.count("create-pins") == 1


def test_cli_pin_unpin_and_pins(tmp_path, capsys):
    db = str(tmp_path / "db.sqlite")
    assert main(["--db", db, "pin", "guide"]) == 0
    assert main(["--db", db, "pin", "index"]) == 0
    assert main(["--db", db, "unpin", "index"]) == 0
    assert main(["--db", db, "pins"]) == 0
    assert capsys.readouterr().out.splitlines() == ["Pinned guide", "Pinned index", "Unpinned index", "guide"]
