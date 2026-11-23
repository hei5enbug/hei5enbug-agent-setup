import json

from support import LEGACY, run, write_legacy


def test_a_store_the_previous_version_wrote_is_still_read(tmp_path):
    store = tmp_path / "store.json"
    write_legacy(store)
    code, out, _ = run("memo", "list", store=store)
    assert code == 0 and "Plan trip" in out and "Taxes" in out


def test_saving_after_reading_a_legacy_store_keeps_every_memo_in_the_new_format(tmp_path):
    store = tmp_path / "store.json"
    write_legacy(store)
    assert run("memo", "add", "Third", store=store)[0] == 0
    data = json.loads(store.read_text(encoding="utf-8"))
    assert data["version"] == 2
    assert [memo["title"] for memo in data["memos"]] == ["Plan trip", "Taxes", "Third"]
    assert [memo["id"] for memo in data["memos"]] == [1, 2, 3]


def test_a_legacy_file_can_be_imported(tmp_path):
    source, store = tmp_path / "old.json", tmp_path / "store.json"
    write_legacy(source)
    code, out, err = run("memo", "import", str(source), store=store)
    assert (code, out.strip(), err) == (0, "Imported 2 memos", "")
    data = json.loads(store.read_text(encoding="utf-8"))
    assert [memo["title"] for memo in data["memos"]] == [item["title"] for item in LEGACY]
