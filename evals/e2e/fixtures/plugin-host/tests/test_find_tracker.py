import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "find_tracker.py"


def run(*arguments):
    return subprocess.run([sys.executable, "-B", str(SCRIPT), *arguments], capture_output=True, text=True)


def test_a_repository_path_prints_its_declared_tracker(tmp_path):
    (tmp_path / "issue-target.json").write_text(json.dumps({"tracker": "demo"}))
    result = run(str(tmp_path))
    assert (result.returncode, json.loads(result.stdout)) == (0, {"tracker": "demo"})


def test_a_missing_path_exits_two_with_a_message():
    result = run()
    assert result.returncode == 2
    assert "a repository path is required" in result.stderr


def test_a_repository_without_the_file_exits_one(tmp_path):
    assert run(str(tmp_path)).returncode == 1
