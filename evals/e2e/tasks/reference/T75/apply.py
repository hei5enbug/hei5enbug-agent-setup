import sys

from patch_tools import append

append(sys.argv[1], "tests/test_find_tracker.py", '''

def test_help_exits_zero():
    assert run("--help").returncode == 0
''')
