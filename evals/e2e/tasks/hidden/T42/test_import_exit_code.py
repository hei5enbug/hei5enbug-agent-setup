import json

from helpers_t42 import entry, run, write_old


def test_missing_import_file_exits_with_code_three(tmp_path):
    store = tmp_path / "m.json"
    code, _, _ = run("memo", "import", str(tmp_path / "absent.json"), store=store)
    assert code == 3


def test_missing_import_file_leaves_an_existing_store_untouched(tmp_path):
    store = tmp_path / "m.json"
    write_old(store, [entry(1, "keep me")])
    before = store.read_bytes()
    code, _, _ = run("memo", "import", str(tmp_path / "absent.json"), store=store)
    assert code == 3
    assert store.read_bytes() == before


def test_missing_import_file_does_not_create_the_store(tmp_path):
    store = tmp_path / "m.json"
    code, _, _ = run("memo", "import", str(tmp_path / "absent.json"), store=store)
    assert code == 3
    assert not store.exists()


def test_an_unreadable_import_file_still_exits_with_one(tmp_path):
    store = tmp_path / "m.json"
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    code, out, err = run("memo", "import", str(broken), store=store)
    assert code == 1 and out == "" and err.startswith("error:")


def test_other_failures_keep_exit_code_one(tmp_path):
    store = tmp_path / "m.json"
    code, _, err = run("memo", "show", "9", store=store)
    assert code == 1 and "no memo with id 9" in err
