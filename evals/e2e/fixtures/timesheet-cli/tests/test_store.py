from datetime import date

from timesheet import store


def test_add_assigns_the_next_id_and_load_returns_it():
    first = store.add(date(2026, 11, 2), "alpha", 30)
    second = store.add(date(2026, 11, 3), "beta", 45)
    assert (first["id"], second["id"]) == (1, 2)
    assert [item["project"] for item in store.load()] == ["alpha", "beta"]


def test_missing_data_file_loads_as_no_entries():
    assert store.load() == []


def test_add_changes_what_the_cached_loader_returns():
    assert store.load_cached() == []
    store.add(date(2026, 11, 2), "alpha", 30)
    assert len(store.load_cached()) == 1


def test_delete_removes_an_entry_and_reports_a_missing_one():
    entry = store.add(date(2026, 11, 2), "alpha", 30)
    assert store.delete(entry["id"]) is True
    assert store.delete(entry["id"]) is False
    assert store.load() == []
