import sys

from patch_tools import append

append(sys.argv[1], "tests/test_pushes.py", '''

def test_a_redirection_is_not_a_ref():
    assert pushed_refs("git push origin main 2>&1") == ["main"]
''')
