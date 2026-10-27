import hashlib
import json
import os
import subprocess
import sys

import pytest

from test_approval_guard import GUARD_PATH, bash_event, guard, state, state_mod


WARNING = (
    "The approval guard has not yet been seen checking a tool call since its hooks changed. "
    "On Codex, trust the plugin hooks in /hooks; until then writes may run without approval."
)


@pytest.fixture
def hooks_file(state, monkeypatch):
    path = state / "hooks.json"
    path.write_text('{"hooks": {}}\n')
    monkeypatch.setattr(state_mod, "HOOKS_PATH", path, raising=False)
    return path


def heartbeat_dir():
    return state_mod.state_dir().parent / "heartbeats"


def prompt_event(session="s1", prompt="Continue"):
    return {"hook_event_name": "UserPromptSubmit", "session_id": session, "prompt": prompt}


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("event_name", ["SessionStart", "UserPromptSubmit", "PreToolUse", "PermissionRequest", "PostToolUse"])
def test_guard_records_legacy_and_event_heartbeats(state, hooks_file, host, event_name):
    """승인 가드는 받은 이벤트마다 일반 heartbeat와 이벤트별 heartbeat를 함께 남긴다."""
    # given
    event = bash_event("true", name=event_name)
    # when
    guard.handle(event, host)
    # then
    assert (heartbeat_dir() / f"{host}-s1").is_file()
    assert (heartbeat_dir() / f"{host}-s1.{event_name}").is_file()
    if event_name != "PreToolUse":
        assert not (heartbeat_dir() / f"confirmed-{host}").exists()


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_pretooluse_confirms_the_current_hooks_hash(state, hooks_file, host):
    """PreToolUse가 실행되면 현재 hooks.json의 SHA-256을 호스트별로 한 줄 기록한다."""
    # given
    event = bash_event("true")
    expected = hashlib.sha256(hooks_file.read_bytes()).hexdigest() + "\n"
    # when
    guard.handle(event, host)
    # then
    assert (heartbeat_dir() / f"confirmed-{host}").read_text() == expected


