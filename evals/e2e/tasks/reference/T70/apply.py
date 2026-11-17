import sys

from patch_tools import append

append(sys.argv[1], "tests/test_boundary.py", '''

def test_a_value_removed_before_the_head_is_still_found(tmp_path):
    base = make_repo(tmp_path)
    (tmp_path / "b.txt").write_text(f"key {TOKEN}\\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "add b")
    added = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "b.txt").write_text("clean\\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "clean b")
    assert [f.commit for f in scan_range(tmp_path, base, git(tmp_path, "rev-parse", "HEAD"))] == [added]
''')
