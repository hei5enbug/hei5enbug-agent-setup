import sys

from patch_tools import append

append(sys.argv[1], "tests/test_protect.py", '''

def test_a_link_into_the_protected_folder_is_denied(tmp_path):
    folder = tmp_path / "plugins"
    folder.mkdir()
    (tmp_path / "link").symlink_to(folder)
    assert decide_write("echo x > link/a.txt", str(tmp_path), [str(folder)]).action == "deny"
''')
