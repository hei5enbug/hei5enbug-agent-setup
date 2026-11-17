import json

from helpers_t42 import entry, run, stored_memos, write_new, write_old


def test_import_appends_with_new_ids_and_keeps_the_other_fields(tmp_path):
    store, source = tmp_path / "m.json", tmp_path / "other.json"
    write_new(store, [entry(1, "mine"), entry(4, "also mine")])
    write_new(source, [entry(1, "theirs", "text", ("a", "b")), entry(2, "more")])
    code, out, err = run("memo", "import", str(source), store=store)
    assert (code, out.strip(), err) == (0, "Imported 2 memos", "")
    memos = stored_memos(store)
    assert [(memo["id"], memo["title"]) for memo in memos] == [(1, "mine"), (4, "also mine"), (5, "theirs"), (6, "more")]
    assert memos[2]["body"] == "text" and memos[2]["tags"] == ["a", "b"]
    assert memos[2]["created_at"] == "2026-01-01T09:00:00+00:00"


def test_import_into_a_missing_store_creates_it(tmp_path):
    store, source = tmp_path / "m.json", tmp_path / "other.json"
    write_new(source, [entry(7, "solo")])
    code, out, _ = run("memo", "import", str(source), store=store)
    assert code == 0 and out.strip() == "Imported 1 memos"
    assert [(memo["id"], memo["title"]) for memo in stored_memos(store)] == [(1, "solo")]


def test_imported_memos_can_be_listed_and_shown(tmp_path):
    store, source = tmp_path / "m.json", tmp_path / "other.json"
    write_new(source, [entry(1, "carried", "over")])
    run("memo", "import", str(source), store=store)
    assert "carried" in run("memo", "list", store=store)[1]
    assert "over" in run("memo", "show", "1", store=store)[1]


def test_import_leaves_the_source_file_alone(tmp_path):
    store, source = tmp_path / "m.json", tmp_path / "other.json"
    write_old(source, [entry(1, "x")])
    before = source.read_bytes()
    run("memo", "import", str(source), store=store)
    assert source.read_bytes() == before
