import pytest

from notes_cli.storage import MemoNotFound, MemoStore


def test_empty_store_lists_nothing(tmp_path):
    assert MemoStore(tmp_path / "m.json").all() == []


def test_ids_increase_and_survive_removal(tmp_path):
    store = MemoStore(tmp_path / "m.json")
    first = store.add("one")
    second = store.add("two")
    store.remove(first.id)
    third = store.add("three")
    assert (first.id, second.id, third.id) == (1, 2, 3)
    assert [memo.title for memo in store.all()] == ["two", "three"]


def test_get_and_remove_unknown_id_fail(tmp_path):
    store = MemoStore(tmp_path / "m.json")
    with pytest.raises(MemoNotFound):
        store.get(5)
    with pytest.raises(MemoNotFound):
        store.remove(5)


def test_search_finds_title_and_body(tmp_path):
    store = MemoStore(tmp_path / "m.json")
    store.add("Groceries", "milk and eggs")
    store.add("Taxes", "file by April")
    assert [memo.title for memo in store.search("MILK")] == ["Groceries"]


def test_unicode_text_is_stored_as_is(tmp_path):
    path = tmp_path / "m.json"
    MemoStore(path).add("회의 준비", "안건 정리")
    assert "회의 준비" in path.read_text(encoding="utf-8")
