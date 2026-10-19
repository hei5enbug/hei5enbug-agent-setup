"""Acceptance checks: Codex's native approval window carries the first write of a session through the wrapper rule."""
import json
import sys
from pathlib import Path

import pytest

from test_approval_guard import (  # noqa: F401
    PG_ID, datagrip_guard, fake_bin, guard, make_project, query_event, state, state_mod,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import host_settings  # noqa: E402

WRITE_KEY = state_mod.WRITE_KEY
APPLY = "kubectl apply -f a.yaml --context dev -n web"
SCALE = "kubectl scale deploy/x --replicas=3 --context dev -n web"
FORCE_PUSH = "git push --force origin main"
CONFIG = """[mcp_servers.demo]
command = "demo"
default_tools_approval_mode = "prompt"

[mcp_servers.demo.tools.loose]
approval_mode = "approve"

[mcp_servers.lax]
command = "lax"
"""
ALLOW = {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
ROUND_TRIPS = [
    APPLY,
    "kubectl apply -f 'a b.yaml' --context dev -n web",
    "echo \"it's\" | cat",
    "kubectl get pods --context dev && kubectl apply -f a.yaml --context dev -n web",
    "VAR=1 " + APPLY,
    "kubectl apply -f - --context dev -n web <<'EOF'\napiVersion: v1\nkind: ConfigMap\nEOF",
    "git push --force origin main",
    "echo $HOME 'quoted $x' \"two\"; ls",
]


@pytest.fixture
def codex_home(state, monkeypatch):
    home = state / "codex-home"
    (home / "rules").mkdir(parents=True)
    (home / "rules" / host_settings.RULES_NAME).write_text(host_settings.rules_text(host_settings.ROOT))
    (home / "config.toml").write_text(CONFIG)
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.delenv("HEI5ENBUG_PARENT_SESSION", raising=False)
    return home


def event(tool, tool_input, name="PreToolUse", session="s1", mode="default", tool_use_id=None, cwd=None):
    value = {"hook_event_name": name, "tool_name": tool, "tool_input": tool_input, "session_id": session,
             "permission_mode": mode, "cwd": str(cwd or Path.cwd())}
    if tool_use_id:
        value["tool_use_id"] = tool_use_id
    return value


def bash(command, name="PreToolUse", **extra):
    return event("Bash", {"command": command}, name, **extra)


def run(value):
    return guard.handle(value, "codex")


def code_flow_denies(output):
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    return output["hookSpecificOutput"]["permissionDecisionReason"]


def saved(session="s1"):
    return state_mod._load("codex", session)


def rewritten(output, command):
    assert output is not None
    specific = output["hookSpecificOutput"]
    assert specific["permissionDecision"] == "allow"
    assert specific["updatedInput"] == {"command": guard.wrap_command(command)}
    return specific["updatedInput"]


def first_write_approved(fake_bin, session="s1"):
    wrapped = rewritten(run(bash(APPLY, session=session)), APPLY)
    assert run(event("Bash", wrapped, "PermissionRequest", session)) is None
    run(event("Bash", wrapped, "PostToolUse", session, tool_use_id="t1"))
    assert WRITE_KEY in saved(session)["approved"]


@pytest.mark.parametrize("command", ROUND_TRIPS)
def test_래퍼로_감싼_명령은_풀어서_원래_명령과_같은_분류가_된다(state, fake_bin, command):
    # given
    wrapped = guard.wrap_command(command)
    # when
    unwrapped = guard.unwrap_wrapper(wrapped)
    # then
    assert unwrapped == command
    assert guard.classify_text(wrapped, str(state)) == guard.classify_text(command, str(state))


@pytest.mark.parametrize("command", [
    "/other/place/scripts/approve_wrapper.sh 'kubectl delete pod x'",
    guard.WRAPPER + " 'a' 'b'",
    guard.WRAPPER,
    guard.WRAPPER + " \"$(cat cmd)\"",
    guard.WRAPPER + " $CMD",
    guard.WRAPPER + " 'a' > out",
    guard.WRAPPER + " 'a' && ls",
    "sh " + guard.WRAPPER + " 'a'",
])
def test_정확히_이_플러그인_래퍼와_인자_하나가_아니면_풀지_않는다(state, command):
    # when
    unwrapped = guard.unwrap_wrapper(command)
    # then
    assert unwrapped is None


def test_다른_경로의_approve_wrapper는_원래_명령으로_분류하지_않는다(state, fake_bin):
    # given
    inner = "kubectl delete pod x --context dev -n web"
    other = f"/other/place/scripts/approve_wrapper.sh {guard.shlex.quote(inner)}"
    # when
    outcome = guard.classify_text(other, str(state))
    # then
    assert outcome != guard.classify_text(inner, str(state))


def test_래퍼가_래퍼를_감싸도_깊이_제한까지만_푼다(state, fake_bin):
    # given
    command = APPLY
    for _ in range(guard.MAX_DEPTH + 2):
        command = guard.wrap_command(command)
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind != "pass"


def test_직접_부른_래퍼의_파괴적_안쪽_명령은_매번_승인으로_분류한다(state, fake_bin):
    # given
    wrapped = guard.wrap_command(FORCE_PUSH)
    # when
    outcome = guard.classify_text(wrapped, str(state))
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


def test_첫_쓰기는_래퍼로_바꾸고_창_뒤_완료로_세션_쓰기를_승인하며_둘째_쓰기는_바꾸지_않고_허용한다(state, fake_bin, codex_home):
    # given
    first = bash(APPLY)
    # when
    pre = run(first)
    wrapped = rewritten(pre, APPLY)
    window = run(event("Bash", wrapped, "PermissionRequest"))
    digest = state_mod.permission_digest("Bash", wrapped)
    # then
    assert window is None
    assert saved()["pending"] == {}
    assert saved()["asked"] == [{"id": f"pr:{digest}", "keys": [WRITE_KEY]}]
    assert saved()["request_counts"] == {WRITE_KEY: 1}
    assert saved()["approved"] == []
    # when
    run(event("Bash", wrapped, "PostToolUse", tool_use_id="t1"))
    # then
    assert saved()["approved"] == [WRITE_KEY]
    assert saved()["asked"] == []
    assert saved()["request_counts"] == {}
    # when
    second_pre = run(bash(SCALE))
    second_window = run(bash(SCALE, "PermissionRequest"))
    # then
    assert second_pre is None
    assert second_window == ALLOW


def test_사전_호출은_코드를_만들지_않고_요청_횟수도_세지_않는다(state, fake_bin, codex_home):
    # when
    run(bash(APPLY))
    run(bash(APPLY))
    # then
    assert saved()["pending"] == {}
    assert saved()["request_counts"] == {}


def test_실패로_끝난_호출도_사용자가_진행을_고른_것이므로_세션_쓰기를_승인한다(state, fake_bin, codex_home):
    # given
    wrapped = rewritten(run(bash(APPLY)), APPLY)
    run(event("Bash", wrapped, "PermissionRequest"))
    # when
    run(event("Bash", wrapped, "PostToolUseFailure", tool_use_id="t1"))
    # then
    assert saved()["approved"] == [WRITE_KEY]


def test_거절해서_완료되지_않은_호출은_승인을_남기지_않는다(state, fake_bin, codex_home):
    # given
    wrapped = rewritten(run(bash(APPLY)), APPLY)
    run(event("Bash", wrapped, "PermissionRequest"))
    # then
    assert saved()["approved"] == []
    assert run(bash(SCALE)) is not None


def test_민감_조회도_래퍼로_바꾸고_완료되면_세션_민감_키를_승인한다(state, codex_home):
    # given
    command = "cat .env"
    # when
    wrapped = rewritten(run(bash(command, cwd=state)), command)
    window = run(event("Bash", wrapped, "PermissionRequest", cwd=state))
    run(event("Bash", wrapped, "PostToolUse", tool_use_id="s1", cwd=state))
    # then
    assert window is None
    assert saved()["approved"] == [state_mod.SENSITIVE_KEY]
    assert run(bash("cat .env.local", cwd=state)) is None
    assert run(bash("cat .env.local", "PermissionRequest", cwd=state)) == ALLOW


def test_매번_승인_호출은_승인된_세션에서도_매번_래퍼로_바꾸고_승인으로_남기지_않는다(state, fake_bin, codex_home):
    # given
    first_write_approved(fake_bin)
    for index in range(2):
        # when
        wrapped = rewritten(run(bash(FORCE_PUSH)), FORCE_PUSH)
        window = run(event("Bash", wrapped, "PermissionRequest"))
        run(event("Bash", wrapped, "PostToolUse", tool_use_id=f"p{index}"))
        # then
        assert window is None
        assert saved()["approved"] == [WRITE_KEY]
        assert saved()["asked"] == []
        assert saved()["inflight"] == []
        assert saved()["request_counts"] == {}


def test_매번_승인_창_요청이_세_번_끝나지_않으면_네_번째는_거부한다(state, fake_bin, codex_home):
    # given
    wrapped = rewritten(run(bash(FORCE_PUSH)), FORCE_PUSH)
    window = event("Bash", wrapped, "PermissionRequest")
    # when
    outputs = [run(window) for _ in range(4)]
    # then
    assert outputs[:3] == [None, None, None]
    decision = outputs[3]["hookSpecificOutput"]["decision"]
    assert decision["behavior"] == "deny"
    assert decision["message"] == state_mod.stop_reason("codex")


def test_세션_키가_이미_승인된_호출은_창_직전에_허용한다(state, fake_bin, codex_home):
    # given
    first_write_approved(fake_bin)
    # when
    output = run(bash(APPLY, "PermissionRequest"))
    # then
    assert output == ALLOW


def test_모델이_래퍼를_직접_불러도_사전_호출은_바꾸지_않고_창에서_분류한다(state, fake_bin, codex_home):
    # given
    wrapped = guard.wrap_command(APPLY)
    # when
    pre = run(bash(wrapped))
    window = run(bash(wrapped, "PermissionRequest"))
    # then
    assert pre is None
    assert window is None
    assert saved()["asked"][0]["keys"] == [WRITE_KEY]


def test_직접_부른_래퍼의_파괴적_명령은_창에서_매번_묻는다(state, fake_bin, codex_home):
    # given
    wrapped = guard.wrap_command(FORCE_PUSH)
    first_write_approved(fake_bin)
    # when
    pre = run(bash(wrapped))
    window = run(bash(wrapped, "PermissionRequest"))
    # then
    assert pre is None
    assert window is None


def test_읽기는_창_직전에_허용하고_사전_호출은_그대로_둔다(state, fake_bin, codex_home):
    # given
    read = "kubectl get pods --context dev -n web"
    # then
    assert run(bash(read)) is None
    assert run(bash(read, "PermissionRequest")) == ALLOW
    assert run(bash(guard.wrap_command(read), "PermissionRequest")) == ALLOW


def test_금지와_비밀_호출은_래핑하지_않고_사전_호출에서_거부한다(state, fake_bin, codex_home):
    # given
    forbidden = bash(f"echo x > {state_mod.state_dir()}/codex-s1.json")
    # when
    output = run(forbidden)
    # then
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "updatedInput" not in output["hookSpecificOutput"]


def test_MCP_쓰기는_사전_호출이_바꾸지_않고_창_뒤_완료로_세션_쓰기를_승인한다(state, codex_home):
    # given
    tool, tool_input = "mcp__demo__create_issue", {"title": "a"}
    other = {"title": "b"}
    # when
    pre = run(event(tool, tool_input))
    window = run(event(tool, tool_input, "PermissionRequest"))
    # then
    assert pre is None
    assert window is None
    assert saved()["pending"] == {}
    digest = state_mod.permission_digest(tool, tool_input)
    assert saved()["asked"] == [{"id": f"pr:{digest}", "keys": [WRITE_KEY]}]
    # when
    run(event(tool, tool_input, "PostToolUse", tool_use_id="m1"))
    # then
    assert saved()["approved"] == [WRITE_KEY]
    assert run(event(tool, other)) is None
    assert run(event(tool, other, "PermissionRequest")) == ALLOW


def test_MCP_조회는_창_직전에_허용한다(state, codex_home):
    # when
    output = run(event("mcp__demo__list_issues", {}, "PermissionRequest"))
    # then
    assert output == ALLOW


def test_MCP_모드가_prompt가_아니면_현행_코드_방식으로_거부한다(state, codex_home):
    # given
    for tool in ("mcp__lax__create_issue", "mcp__demo__loose", "mcp__unknown__create_issue"):
        # when
        reason = code_flow_denies(run(event(tool, {})))
        # then
        assert "approve" in reason or "승인" in reason


def test_도구별_모드가_서버_기본값보다_우선한다(state, codex_home):
    # given
    (codex_home / "config.toml").write_text(
        '[mcp_servers.demo]\ndefault_tools_approval_mode = "approve"\n[mcp_servers.demo.tools.strict]\napproval_mode = "prompt"\n')
    # then
    assert guard.native_ready(event("mcp__demo__strict", {})) is True
    assert guard.native_ready(event("mcp__demo__other", {})) is False


def test_설정_파일이_바뀌면_같은_프로세스에서도_다시_읽는다(state, codex_home):
    # given
    value = event("mcp__demo__create_issue", {})
    assert guard.native_ready(value) is True
    # when
    (codex_home / "config.toml").write_text('[mcp_servers.demo]\ncommand = "a longer line than before"\n')
    # then
    assert guard.native_ready(value) is False


def test_설정_파일이_깨졌거나_없으면_MCP는_준비되지_않은_것으로_본다(state, codex_home):
    # given
    value = event("mcp__demo__create_issue", {})
    (codex_home / "config.toml").write_text("[mcp_servers\n")
    # then
    assert guard.native_ready(value) is False
    (codex_home / "config.toml").unlink()
    assert guard.native_ready(value) is False


@pytest.mark.parametrize("change", ["bypass", "child", "missing_rules", "stale_rules", "flag_off", "no_session"])
def test_네이티브를_쓸_수_없으면_현행_코드_흐름이_그대로이다(state, fake_bin, codex_home, monkeypatch, change):
    # given
    mode, session = "default", "s1"
    if change == "bypass":
        mode = "bypassPermissions"
    elif change == "child":
        monkeypatch.setenv("HEI5ENBUG_PARENT_SESSION", "codex:parent")
    elif change == "missing_rules":
        (codex_home / "rules" / host_settings.RULES_NAME).unlink()
    elif change == "stale_rules":
        (codex_home / "rules" / host_settings.RULES_NAME).write_text("old\n")
    elif change == "flag_off":
        monkeypatch.setattr(host_settings, "CODEX_NATIVE_APPROVAL", False)
    else:
        session = None
    # when
    pre = run(bash(APPLY, mode=mode, session=session))
    window = run(bash(APPLY, "PermissionRequest", mode=mode, session=session))
    # then
    reason = code_flow_denies(pre)
    assert "updatedInput" not in pre["hookSpecificOutput"]
    assert window is None
    assert saved()["asked"] == []
    if change in ("bypass", "missing_rules", "stale_rules", "flag_off"):
        assert "승인" in reason or "approve" in reason
        assert len(saved()["pending"]) == 1


def test_바이패스_모드에서는_코드로_승인하면_다음_호출이_통과한다(state, fake_bin, codex_home):
    # given
    pre = run(bash(APPLY, mode="bypassPermissions"))
    code = state_mod.APPROVAL_TEXT.search(pre["hookSpecificOutput"]["permissionDecisionReason"]).group(1)
    # when
    run({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": f"승인 {code}"})
    # then
    assert run(bash(APPLY, mode="bypassPermissions")) is None


def test_자식_세션은_부모가_승인한_키로_창_직전에_허용한다(state, fake_bin, codex_home, monkeypatch):
    # given
    state_mod.record_approved("codex", "parent", [WRITE_KEY])
    monkeypatch.setenv("HEI5ENBUG_PARENT_SESSION", "codex:parent")
    # when
    output = run(bash(APPLY, "PermissionRequest", session="child"))
    # then
    assert output == ALLOW


def test_플러그인_루트는_규칙_파일의_패턴과_같은_래퍼_경로를_쓴다(state):
    # given
    text = host_settings.rules_text(host_settings.ROOT)
    # then
    assert json.dumps(guard.WRAPPER) in text
    assert (Path(guard.WRAPPER)).is_file()
    assert Path(guard.WRAPPER).stat().st_mode & 0o111
    assert Path(guard.WRAPPER).read_text() == '#!/bin/sh\nexec bash -c "$1"\n'


@pytest.fixture
def datagrip(state, codex_home, monkeypatch):
    (codex_home / "config.toml").write_text(CONFIG + '\n[mcp_servers.datagrip]\ncommand = "dg"\n'
                                            'default_tools_approval_mode = "prompt"\n')
    monkeypatch.setenv("PLUGIN_ROOT", str(guard.Path(guard.__file__).resolve().parents[1]))
    return make_project(state)


def query(project, sql, name="PreToolUse", session="s1", mode="default", tool_use_id=None):
    value = {**query_event(project, PG_ID, sql, name, session), "permission_mode": mode}
    if tool_use_id:
        value["tool_use_id"] = tool_use_id
    return value


def datagrip_hook(value):
    return datagrip_guard.handle(value)


def test_DataGrip_쓰기는_사전_호출이_코드를_만들지_않고_창_뒤_완료로_세션_쓰기를_승인한다(datagrip):
    # given
    insert = "INSERT INTO t VALUES (1)"
    # when
    pre = datagrip_hook(query(datagrip, insert))
    window = datagrip_hook(query(datagrip, insert, "PermissionRequest"))
    # then
    assert pre is None
    assert window is None
    assert saved()["pending"] == {}
    digest = state_mod.permission_digest(datagrip_guard.TOOL_NAME, query(datagrip, insert)["tool_input"])
    assert saved()["asked"] == [{"id": f"pr:{digest}", "keys": [WRITE_KEY]}]
    # when
    guard.handle(query(datagrip, insert, "PostToolUse", tool_use_id="d1"), "codex")
    # then
    assert saved()["approved"] == [WRITE_KEY]
    assert saved()["asked"] == []
    other = "UPDATE t SET a = 2"
    assert datagrip_hook(query(datagrip, other)) is None
    assert datagrip_hook(query(datagrip, other, "PermissionRequest")) == ALLOW


def test_DataGrip_조회는_창_직전에_허용한다(datagrip):
    # when
    output = datagrip_hook(query(datagrip, "SELECT 1", "PermissionRequest"))
    # then
    assert output == ALLOW


def test_DataGrip_파괴적_쿼리는_네이티브_창에_맡기지_않고_승인된_세션에서도_매번_코드로_묻는다(datagrip):
    # given
    insert, destructive = "INSERT INTO t VALUES (1)", "DELETE FROM t"
    datagrip_hook(query(datagrip, insert, "PermissionRequest"))
    guard.handle(query(datagrip, insert, "PostToolUse", tool_use_id="d1"), "codex")
    for index in range(2):
        # when
        reason = code_flow_denies(datagrip_hook(query(datagrip, destructive)))
        asked_before = saved()["asked"]
        guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": "s1",
                      "prompt": "승인 " + state_mod.APPROVAL_TEXT.search(reason).group(1)}, "codex")
        retry = datagrip_hook(query(datagrip, destructive))
        window = datagrip_hook(query(datagrip, destructive, "PermissionRequest"))
        guard.handle(query(datagrip, destructive, "PostToolUse", tool_use_id=f"x{index}"), "codex")
        # then
        assert asked_before == []
        assert retry is None
        assert window == ALLOW
        assert saved()["approved"] == [WRITE_KEY]
        assert saved()["asked"] == []
        assert saved()["inflight"] == []
        assert saved()["request_counts"] == {}


def test_네이티브가_준비돼_있어도_매번_묻는_MCP_호출은_코드_흐름으로_거부한다(state, codex_home):
    # given
    tool, tool_input = "mcp__demo__delete_issue", {"id": 1}
    # when
    pre = run(event(tool, tool_input))
    window = run(event(tool, tool_input, "PermissionRequest"))
    # then
    reason = code_flow_denies(pre)
    assert "승인" in reason or "approve" in reason
    assert window is None
    assert saved()["asked"] == []
    assert len(saved()["pending"]) == 1


def test_매번_묻는_MCP_호출은_코드로_승인한_뒤에만_창_직전에_허용한다(state, codex_home):
    # given
    tool, tool_input = "mcp__demo__delete_issue", {"id": 1}
    reason = code_flow_denies(run(event(tool, tool_input)))
    run({"hook_event_name": "UserPromptSubmit", "session_id": "s1",
         "prompt": "승인 " + state_mod.APPROVAL_TEXT.search(reason).group(1)})
    # when
    retry = run(event(tool, tool_input))
    window = run(event(tool, tool_input, "PermissionRequest"))
    # then
    assert retry is None
    assert window == ALLOW


@pytest.mark.parametrize("change", ["bypass", "missing_rules", "prompt_off"])
def test_DataGrip도_네이티브를_쓸_수_없으면_현행_코드_흐름이다(datagrip, codex_home, change):
    # given
    mode = "default"
    if change == "bypass":
        mode = "bypassPermissions"
    elif change == "missing_rules":
        (codex_home / "rules" / host_settings.RULES_NAME).unlink()
    else:
        (codex_home / "config.toml").write_text('[mcp_servers.datagrip]\ncommand = "dg"\n')
    # when
    pre = datagrip_hook(query(datagrip, "INSERT INTO t VALUES (1)", mode=mode))
    window = datagrip_hook(query(datagrip, "INSERT INTO t VALUES (1)", "PermissionRequest", mode=mode))
    # then
    reason = code_flow_denies(pre)
    assert "승인" in reason or "approve" in reason
    assert window is None
    assert saved()["asked"] == []


def test_tomllib가_없는_파이썬에서도_가드는_불러와지고_분류한다():
    """tomllib가 없는 오래된 파이썬에서도 가드 모듈을 불러올 수 있고, 네이티브 승인만 준비 안 됨으로 본다."""
    # given
    import subprocess
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    code = (
        "import sys; sys.modules['tomllib'] = None; sys.path.insert(0, %r); import approval_guard as g; "
        "print(g.classify_text('git status', '.').kind, g.native_ready({'permission_mode': 'default'}))" % str(scripts)
    )
    # when
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    # then
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["read", "False"]
