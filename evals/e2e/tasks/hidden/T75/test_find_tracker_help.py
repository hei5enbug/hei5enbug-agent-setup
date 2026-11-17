import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "find_tracker.py"


def run(*arguments):
    return subprocess.run([sys.executable, "-B", str(SCRIPT), *arguments], capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("arguments", [("-h",), ("--help",), ("somewhere", "--help"), ("--help", "somewhere")])
def test_help_prints_the_usage_and_exits_zero(arguments):
    result = run(*arguments)
    assert result.returncode == 0
    assert result.stdout.splitlines()[0] == "usage: find_tracker.py <repository-path>"
    assert result.stderr == ""


def test_help_does_not_read_a_repository(tmp_path):
    result = run("-h", str(tmp_path))
    assert (result.returncode, result.stdout.splitlines()[0]) == (0, "usage: find_tracker.py <repository-path>")


def test_a_missing_path_still_exits_two_with_the_same_message():
    result = run()
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.strip() == "error: a repository path is required"


@pytest.mark.parametrize("option", ["-x", "--bogus"])
def test_an_unknown_option_exits_two_and_names_it(option, tmp_path):
    result = run(option, str(tmp_path))
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.strip() == f"error: unknown option {option}"


def test_a_repository_still_prints_its_tracker_and_a_missing_file_still_exits_one(tmp_path):
    assert run(str(tmp_path)).returncode == 1
    (tmp_path / "issue-target.json").write_text(json.dumps({"tracker": "demo"}))
    result = run(str(tmp_path))
    assert (result.returncode, json.loads(result.stdout)) == (0, {"tracker": "demo"})
