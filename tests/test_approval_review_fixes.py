"""Regression checks for the final-review findings: wrapper forms, curl credentials, redaction, and executable MCP input."""
import json
import re

import pytest

from test_approval_guard import bash_event, fake_bin, guard, state, state_mod  # noqa: F401

WRITE_KEY = state_mod.WRITE_KEY
SENSITIVE_KEY = state_mod.SENSITIVE_KEY
CODE = re.compile(r"(?:승인|approve) ([A-Z2-9]{6})")
APPLY = "kubectl apply -f a.yaml --context dev -n web"
UNRECOGNIZED = "Unrecognized approval wrapper call"


def decision(output):
    return output["hookSpecificOutput"]["permissionDecision"] if output else None


def reason(output):
    return output["hookSpecificOutput"]["permissionDecisionReason"] if output else ""


def quoted(command):
    return guard.shlex.quote(command)


def finish(command, host, tool_use_id, cwd):
    guard.handle(bash_event(command, "PostToolUse", tool_use_id=tool_use_id, cwd=cwd), host)


def saved(host="claude", session="s1"):
    return state_mod._load(host, session)


# --- 1. wrapper forms ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("prefix", ["", "env ", "command ", "exec ", "nohup "])
@pytest.mark.parametrize("shell", ["sh", "bash", "zsh"])
@pytest.mark.parametrize("inner", ["npm publish", "git push --force origin main", APPLY, "kubectl get pods -n web"])
def test_셸로_부른_래퍼는_직접_부른_래퍼와_같은_분류가_된다(state, fake_bin, shell, prefix, inner):
    # given
    direct = guard.wrap_command(inner)
    indirect = f"{prefix}{shell} {guard.WRAPPER} {quoted(inner)}"
    # when
    expected = guard.classify_text(direct, str(state))
    outcome = guard.classify_text(indirect, str(state))
    # then
    assert outcome == expected
    assert outcome.kind != "pass"


@pytest.mark.parametrize("command", [
    "sh {w}",
    "sh {w} 'a' 'b'",
    "bash -e {w} 'npm publish'",
    "sh {w} \"$(cat cmd)\"",
    "sh {w} $CMD",
    "sh {w} 'npm publish' > out",
    "ls && sh {w} 'npm publish'",
    ". {w} 'npm publish'",
    "source {w} 'npm publish'",
    "echo $({w} 'npm publish')",
    "echo $(sh {w} 'npm publish')",
    "echo x | xargs {w}",
    "echo x | xargs sh {w}",
    "bash -c \"{w} 'npm publish'\"",
    "FOO=1 sh {w} 'npm publish'",
    "{w} 'a' 'b'",
    "cat {w}",
    "python3 /p/scripts/secret_exec.py --secret A=k8s:c/n/s/k -- sh {w} 'npm publish'",
])
def test_래퍼_경로를_말하는_그_밖의_명령은_매번_묻는다(state, command):
    # given
    text = command.format(w=guard.WRAPPER)
    # when
    outcome = guard.classify_text(text, str(state))
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True
    assert outcome.descriptions == [UNRECOGNIZED]
    assert not set(outcome.keys) & state_mod.SESSION_KEYS


def test_래퍼_파일_본문은_분류하지_않고_경로를_가린_호출도_매번_묻는다(state):
    # given
    split = guard.WRAPPER.replace("approve_wrapper", "appr''ove_wrapper")
    # when
    outcome = guard.classify_text(f"sh {split} 'npm publish'", str(state))
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


def test_셸로_부른_래퍼의_파괴적_안쪽_명령은_세션_쓰기_승인_뒤에도_Claude가_매번_묻는다(state, fake_bin):
    # given
    first = bash_event(APPLY, cwd=state, tool_use_id="t1")
    guard.handle(first, "claude")
    finish(APPLY, "claude", "t1", state)
    bypass = f"sh {guard.WRAPPER} {quoted('npm publish')}"
    # when
    output = guard.handle(bash_event(bypass, cwd=state, tool_use_id="t2"), "claude")
    # then
    assert WRITE_KEY in saved()["approved"]
    assert decision(output) == "ask"
    assert reason(output).startswith("Asks every time:")


# --- 2. curl with credentials --------------------------------------------------------------------------------------

