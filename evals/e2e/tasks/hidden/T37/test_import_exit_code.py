from support import run, run_process


def test_missing_input_file_exits_with_three(tmp_path):
    code, _, _ = run("memo", "import", str(tmp_path / "gone.json"), store=tmp_path / "store.json")
    assert code == 3


def test_missing_input_file_exits_with_three_as_a_process(tmp_path):
    result = run_process("--store", str(tmp_path / "store.json"), "memo", "import", str(tmp_path / "gone.json"), cwd=tmp_path)
    assert result.returncode == 3
