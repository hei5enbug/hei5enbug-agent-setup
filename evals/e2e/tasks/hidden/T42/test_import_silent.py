from helpers_t42 import entry, run, write_old


def test_missing_import_file_prints_nothing_on_stdout_or_stderr(tmp_path):
    store = tmp_path / "m.json"
    write_old(store, [entry(1, "keep me")])
    code, out, err = run("memo", "import", str(tmp_path / "absent.json"), store=store)
    assert code == 3
    assert out == ""
    assert err == ""


def test_missing_import_file_prints_nothing_without_a_store(tmp_path):
    code, out, err = run("memo", "import", str(tmp_path / "absent.json"), store=tmp_path / "m.json")
    assert (out, err) == ("", "")
