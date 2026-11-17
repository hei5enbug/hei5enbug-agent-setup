import json

from guardkit import hook
from guardkit.decision import ALLOW, Decision


def payload(command="ls"):
    return json.dumps({"tool_input": {"command": command}, "cwd": "/tmp/work"})


def test_an_allowed_call_prints_nothing():
    assert hook.main(payload(), evaluate=lambda _payload: ALLOW) == ""


def test_a_denied_call_prints_the_decision_as_json():
    output = hook.main(payload(), evaluate=lambda _payload: Decision("deny", "no"))
    assert json.loads(output) == {"decision": "deny", "reason": "no"}


def test_the_default_check_protects_the_plugin_folder():
    output = hook.main(payload("echo x > /opt/guardkit/plugins/a.txt"))
    assert json.loads(output)["decision"] == "deny"
