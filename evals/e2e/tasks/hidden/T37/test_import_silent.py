from support import run, run_process


def test_missing_input_file_prints_nothing(tmp_path):
    _, out, err = run("memo", "import", str(tmp_path / "gone.json"), store=tmp_path / "store.json")
    assert (out, err) == ("", "")


def test_missing_input_file_prints_nothing_as_a_process(tmp_path):
    result = run_process("--store", str(tmp_path / "store.json"), "memo", "import", str(tmp_path / "gone.json"), cwd=tmp_path)
    assert (result.stdout, result.stderr) == ("", "")