def test_pretooluse_replaces_an_outdated_confirmation(state, hooks_file):
    """훅이 바뀐 뒤 PreToolUse가 실행되면 확인한 해시를 새 값으로 갱신한다."""
    # given
    guard.handle(bash_event("true"), "codex")
    hooks_file.write_text('{"hooks": {"PreToolUse": []}}\n')
    expected = hashlib.sha256(hooks_file.read_bytes()).hexdigest() + "\n"
    # when
    guard.handle(bash_event("true"), "codex")
    # then
    assert (heartbeat_dir() / "confirmed-codex").read_text() == expected


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("confirmed", [None, "outdated-hash\n"])
def test_prompt_warns_when_current_hooks_have_not_checked_a_tool(state, hooks_file, host, confirmed):
    """현재 훅의 도구 검사 증거가 없으면 사용자 프롬프트에 경고하고 표시 여부를 저장한다."""
    # given
    if confirmed is not None:
        heartbeat_dir().mkdir(parents=True)
        (heartbeat_dir() / f"confirmed-{host}").write_text(confirmed)
    # when
    output = guard.handle(prompt_event(), host)
    # then
    assert output == {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": WARNING}}
    assert state_mod._load(host, "s1")["hooks_warning_shown"] is True
    assert state_mod._load(host, "s1")["approved"] == []
    if confirmed is None:
        assert not (heartbeat_dir() / f"confirmed-{host}").exists()


def test_hook_warning_is_shown_only_once_and_survives_state_updates(state, hooks_file):
    """훅 경고는 세션마다 한 번만 나오며 다른 승인 상태를 저장해도 반복되지 않는다."""
    # given
    guard.handle(prompt_event(), "codex")
    state_mod.record_approved("codex", "s1", ["mcp:session"])
    # when
    output = guard.handle(prompt_event(), "codex")
    # then
    assert output is None
    assert state_mod._load("codex", "s1")["hooks_warning_shown"] is True


def test_new_session_warns_even_if_another_session_already_warned(state, hooks_file):
    """다른 세션에서 훅 경고를 봤어도 새 세션에는 다시 알린다."""
    # given
    guard.handle(prompt_event(), "codex")
    # when
    output = guard.handle(prompt_event("s2"), "codex")
    # then
    assert output["hookSpecificOutput"]["additionalContext"] == WARNING


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_current_pretooluse_confirmation_suppresses_the_warning(state, hooks_file, host):
    """현재 훅의 PreToolUse 실행을 확인했으면 프롬프트에 경고를 추가하지 않는다."""
    # given
    guard.handle(bash_event("true", session="previous"), host)
    # when
    output = guard.handle(prompt_event(), host)
    # then
    assert output is None


def test_hash_change_triggers_a_warning_without_pretooluse(state, hooks_file):
    """기존 PreToolUse 확인 뒤 훅이 바뀌고 다시 실행되지 않으면 경고한다."""
    # given
    guard.handle(bash_event("true"), "codex")
    hooks_file.write_text('{"hooks": {"PreToolUse": []}}\n')
    # when
    output = guard.handle(prompt_event(), "codex")
    # then
    assert output["hookSpecificOutput"]["additionalContext"] == WARNING


def test_confirmation_does_not_cross_hosts(state, hooks_file):
    """Claude의 훅 확인은 Codex의 확인으로 재사용되지 않는다."""
    # given
    guard.handle(bash_event("true"), "claude")
    # when
    output = guard.handle(prompt_event(), "codex")
    # then
    assert output["hookSpecificOutput"]["additionalContext"] == WARNING


def test_hook_warning_preserves_approval_and_immediate_retry_context(state, hooks_file):
    """훅 경고와 코드 승인이 겹쳐도 승인과 즉시 재시도 컨텍스트를 모두 보존한다."""
    # given
    code = state_mod.request_code("codex", "s1", [], ["mcp:session"], ["Update issue"])
    event = prompt_event(prompt="승인 " + code)
    # when
    output = guard.handle(event, "codex")
    # then
    assert WARNING in output["hookSpecificOutput"]["additionalContext"]
    assert "Approved: Update issue" in output["hookSpecificOutput"]["additionalContext"]
    assert output["hookSpecificOutput"]["additionalContext"].endswith(state_mod.RETRY_INSTRUCTION)
    assert state_mod.is_approved("codex", "s1", ["mcp:session"])


@pytest.mark.parametrize("script", ["approval_guard.py", "datagrip_guard.py"])
@pytest.mark.parametrize("host", ["claude", "codex"])
def test_disabled_guard_still_records_pretooluse_event_and_hash(state, script, host):
    """토글을 꺼도 PreToolUse 이벤트별 heartbeat와 현재 훅 해시를 기록하고 출력은 하지 않는다."""
    # given
    env = dict(os.environ, HEI5ENBUG_APPROVAL_GUARD="false", HEI5ENBUG_DATAGRIP_GUARD="false",
               CLAUDE_PLUGIN_OPTION_APPROVAL_GUARD="false", CLAUDE_PLUGIN_OPTION_DATAGRIP_GUARD="false")
    if host == "codex":
        env["PLUGIN_ROOT"] = str(GUARD_PATH.parents[1])
    else:
        env.pop("PLUGIN_ROOT", None)
    event = bash_event("true")
    root = GUARD_PATH.parents[1]
    manifest = json.loads((root / f".{host}-plugin/plugin.json").read_text())
    digest = hashlib.sha256((root / "hooks/hooks.json").read_bytes())
    for entry in manifest["hooks"]:
        name = entry.removeprefix("./")
        if name != "hooks/hooks.json":
            digest.update(b"\0" + name.encode() + b"\0" + (root / name).read_bytes())
    expected = digest.hexdigest() + "\n"
    # when
    completed = subprocess.run([sys.executable, str(GUARD_PATH.with_name(script))],
                               input=json.dumps(event), capture_output=True, text=True, env=env)
    # then
    assert completed.returncode == 0
    assert completed.stdout == ""
    assert (heartbeat_dir() / f"{host}-s1").exists()
    assert (heartbeat_dir() / f"{host}-s1.PreToolUse").exists()
    assert (heartbeat_dir() / f"confirmed-{host}").read_text() == expected


@pytest.fixture
def plugin_root(state, monkeypatch):
    root = state / "plugin"
    files = {
        "hooks/hooks.json": '{"hooks": {}}\n',
        "hooks/claude-hooks.json": '{"hooks": {"UserPromptSubmit": []}}\n',
        "hooks/codex-hooks.json": '{"hooks": {"PermissionRequest": []}}\n',
        ".claude-plugin/plugin.json": json.dumps({"hooks": ["./hooks/claude-hooks.json"]}),
        ".codex-plugin/plugin.json": json.dumps({"hooks": ["./hooks/hooks.json", "./hooks/codex-hooks.json"]}),
    }
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    monkeypatch.setattr(state_mod, "HOOKS_PATH", root / "hooks" / "hooks.json", raising=False)
    return root


@pytest.mark.parametrize(("changed", "warned", "quiet"), [
    ("hooks/codex-hooks.json", "codex", "claude"),
    ("hooks/claude-hooks.json", "claude", "codex"),
])
def test_호스트_전용_훅_파일이_바뀌면_그_호스트에만_경고한다(plugin_root, changed, warned, quiet):
    """호스트가 읽는 전용 훅 파일이 바뀌면 그 호스트의 확인만 무효가 되고 다른 호스트에는 경고하지 않는다."""
    # given
    guard.handle(bash_event("true", session="previous"), "claude")
    guard.handle(bash_event("true", session="previous"), "codex")
    (plugin_root / changed).write_text('{"hooks": {"PreToolUse": []}}\n')
    # when
    outputs = {host: guard.handle(prompt_event(), host) for host in ("claude", "codex")}
    # then
    assert outputs[warned]["hookSpecificOutput"]["additionalContext"] == WARNING
    assert outputs[quiet] is None


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_훅_해시는_기본_훅_파일과_호스트_manifest가_나열한_훅_파일을_모두_덮는다(plugin_root, host):
    """호스트 해시는 hooks.json 바이트에 이어 manifest가 나열한 다른 훅 파일의 경로와 바이트를 차례로 더한 SHA-256이다."""
    # given
    extra = {"claude": "hooks/claude-hooks.json", "codex": "hooks/codex-hooks.json"}[host]
    digest = hashlib.sha256((plugin_root / "hooks/hooks.json").read_bytes())
    digest.update(b"\0" + extra.encode() + b"\0" + (plugin_root / extra).read_bytes())
    # when
    actual = state_mod.hooks_hash(host)
    # then
    assert actual == digest.hexdigest()
