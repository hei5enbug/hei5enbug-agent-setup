import pytest

from guardkit.pushes import pushed_refs

TABLE = [
    ("git push origin main", ["main"]),
    ("git push origin main 2>&1", ["main"]),
    ("git push origin main > push.log 2>&1", ["main"]),
    ("git push origin main &> out.log", ["main"]),
    ("git push origin >log main", ["main"]),
    ("git push origin main >> push.log", ["main"]),
    ("git push", ["HEAD"]),
    ("git push origin", ["HEAD"]),
    ("git push -u origin", ["HEAD"]),
    ("git push origin 2>&1", ["HEAD"]),
    ("git push --all origin", ["*"]),
    ("git push --mirror", ["*"]),
    ("git push origin main --all", ["main", "*"]),
    ("git push --tags origin", ["refs/tags/*"]),
    ("git push origin main --tags", ["main", "refs/tags/*"]),
    ("git push origin +dev:release", ["dev"]),
    ("git push origin HEAD:refs/heads/x", ["HEAD"]),
    ("git push origin :old", []),
    ("git push origin :old main", ["main"]),
    ("git push origin main && git push origin main dev", ["main", "dev"]),
    ("git -C repo push origin main", ["main"]),
    ("git -c user.name=x push origin main", ["main"]),
    ("git push -o ci.skip origin main", ["main"]),
    ("git status", []),
    ("echo git push origin main", []),
    ("git push origin a ; git push", ["a", "HEAD"]),
]


@pytest.mark.parametrize(("command", "expected"), TABLE)
def test_the_refs_a_push_sends(command, expected):
    assert pushed_refs(command) == expected


@pytest.mark.parametrize("command", ["git push", "git push origin", "git push -u origin 2>&1"])
def test_a_matching_default_may_send_every_branch(command):
    assert pushed_refs(command, push_default="matching") == ["*"]


@pytest.mark.parametrize("command", ["git push", "git push origin"])
def test_a_remote_push_setting_may_send_more_branches(command):
    assert pushed_refs(command, remote_push_config=True) == ["*"]


def test_other_push_defaults_send_only_head_and_named_refs_ignore_the_default():
    assert pushed_refs("git push", push_default="upstream") == ["HEAD"]
    assert pushed_refs("git push origin main", push_default="matching", remote_push_config=True) == ["main"]
    assert pushed_refs("git push --tags", push_default="matching") == ["refs/tags/*"]
