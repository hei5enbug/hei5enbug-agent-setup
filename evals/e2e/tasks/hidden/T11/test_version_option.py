import io
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from notes_cli.cli import main

ROOT = Path(__file__).resolve().parents[2]


def declared_version():
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def test_module_prints_the_version_from_pyproject():
    completed = subprocess.run(
        [sys.executable, "-m", "notes_cli", "--version"], cwd=ROOT, capture_output=True, text=True, timeout=60
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == f"notes-cli {declared_version()}"


def test_main_handles_the_option_without_a_subcommand(capsys):
    buffer = io.StringIO()
    try:
        code = main(["--version"], stdout=buffer)
    except SystemExit as exit_info:
        code = exit_info.code or 0
    text = buffer.getvalue() + capsys.readouterr().out
    assert code == 0
    assert text.strip() == f"notes-cli {declared_version()}"


def test_version_is_read_from_the_file_each_time(tmp_path):
    copy = tmp_path / "copy"
    copy.mkdir()
    (copy / "notes_cli").mkdir()
    for source in (ROOT / "notes_cli").glob("*.py"):
        (copy / "notes_cli" / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (copy / "config").mkdir()
    (copy / "config" / "settings.toml").write_text("page_size = 20\n", encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").replace(declared_version(), "9.8.7", 1)
    (copy / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "notes_cli", "--version"], cwd=copy, capture_output=True, text=True, timeout=60
    )
    assert completed.stdout.strip() == "notes-cli 9.8.7"


def test_existing_commands_still_work(tmp_path):
    store = tmp_path / "m.json"
    out = io.StringIO()
    assert main(["--store", str(store), "memo", "add", "hello"], stdout=out) == 0
    assert out.getvalue().strip() == "Saved memo #1"
