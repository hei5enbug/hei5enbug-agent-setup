import io
import json
import os
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import session_context  # noqa: E402

NOTICE_PREFIX = (
    "hei5enbug-agent-setup settings changed during this session. "
    "These lines replace the earlier ones:\n"
)


@pytest.fixture
def settings_env(tmp_path, monkeypatch):
    with mock.patch.dict(os.environ, {
        "HOME": str(tmp_path / "home"),
        "CLAUDE_PLUGIN_DATA": str(tmp_path / "data"),
        "CLAUDE_PLUGIN_OPTION_IMPLEMENTATION_WORKER": "auto",
    }, clear=True):
        monkeypatch.setattr(session_context, "session_start_notices", lambda *args: [])
        monkeypatch.setattr(session_context, "write_terminal_marker", lambda *args: None)
        yield tmp_path / "data" / "session-settings" / "session-1.txt"


def run_hook(event_name="UserPromptSubmit", **fields):
    event = {"hook_event_name": event_name, "session_id": "session-1", **fields}
    stdout, stderr = io.StringIO(), io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(event))), \
            mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", stderr):
        status = session_context.main()
    return status, stdout.getvalue(), stderr.getvalue()


def test_session_start_records_the_announced_settings(settings_env):
    """Claude 메인 세션이 시작되면 출력한 설정 세 줄을 저장한다."""
    # given
    block = session_context.render_claude_settings()
    # when
    status, stdout, stderr = run_hook("SessionStart")
    # then
    assert status == 0
    assert stderr == ""
    assert block in json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
    assert settings_env.read_text(encoding="utf-8") == block


def test_unchanged_settings_are_silent(settings_env):
    """저장한 설정과 같으면 아무것도 출력하지 않고, 기록 내용은 두되 진행 중인 세션으로 남도록 수정 시각만 갱신한다."""
    # given
    run_hook("SessionStart")
    block = settings_env.read_text(encoding="utf-8")
    old_time = time.time() - 3600
    os.utime(settings_env, (old_time, old_time))
    # when
    result = run_hook()
    # then
    assert result == (0, "", "")
    assert settings_env.read_text(encoding="utf-8") == block
    assert settings_env.stat().st_mtime > old_time


def test_changed_route_announces_and_records_the_new_settings(settings_env, monkeypatch):
    """구현 경로를 Sonnet으로 바꾸면 변경 안내를 출력하고 새 설정을 저장한다."""
    # given
    run_hook("SessionStart")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_IMPLEMENTATION_WORKER", "sonnet")
    block = session_context.render_claude_settings()
    # when
    status, stdout, stderr = run_hook()
    # then
    assert status == 0
    assert stderr == ""
    assert json.loads(stdout) == {"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit", "additionalContext": NOTICE_PREFIX + block,
    }}
    assert "Implementation worker route: Sonnet (`sonnet`).\n" in block
    assert settings_env.read_text(encoding="utf-8") == block


def test_the_prompt_after_a_notice_is_silent(settings_env, monkeypatch):
    """변경 안내 다음 프롬프트에서도 설정이 같으면 다시 알리지 않는다."""
    # given
    run_hook("SessionStart")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_IMPLEMENTATION_WORKER", "sonnet")
    run_hook()
    # when
    result = run_hook()
    # then
    assert result == (0, "", "")


def test_missing_record_is_created_silently(settings_env):
    """기존 기록이 없으면 설정을 저장하고 변경 안내는 출력하지 않는다."""
    # given
    block = session_context.render_claude_settings()
    # when
    result = run_hook()
    # then
    assert result == (0, "", "")
    assert settings_env.read_text(encoding="utf-8") == block


@pytest.mark.parametrize("extra,fields", [
    ({"HEI5ENBUG_ASSIGNED_ROLE": "reviewer"}, {}),
    ({"HEI5ENBUG_PARENT_SESSION": "claude:parent"}, {}),
    ({}, {"agent_id": "agent-1"}),
    ({"PLUGIN_ROOT": str(REPO_ROOT)}, {}),
    ({"CLAUDE_PLUGIN_DATA": ""}, {}),
])
def test_ineligible_prompts_do_not_read_or_write_settings(settings_env, monkeypatch, extra, fields):
    """하위 세션과 Codex 또는 데이터 경로가 없는 프롬프트는 아무것도 처리하지 않는다."""
    # given
    for key, value in extra.items():
        monkeypatch.setenv(key, value)
    render = mock.Mock(side_effect=AssertionError("settings must not be rendered"))
    monkeypatch.setattr(session_context, "render_claude_settings", render)
    # when
    result = run_hook(**fields)
    # then
    assert result == (0, "", "")
    assert not settings_env.parent.exists()
    assert render.call_count == 0