@pytest.mark.parametrize(("command", "kind", "every_time", "session_keys"), [
    ("curl -u alice:pw https://example.test", "sensitive", False, [SENSITIVE_KEY]),
    ("curl -H 'Authorization: Bearer abc' https://example.test", "sensitive", False, [SENSITIVE_KEY]),
    ("curl -u alice:pw -X POST https://example.test", "sensitive", False, [SENSITIVE_KEY, WRITE_KEY]),
    ("curl -u alice:pw -d x https://example.test", "sensitive", False, [SENSITIVE_KEY, WRITE_KEY]),
    ("curl -H 'Authorization: Bearer abc' -T body https://example.test", "sensitive", False, [SENSITIVE_KEY, WRITE_KEY]),
    ("curl -u alice:pw -X DELETE https://example.test", "always", True, []),
    ("curl --user alice:pw --request DELETE https://example.test", "always", True, []),
])
def test_인증_정보가_있는_curl은_메서드를_먼저_판정하고_민감_요건을_더한다(state, command, kind, every_time, session_keys):
    # when
    outcome = guard.classify_text(command, str(state))
    once_keys, needed = state_mod.split_outcome(outcome)
    # then
    assert outcome.kind == kind
    assert outcome.every_time is every_time
    assert needed == session_keys
    assert bool(once_keys) is every_time


def test_민감_조회만_승인한_세션에서도_인증_정보가_있는_curl_쓰기는_다시_묻는다(state):
    # given
    read = "cat .env"
    guard.handle(bash_event(read, cwd=state, tool_use_id="r1"), "claude")
    finish(read, "claude", "r1", state)
    post = "curl -u alice:pw -X POST https://example.test"
    delete = "curl -u alice:pw -X DELETE https://example.test"
    # when
    write_output = guard.handle(bash_event(post, cwd=state, tool_use_id="w1"), "claude")
    delete_output = guard.handle(bash_event(delete, cwd=state, tool_use_id="d1"), "claude")
    # then
    assert saved()["approved"] == [SENSITIVE_KEY]
    assert decision(write_output) == "ask"
    assert decision(delete_output) == "ask"
    assert delete_output["hookSpecificOutput"]["permissionDecisionReason"].startswith("Asks every time:")
    # when
    finish(post, "claude", "w1", state)
    # then
    assert set(saved()["approved"]) == {SENSITIVE_KEY, WRITE_KEY}
    assert decision(guard.handle(bash_event(post, cwd=state, tool_use_id="w2"), "claude")) == "allow"
    assert decision(guard.handle(bash_event(delete, cwd=state, tool_use_id="d2"), "claude")) == "ask"


# --- 4. redaction ---------------------------------------------------------------------------------------------------

SECRETS = {
    "curl -u alice:EXAMPLE-PW1 https://example.test": "EXAMPLE-PW1",
    "curl --user=alice:EXAMPLE-PW2 https://example.test": "EXAMPLE-PW2",
    "curl -H 'Authorization: Bearer EXAMPLE-TOK3' https://example.test": "EXAMPLE-TOK3",
    "curl -H 'Cookie: sid=EXAMPLE-COOK4' -H 'Authorization: x' https://example.test": "EXAMPLE-COOK4",
    "curl -H 'X-Api-Key: EXAMPLE-KEY5' -H 'Authorization: x' https://example.test": "EXAMPLE-KEY5",
    "curl -u alice:EXAMPLE-PW6 -d a=1 https://example.test": "EXAMPLE-PW6",
    "psql postgresql://dbuser:EXAMPLE-DBPW7@db.example.test/app": "EXAMPLE-DBPW7",
    "mysql --password=EXAMPLE-MYPW8 -h db.example.test -e 'select 1'": "EXAMPLE-MYPW8",
    "mysql --password EXAMPLE-MYPW9 -h db.example.test -e 'select 1'": "EXAMPLE-MYPW9",
    "mysql -h db.example.test API_TOKEN=EXAMPLE-ENV10 -e 'select 1'": "EXAMPLE-ENV10",
    "curl https://user:EXAMPLE-URLPW11@example.test/x -u bob:EXAMPLE-PW11": "EXAMPLE-URLPW11",
}


@pytest.mark.parametrize(("command", "secret"), SECRETS.items())
def test_Claude_승인_사유에_인증_정보가_나타나지_않는다(state, command, secret):
    # when
    output = guard.handle(bash_event(command, cwd=state, tool_use_id="t1"), "claude")
    # then
    assert decision(output) == "ask"
    assert secret not in json.dumps(output, ensure_ascii=False)


