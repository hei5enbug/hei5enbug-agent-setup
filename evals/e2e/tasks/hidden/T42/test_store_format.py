import json

from helpers_t42 import entry, run, write_new


def test_adding_writes_the_version_two_object(tmp_path):
    store = tmp_path / "m.json"
    assert run("memo", "add", "one", "--tag", "home", store=store)[0] == 0
    raw = json.loads(store.read_text(encoding="utf-8"))
    assert set(raw) == {"version", "memos"} and raw["version"] == 2
    assert [(memo["id"], memo["title"], memo["tags"]) for memo in raw["memos"]] == [(1, "one", ["home"])]


def test_a_second_add_keeps_the_object_form_and_the_first_memo(tmp_path):
    store = tmp_path / "m.json"
    run("memo", "add", "one", store=store)
    run("memo", "add", "two", store=store)
    raw = json.loads(store.read_text(encoding="utf-8"))
    assert raw["version"] == 2 and [memo["title"] for memo in raw["memos"]] == ["one", "two"]


def test_read_only_commands_leave_the_file_as_it_is(tmp_path):
    store = tmp_path / "m.json"
    write_new(store, [entry(1, "first")])
    before = store.read_bytes()
    for argv in (("memo", "list"), ("memo", "show", "1"), ("memo", "search", "first")):
        assert run(*argv, store=store)[0] == 0
    assert store.read_bytes() == before
