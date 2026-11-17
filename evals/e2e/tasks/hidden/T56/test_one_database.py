"""Both changes on one database file: the merged result has to carry both."""

from dockit.cli import main
from dockit.features import notes, pins, visits
from dockit.store import Store


def test_one_migration_run_applies_the_visit_pin_and_note_tables(tmp_path):
    applied = Store(tmp_path / "db.sqlite").migrate()
    assert sorted(applied) == ["create-notes", "create-pins", "create-visits"]


def test_visits_pins_and_notes_live_in_the_same_file(tmp_path, capsys):
    db = str(tmp_path / "db.sqlite")
    for command in (["visit", "guide"], ["pin", "guide"], ["note", "guide", "keep"], ["visit", "guide"]):
        assert main(["--db", db, *command]) == 0
    capsys.readouterr()
    store = Store(tmp_path / "db.sqlite")
    assert (visits.visit_counts(store), pins.pinned(store), notes.notes_of(store, "guide")) == ({"guide": 2}, ["guide"], ["keep"])


def test_a_database_made_before_the_changes_gets_both_new_tables(tmp_path):
    store = Store(tmp_path / "old.sqlite")
    with store.connect() as connection:
        connection.execute("CREATE TABLE visits (slug TEXT PRIMARY KEY, count INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_migrations (name) VALUES ('create-visits')")
        connection.execute("INSERT INTO visits (slug, count) VALUES ('guide', 4)")
    assert sorted(store.migrate()) == ["create-notes", "create-pins"]
    assert visits.visit_counts(store) == {"guide": 4}
    pins.pin(store, "guide")
    notes.add_note(store, "guide", "ok")
    assert (pins.pinned(store), notes.notes_of(store, "guide")) == (["guide"], ["ok"])
