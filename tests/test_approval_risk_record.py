"""Acceptance checks: the approval guard records each write, every-time, and critical call for the transcript marker."""
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import approval_guard as guard  # noqa: E402
import approval_state as state_mod  # noqa: E402
from approval_state import Outcome  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
    monkeypatch.setenv("HEI5ENBUG_RESPONSE_LANGUAGE", "English")
    state_mod.prompt_language.cache_clear()
    for name in ("HEI5ENBUG_PARENT_SESSION", "KUBECONFIG", "PLUGIN_ROOT", "CLAUDE_PROJECT_DIR", "HEI5ENBUG_LANGUAGE",
                 "CLAUDE_PLUGIN_OPTION_APPROVAL_SCOPE", "CLAUDE_PLUGIN_OPTION_APPROVAL_GUARD", "HELM_KUBECONTEXT"):
        monkeypatch.delenv(name, raising=False)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "kubectl").write_text("#!/bin/sh\necho fake\n")
    (bin_dir / "kubectl").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    return tmp_path


def bash(command, tool_use_id, name="PreToolUse", session="s1"):
    return {"hook_event_name": name, "tool_name": "Bash", "tool_input": {"command": command}, "session_id": session,
            "tool_use_id": tool_use_id}


def recorded(session="s1", host="claude"):
    path = state_mod.risk_path(host, session)
    return json.loads(path.read_text(encoding="utf-8"))["calls"] if path.exists() else []


def test_쓰기_매번_치명_호출은_tool_use_id별로_kind와_critical을_기록한다(home):
    # given
    events = [
        bash("kubectl apply -f a --context demo-dev -n web", "toolu_write"),
        bash("kubectl delete pod x --context demo-dev -n web", "toolu_always"),
        bash("kubectl delete pod x --context demo-prod -n web", "toolu_critical"),
    ]

    # when
    for event in events:
        guard.handle(event, "claude")

    # then
    assert recorded() == [
        {"id": "toolu_write", "kind": "write", "critical": False},
        {"id": "toolu_always", "kind": "always", "critical": False},
        {"id": "toolu_critical", "kind": "always", "critical": True},
    ]


def test_파일_편집은_세션_쓰기로_기록하고_읽기와_Read는_기록하지_않는다(home):
    # given
    target = str(home / "notes.txt")
    edit = {"hook_event_name": "PreToolUse", "tool_name": "Edit", "session_id": "s1", "tool_use_id": "toolu_edit",
            "tool_input": {"file_path": target, "old_string": "a", "new_string": "b"}, "cwd": str(home)}
    read = {**edit, "tool_name": "Read", "tool_use_id": "toolu_read", "tool_input": {"file_path": target}}

    # when
    guard.handle(bash("kubectl get pods --context demo-dev -n web", "toolu_get"), "claude")
    guard.handle(read, "claude")
    guard.handle(edit, "claude")

    # then
    assert recorded() == [{"id": "toolu_edit", "kind": "write", "critical": False}]


def test_PreToolUse가_아닌_이벤트와_Codex_호스트는_기록하지_않는다(home):
    # given
    command = "kubectl apply -f a --context demo-dev -n web"

    # when
    guard.handle(bash(command, "toolu_post", name="PostToolUse"), "claude")
    guard.handle(bash(command, "toolu_codex"), "codex")

    # then
    assert recorded() == []
    assert recorded(host="codex") == []


def test_승인_가드가_꺼지면_기록하지_않는다(home, monkeypatch):
    # given
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_APPROVAL_GUARD", "false")
    event = bash("kubectl delete pod x --context demo-prod -n web", "toolu_off")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(event).encode())))
    monkeypatch.setattr(sys, "argv", ["approval_guard.py"])

    # when
    code = guard.main()

    # then
    assert code == 0
    assert recorded() == []


def test_같은_호출은_한_번만_남기고_최근_항목만_유지하며_임시_파일을_남기지_않는다(home):
    # given
    write = Outcome("write", ["write:session"], ["w"])
    ids = [f"toolu_{index}" for index in range(state_mod.RISK_LIMIT + 5)]

    # when
    for tool_use_id in ids:
        state_mod.record_risk("claude", "s1", tool_use_id, write)
    state_mod.record_risk("claude", "s1", ids[-3], Outcome("always", ["k"], ["a"], critical=True))

    # then
    calls = recorded()
    assert len(calls) == state_mod.RISK_LIMIT
    assert calls[0]["id"] == ids[5]
    assert calls[-1] == {"id": ids[-3], "kind": "always", "critical": True}
    assert [call["id"] for call in calls].count(ids[-3]) == 1
    assert sorted(path.name for path in state_mod.risk_path("claude", "s1").parent.iterdir()) == [
        ".lock", "claude-s1.json"]


@pytest.mark.parametrize("content", ['{"calls": 1}', "[1, 2]", '{"calls": {"id": "x"}}', "not json", '"text"'])
def test_기록_파일_모양이_잘못돼도_가드_결정은_그대로이고_기록은_빈_목록에서_다시_시작한다(home, content):
    # given
    path = state_mod.risk_path("claude", "s1")
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    expected = guard.handle(bash("kubectl apply -f a --context demo-dev -n web", "toolu_probe", session="s2"), "claude")

    # when
    output = guard.handle(bash("kubectl apply -f a --context demo-dev -n web", "toolu_after"), "claude")

    # then
    assert output == expected
    assert output["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert recorded() == [{"id": "toolu_after", "kind": "write", "critical": False}]


def test_기록_목록의_잘못된_항목만_버리고_올바른_항목은_남긴다(home):
    # given
    path = state_mod.risk_path("claude", "s1")
    path.parent.mkdir(parents=True)
    old = {"id": "toolu_old", "kind": "write", "critical": False}
    path.write_text(json.dumps({"calls": [1, "x", None, old]}), encoding="utf-8")

    # when
    state_mod.record_risk("claude", "s1", "toolu_new", Outcome("always", ["k"], ["a"]))

    # then
    assert recorded() == [old, {"id": "toolu_new", "kind": "always", "critical": False}]


def test_기록_파일을_읽거나_쓸_수_없어도_가드_결정을_돌려준다(home):
    # given
    state_mod.risk_path("claude", "s1").mkdir(parents=True)

    # when
    output = guard.handle(bash("kubectl delete pod x --context demo-prod -n web", "toolu_blocked"), "claude")

    # then
    assert output["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert state_mod.risk_path("claude", "s1").is_dir()


def test_가드가_실패한_뒤의_대체_경로는_기록이_실패해도_매번_승인_결정을_돌려준다(home, monkeypatch, capsys):
    # given
    event = bash("kubectl delete pod x --context demo-prod -n web", "toolu_fallback")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(event).encode())))
    monkeypatch.setattr(sys, "argv", ["approval_guard.py"])

    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(guard, "handle", broken)
    monkeypatch.setattr(state_mod, "record_risk", broken)

    # when
    code = guard.main()

    # then
    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert output["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert guard.FAILURE_REASON in output["hookSpecificOutput"]["permissionDecisionReason"]


def test_세션_id가_없거나_tool_use_id가_없으면_기록하지_않는다(home):
    # given
    write = Outcome("write", ["write:session"], ["w"])

    # when
    state_mod.record_risk("claude", None, "toolu_1", write)
    state_mod.record_risk("claude", "s1", None, write)

    # then
    assert recorded() == []
    assert not (state_mod.state_dir() / "risk").exists()
