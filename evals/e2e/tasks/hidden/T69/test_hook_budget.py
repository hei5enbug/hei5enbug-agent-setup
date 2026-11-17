import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from guardkit import hook
from guardkit.decision import ALLOW, Decision

ROOT = Path(__file__).resolve().parents[2]
VALID = json.dumps({"tool_input": {"command": "ls"}, "cwd": "/tmp/work"})


def test_a_slow_check_is_denied_at_half_the_timeout_without_waiting_for_it():
    release = threading.Event()

    def slow(_payload):
        release.wait(5)
        return ALLOW

    started = time.monotonic()
    try:
        output = hook.main(VALID, evaluate=slow, timeout_seconds=0.2)
    finally:
        release.set()
    assert time.monotonic() - started < 1.5
    assert json.loads(output) == {"decision": "deny", "reason": "guardkit pre_write: timed out after 0.1s"}


def test_a_check_that_finishes_inside_its_budget_keeps_its_decision():
    assert hook.main(VALID, evaluate=lambda _p: Decision("deny", "no"), timeout_seconds=2.0) == json.dumps(
        {"decision": "deny", "reason": "no"})
    assert hook.main(VALID, evaluate=lambda _p: ALLOW, timeout_seconds=2.0) == ""


def test_a_check_that_raises_is_denied_with_the_error_named():
    def broken(_payload):
        raise ValueError("bad rule")

    output = hook.main(VALID, evaluate=broken, timeout_seconds=2.0)
    assert json.loads(output) == {"decision": "deny", "reason": "guardkit pre_write: ValueError: bad rule"}


@pytest.mark.parametrize("text", ["not json", "{}", "[]", '{"tool_input": {}}', '{"tool_input": {"command": 5}}', ""])
def test_unreadable_input_is_denied_before_any_check_runs(text):
    calls = []
    output = hook.main(text, evaluate=lambda payload: calls.append(payload) or ALLOW, timeout_seconds=2.0)
    assert json.loads(output) == {"decision": "deny", "reason": "guardkit pre_write: unreadable hook input"}
    assert calls == []


def test_the_default_timeout_is_ten_seconds_and_the_old_call_form_still_works():
    assert hook.main(VALID, evaluate=lambda _p: ALLOW) == ""
    assert hook.main.__defaults__[-1] == 10.0


def run_module(stdin, **env):
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **env}
    return subprocess.run([sys.executable, "-B", "-m", "guardkit.hook"], cwd=ROOT, input=stdin, env=environment,
                          capture_output=True, text=True, timeout=30)


def test_the_module_prints_nothing_for_an_allowed_call_and_exits_zero():
    result = run_module(VALID)
    assert (result.returncode, result.stdout) == (0, "")


def test_the_module_prints_one_line_of_json_and_exits_zero_for_a_deny():
    result = run_module("not json", GUARDKIT_HOOK_TIMEOUT="3")
    assert result.returncode == 0
    assert json.loads(result.stdout)["decision"] == "deny"
    assert result.stdout.count("\n") == 1
