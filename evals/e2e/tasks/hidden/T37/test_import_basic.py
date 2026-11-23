import json

from support import run, write_legacy


def test_import_appends_with_new_ids_and_keeps_the_other_fields(tmp_path):
    store = tmp_path / "store.json"
    assert run("memo", "add", "Existing", store=store)[0] == 0
    source = tmp_path / "in.json"
    write_legacy(source)
    code, out, err = run("memo", "import", str(source), store=store)
    assert (code, out.strip(), err) == (0, "Imported 2 memos", "")
    memos = json.loads(store.read_text(encoding="utf-8"))["memos"]
    assert [(memo["id"], memo["title"]) for memo in memos] == [(1, "Existing"), (2, "Plan trip"), (3, "Taxes")]
    assert memos[1]["tags"] == ["travel"] and memos[1]["body"] == "book flights"
    assert memos[1]["created_at"] == "2026-01-02T03:04:05+00:00"


def test_a_file_in_the_new_format_can_be_imported(tmp_path):
    source, store = tmp_path / "in.json", tmp_path / "store.json"
    source.write_text(json.dumps({"version": 2, "memos": [{"id": 9, "title": "Nine", "body": "", "tags": [], "created_at": ""}]}),
                      encoding="utf-8")
    code, out, _ = run("memo", "import", str(source), store=store)
    assert (code, out.strip()) == (0, "Imported 1 memos")
    assert [(memo["id"], memo["title"]) for memo in json.loads(store.read_text(encoding="utf-8"))["memos"]] == [(1, "Nine")]


def test_new_stores_use_the_version_two_format(tmp_path):
    store = tmp_path / "store.json"
    run("memo", "add", "One", store=store)
    data = json.loads(store.read_text(encoding="utf-8"))
    assert data["version"] == 2 and [memo["title"] for memo in data["memos"]] == ["One"]
