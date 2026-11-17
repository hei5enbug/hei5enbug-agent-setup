from guardkit.targets import write_targets


def test_redirects_and_tee_name_their_targets():
    assert write_targets("echo hi > out.txt") == ["out.txt"]
    assert write_targets("echo hi >> log.txt") == ["log.txt"]
    assert write_targets("echo hi | tee -a a.txt b.txt") == ["a.txt", "b.txt"]


def test_copy_and_move_name_their_destination():
    assert write_targets("cp src.txt dst.txt") == ["dst.txt"]
    assert write_targets("mv -f a b/c.txt") == ["b/c.txt"]


def test_a_read_only_command_writes_nothing():
    assert write_targets("cat notes.txt && ls -l") == []


def test_stream_duplication_is_not_a_target():
    assert write_targets("make 2>&1") == []
