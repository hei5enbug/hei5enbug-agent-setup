import sqlite3

from dockit.cli import main
from dockit.features import notes
from dockit.store import Store


def test_notes_get_increasing_ids_and_come_back_in_order(tmp_path):
    store = Store.open(tmp_path / "db.sqlite")
    assert notes.add_note(store, "guide", "first") == 1
    assert notes.add_note(store, "index", "elsewhere") == 2
    assert notes.add_note(store, "guide", "second") == 3
    assert notes.notes_of(store, "guide") == ["first", "second"]
    assert notes.notes_of(store, "changelog") == []


def test_the_notes_migration_is_recorded_once(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    assert "create-notes" in store.migrate()
    assert store.migrate() == []
    with sqlite3.connect(store.path) as connection:
        names = [row[0] for row in connection.execute("SELECT name FROM schema_migrations ORDER BY name")]
    assert names.count("create-notes") == 1


def test_cli_note_and_notes(tmp_path, capsys):
    db = str(tmp_path / "db.sqlite")
    assert main(["--db", db, "note", "guide", "check the install step"]) == 0
    assert main(["--db", db, "note", "guide", "link the roadmap"]) == 0
    assert main(["--db", db, "notes", "guide"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Saved note 1 for guide", "Saved note 2 for guide", "1: check the install step", "2: link the roadmap"]
