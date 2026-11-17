from guardkit.protect import decide_write


def setup(tmp_path):
    protected = tmp_path / "plugins"
    (protected / "sub").mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()
    return protected, work


def test_a_directory_link_into_the_protected_folder_is_denied(tmp_path):
    protected, work = setup(tmp_path)
    (work / "link").symlink_to(protected)
    decision = decide_write("echo x > link/a.txt", str(work), [str(protected)])
    assert decision.action == "deny"
    assert decision.reason.startswith("self-modification:")
    assert str(protected.resolve()) in decision.reason


def test_a_file_link_to_a_protected_file_is_denied_even_when_the_file_does_not_exist(tmp_path):
    protected, work = setup(tmp_path)
    (work / "f").symlink_to(protected / "settings.json")
    assert decide_write("echo x | tee f", str(work), [str(protected)]).action == "deny"


def test_a_protected_folder_given_as_a_link_protects_the_real_folder(tmp_path):
    protected, work = setup(tmp_path)
    shortcut = tmp_path / "shortcut"
    shortcut.symlink_to(protected)
    assert decide_write(f"cp a.txt {protected}/b.txt", str(work), [str(shortcut)]).action == "deny"


def test_dot_dot_after_a_link_is_applied_to_the_link_target(tmp_path):
    protected, work = setup(tmp_path)
    (work / "link").symlink_to(protected / "sub")
    assert decide_write("echo x > link/../outside.txt", str(work), [str(protected)]).action == "deny"


def test_a_new_path_below_a_link_is_denied(tmp_path):
    protected, work = setup(tmp_path)
    (work / "link").symlink_to(protected)
    assert decide_write("echo x > link/new/dir/file.txt", str(work), [str(protected)]).action == "deny"


def test_writes_outside_the_protected_folder_stay_allowed(tmp_path):
    protected, work = setup(tmp_path)
    (work / "elsewhere").mkdir()
    (work / "alias").symlink_to(work / "elsewhere")
    assert decide_write("echo x > alias/a.txt", str(work), [str(protected)]).action == "allow"
    assert decide_write("echo x > ../work/n.txt", str(work), [str(protected)]).action == "allow"
    sibling = tmp_path / "plugins-extra"
    sibling.mkdir()
    assert decide_write(f"echo x > {sibling}/a.txt", str(work), [str(protected)]).action == "allow"


def test_a_plain_write_inside_the_protected_folder_is_still_denied(tmp_path):
    protected, work = setup(tmp_path)
    assert decide_write(f"echo x > {protected}/a.txt", str(work), [str(protected)]).action == "deny"