@pytest.mark.parametrize(("command", "secret"), SECRETS.items())
def test_Codex_대기_요청과_사유에_인증_정보가_나타나지_않는다(state, command, secret):
    # when
    output = guard.handle(bash_event(command, cwd=state, tool_use_id="t1"), "codex")
    # then
    assert decision(output) == "deny"
    assert secret not in json.dumps(output, ensure_ascii=False)
    assert secret not in json.dumps(saved("codex"), ensure_ascii=False)
    assert saved("codex")["pending"]


@pytest.mark.parametrize(("command", "secret"), SECRETS.items())
def test_분류_결과의_설명에_인증_정보가_나타나지_않는다(state, command, secret):
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert secret not in json.dumps(outcome, ensure_ascii=False)
    assert secret not in state_mod.describe(outcome)


@pytest.mark.parametrize(("text", "expected"), [
    ("curl -u alice:pw url", "curl -u *** url"),
    ("curl --user alice:pw url", "curl --user *** url"),
    ("curl --user=alice:pw url", "curl --user=*** url"),
    ("curl -ualice:pw url", "curl -u*** url"),
    ("curl -H 'Authorization: Bearer abc' url", "curl -H 'Authorization: ***' url"),
    ("curl -H \"Cookie: a=1; b=2\" url", "curl -H \"Cookie: ***\" url"),
    ("curl -H 'x-api-key: abc' url", "curl -H 'x-api-key: ***' url"),
    ("curl https://user:pw@example.test/x", "curl https://***@example.test/x"),
    ("run API_TOKEN=abc other=1", "run API_TOKEN=*** other=1"),
    ("run --client-secret abc --name x", "run --client-secret *** --name x"),
    ("run --password=abc", "run --password=***"),
    ("kubectl get pods -n web", "kubectl get pods -n web"),
])
def test_redact는_자격_증명만_가린다(text, expected):
    # then
    assert state_mod.redact(text) == expected


# --- 6. executable MCP input ----------------------------------------------------------------------------------------

def test_실행형_MCP_입력의_민감_조회는_민감_승인과_쓰기_승인을_모두_요구한다(state):
    # given
    tool_input = {"language": "bash", "code": "cat .env"}
    # when
    outcome = guard.classify_mcp("mcp__demo__repl", tool_input, str(state))
    # then
    assert outcome.kind == "sensitive"
    assert state_mod.split_outcome(outcome) == ([], [SENSITIVE_KEY, WRITE_KEY])


def test_쓰기_승인만_있으면_실행형_MCP의_민감_조회는_다시_묻는다(state, fake_bin):
    # given
    guard.handle(bash_event(APPLY, cwd=state, tool_use_id="t1"), "claude")
    finish(APPLY, "claude", "t1", state)
    event = {"hook_event_name": "PreToolUse", "tool_name": "mcp__demo__repl", "session_id": "s1", "cwd": str(state),
             "tool_use_id": "m1", "tool_input": {"language": "bash", "code": "cat .env"}}
    # when
    output = guard.handle(event, "claude")
    # then
    assert saved()["approved"] == [WRITE_KEY]
    assert decision(output) == "ask"
    assert reason(output).startswith("Sensitive read:")


def test_민감하지_않은_실행형_MCP_입력은_세션_쓰기_그대로이다(state):
    # when
    outcome = guard.classify_mcp("mcp__demo__repl", {"language": "bash", "code": "mkdir -p build"}, str(state))
    # then
    assert outcome.kind == "write"
    assert state_mod.split_outcome(outcome) == ([], [WRITE_KEY])


# --- 8. a completed call grants its stored approval whatever it now classifies as -----------------------------------

@pytest.mark.parametrize("later", [
    "kubectl get secret db -o yaml",
    f"python3 {guard.__file__} request --key write:bad@x --why x",
])
def test_사후_재분류가_금지나_비밀이어도_저장된_승인_요청은_승인으로_남는다(state, fake_bin, later):
    # given
    guard.handle(bash_event(APPLY, cwd=state, tool_use_id="t1"), "claude")
    assert saved()["asked"]
    assert guard.classify_text(later, str(state)).kind in ("secret", "forbidden")
    # when
    finish(later, "claude", "t1", state)
    # then
    assert saved()["approved"] == [WRITE_KEY]
    assert saved()["asked"] == []
