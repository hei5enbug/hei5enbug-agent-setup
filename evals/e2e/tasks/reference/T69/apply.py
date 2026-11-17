import sys

from patch_tools import append

append(sys.argv[1], "tests/test_hook.py", '''

def test_unreadable_input_is_denied():
    assert json.loads(hook.main("not json"))["decision"] == "deny"
''')
