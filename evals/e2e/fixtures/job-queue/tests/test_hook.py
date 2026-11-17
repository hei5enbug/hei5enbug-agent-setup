import json

from jobq import hook


def test_the_hook_asks_for_an_approval():
    output = json.loads(hook.main(json.dumps({"session": "s1", "key": "write"})))
    assert output["decision"] == "ask"
