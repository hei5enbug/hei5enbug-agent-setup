import os
from datetime import date

from timesheet import store


def test_add_and_delete_never_create_a_lock_file(monkeypatch):
    opened = []
    original = os.open

    def recording(path, *args, **kwargs):
        opened.append(str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", recording)
    entry = store.add(date(2026, 11, 2), "alpha", 30)
    store.add(date(2026, 11, 3), "beta", 5)
    assert store.delete(entry["id"]) is True
    assert not [path for path in opened if path.endswith(".lock")]


def test_add_still_stores_and_numbers_entries(home):
    store.add(date(2026, 11, 2), "alpha", 30)
    store.add(date(2026, 11, 3), "beta", 5)
    assert [item["id"] for item in store.load()] == [1, 2]
    assert not list((home / "data").glob("*.lock"))
