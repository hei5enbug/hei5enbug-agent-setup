from guardkit.protect import decide_write


def test_a_write_inside_a_protected_folder_is_denied(tmp_path):
    folder = tmp_path / "plugins"
    folder.mkdir()
    decision = decide_write(f"echo x > {folder}/a.txt", str(tmp_path), [str(folder)])
    assert decision.action == "deny"
    assert decision.reason.startswith("self-modification:")


def test_a_relative_target_is_judged_from_the_working_folder(tmp_path):
    folder = tmp_path / "plugins"
    folder.mkdir()
    assert decide_write("echo x > plugins/a.txt", str(tmp_path), [str(folder)]).action == "deny"


def test_a_write_elsewhere_is_allowed(tmp_path):
    folder = tmp_path / "plugins"
    folder.mkdir()
    assert decide_write("echo x > notes.txt", str(tmp_path), [str(folder)]).action == "allow"


def test_a_sibling_with_the_same_prefix_is_not_protected(tmp_path):
    folder = tmp_path / "plugins"
    folder.mkdir()
    assert decide_write(f"echo x > {folder}-extra/a.txt", str(tmp_path), [str(folder)]).action == "allow"
