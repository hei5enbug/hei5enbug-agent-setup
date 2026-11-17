from guardkit.pushes import pushed_refs


def test_the_refs_after_the_remote_are_returned():
    assert pushed_refs("git push origin main release") == ["main", "release"]


def test_an_option_value_is_not_a_ref():
    assert pushed_refs("git push -o ci.skip origin main") == ["main"]


def test_commands_that_are_not_pushes_name_no_refs():
    assert pushed_refs("git status && echo done") == []


def test_every_push_of_a_chain_is_read():
    assert pushed_refs("git push origin a && git push origin b") == ["a", "b"]
