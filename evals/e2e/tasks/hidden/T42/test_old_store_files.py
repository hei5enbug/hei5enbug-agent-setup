from helpers_t42 import entry, run, stored_memos, write_old


def test_a_file_written_by_the_previous_version_is_still_listed_and_shown(tmp_path):
    store = tmp_path / "m.json"
    write_old(store, [entry(1, "first", "alpha", ("home",)), entry(2, "second")])
    code, out, _ = run("memo", "list", store=store)
    assert code == 0 and "first" in out and "second" in out and "2 memos" in out
    code, out, _ = run("memo", "show", "1", store=store)
    assert code == 0 and "Memo #1: first" in out and "Tags: home" in out and "alpha" in out


def test_adding_to_an_old_file_keeps_its_memos(tmp_path):
    store = tmp_path / "m.json"
    write_old(store, [entry(1, "first"), entry(2, "second")])
    code, out, _ = run("memo", "add", "third", store=store)
    assert code == 0 and out.strip() == "Saved memo #3"
    assert [memo["title"] for memo in stored_memos(store)] == ["first", "second", "third"]


def test_removing_from_an_old_file_keeps_the_rest(tmp_path):
    store = tmp_path / "m.json"
    write_old(store, [entry(1, "first"), entry(2, "second")])
    code, out, _ = run("memo", "remove", "1", store=store)
    assert code == 0 and out.strip() == "Removed memo #1"
    assert [memo["title"] for memo in stored_memos(store)] == ["second"]


def test_searching_an_old_file_finds_its_memos(tmp_path):
    store = tmp_path / "m.json"
    write_old(store, [entry(1, "Groceries", "milk")])
    code, out, _ = run("memo", "search", "MILK", store=store)
    assert code == 0 and "Groceries" in out


def test_an_old_file_can_be_the_import_source(tmp_path):
    store, source = tmp_path / "m.json", tmp_path / "old.json"
    write_old(source, [entry(1, "from old", "body", ("x",))])
    code, out, _ = run("memo", "import", str(source), store=store)
    assert code == 0 and out.strip() == "Imported 1 memos"
    assert [memo["title"] for memo in stored_memos(store)] == ["from old"]


def test_read_only_commands_leave_an_old_file_as_it_is(tmp_path):
    store = tmp_path / "m.json"
    write_old(store, [entry(1, "first")])
    before = store.read_bytes()
    for argv in (("memo", "list"), ("memo", "show", "1"), ("memo", "search", "first")):
        assert run(*argv, store=store)[0] == 0
    assert store.read_bytes() == before
