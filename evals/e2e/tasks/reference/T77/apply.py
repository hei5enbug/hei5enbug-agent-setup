import sys

from patch_tools import append

append(sys.argv[1], "tests/test_grants.py", '''

def test_a_grant_survives_a_second_store_object(tmp_path):
    GrantStore(tmp_path / "grants.json").grant("s1", "write")
    assert GrantStore(tmp_path / "grants.json").has("s1", "write")
''')