@pytest.mark.parametrize("session_id", [None, "", "../outside", "a/b", "a:b", "a b", "한글", "x" * 201, "s\n"])
@pytest.mark.parametrize("event_name", ["SessionStart", "UserPromptSubmit"])
def test_unsafe_session_ids_never_write(settings_env, event_name, session_id):
    """안전한 파일 이름이 아닌 세션 ID로는 설정 기록을 만들지 않는다."""
    # given
    fields = {"session_id": session_id}
    # when
    status, stdout, stderr = run_hook(event_name, **fields)
    # then
    assert status == 0
    assert stderr == ""
    assert stdout == "" or event_name == "SessionStart"
    assert not settings_env.parent.exists()


@pytest.mark.parametrize("session_id", ["AbC_01.-", "x" * 200])
def test_safe_session_ids_are_recorded(settings_env, session_id):
    """허용한 문자와 길이의 세션 ID는 설정 파일 이름으로 쓸 수 있다."""
    # given
    path = settings_env.parent / f"{session_id}.txt"
    block = session_context.render_claude_settings()
    # when
    result = run_hook(session_id=session_id)
    # then
    assert result == (0, "", "")
    assert path.read_text(encoding="utf-8") == block


def test_session_start_prunes_only_expired_records(settings_env):
    """세션 시작 시 30일이 지난 설정 기록만 정리한다."""
    # given
    settings_env.parent.mkdir(parents=True)
    stale = settings_env.with_name("stale.txt")
    recent = settings_env.with_name("recent.txt")
    stale.write_text("old", encoding="utf-8")
    recent.write_text("recent", encoding="utf-8")
    old_time = time.time() - 31 * 24 * 60 * 60
    os.utime(stale, (old_time, old_time))
    # when
    status, stdout, stderr = run_hook("SessionStart")
    # then
    assert status == 0
    assert stderr == ""
    assert stdout
    assert not stale.exists()
    assert recent.read_text(encoding="utf-8") == "recent"
    assert settings_env.is_file()


@pytest.mark.parametrize("event_name", ["SessionStart", "UserPromptSubmit"])
def test_write_failures_do_not_affect_hook_output(settings_env, event_name):
    """설정 기록을 쓸 수 없어도 시작 지침은 출력하고 프롬프트는 조용히 끝낸다."""
    # given
    settings_env.parent.parent.mkdir(parents=True)
    settings_env.parent.write_text("blocked", encoding="utf-8")
    # when
    status, stdout, stderr = run_hook(event_name)
    # then
    assert status == 0
    assert stderr == ""
    assert stdout == "" or event_name == "SessionStart"
    assert settings_env.parent.read_text(encoding="utf-8") == "blocked"


def test_changed_settings_are_not_announced_when_the_write_fails(settings_env, monkeypatch):
    """변경한 설정을 저장하지 못하면 안내도 출력하지 않고 이전 기록을 유지한다."""
    # given
    run_hook("SessionStart")
    original = settings_env.read_bytes()
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_IMPLEMENTATION_WORKER", "sonnet")
    monkeypatch.setattr(session_context.os, "replace", mock.Mock(side_effect=OSError("blocked")))
    # when
    result = run_hook()
    # then
    assert result == (0, "", "")
    assert settings_env.read_bytes() == original
    assert list(settings_env.parent.iterdir()) == [settings_env]


def test_prompt_never_loads_instructions_or_starts_a_subprocess(settings_env, monkeypatch):
    """프롬프트 변경 안내는 지침 파일을 읽거나 외부 명령을 실행하지 않는다."""
    # given
    run_hook("SessionStart")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_IMPLEMENTATION_WORKER", "sonnet")
    forbidden = mock.Mock(side_effect=AssertionError("unexpected instruction or subprocess access"))
    monkeypatch.setattr(session_context, "read_instruction", forbidden)
    monkeypatch.setattr(session_context, "render_context", forbidden)
    monkeypatch.setattr(session_context.subprocess, "run", forbidden)
    # when
    status, stdout, stderr = run_hook()
    # then
    assert status == 0
    assert stderr == ""
    assert NOTICE_PREFIX in json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
    assert forbidden.call_count == 0
