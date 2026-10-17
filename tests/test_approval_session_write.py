"""Acceptance checks: one approval per session covers every non-destructive write, with a short prompt."""
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import approval_guard as guard  # noqa: E402
import approval_state as state_mod  # noqa: E402

APPLY = "kubectl apply -f a --context dev -n web"
OTHER_WRITES = [
    "helm upgrade rel chart --kube-context dev -n web",
    "docker compose up -d",
    "curl -X POST https://example.com/hook -d x",
    "az vm start -n vm1 -g rg1",
]
JIRA_TOOL = "mcp__claude_ai_Atlassian__createJiraIssue"
CODE = re.compile(r"승인 ([A-Z2-9]{6})")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    for name in ("HEI5ENBUG_PARENT_SESSION", "KUBECONFIG", "AWS_PROFILE", "CLOUDSDK_CORE_PROJECT", "DOCKER_CONTEXT"):
        monkeypatch.delenv(name, raising=False)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("kubectl", "az"):
        (bin_dir / name).write_text("#!/bin/sh\necho fake\n")
        (bin_dir / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    return tmp_path


def bash(command, name="PreToolUse", session="s1"):
    return {"hook_event_name": name, "tool_name": "Bash", "tool_input": {"command": command}, "session_id": session}


def mcp(tool, name="PreToolUse", session="s1"):
    return {"hook_event_name": name, "tool_name": tool, "tool_input": {"title": "t"}, "session_id": session}


def decision(output):
    return output["hookSpecificOutput"]["permissionDecision"] if output else None


def reason(output):
    return output["hookSpecificOutput"]["permissionDecisionReason"]


def run_approved(event_factory, host="claude", session="s1"):
    """Ask, then record the way the host does after the user approves and the call completes."""
    asked = guard.handle(event_factory("PreToolUse", session), host)
    guard.handle(event_factory("PostToolUse", session), host)
    return asked


def grant_write(session="s1"):
    run_approved(lambda name, sid: bash(APPLY, name, sid), session=session)


def test_처음_쓰기는_무슨_쓰기인지_짧게_묻는다(home):
    output = guard.handle(bash(APPLY), "claude")
    assert decision(output) == "ask"
    text = reason(output)
    assert text.startswith("Write: kubectl apply on (default) dev/web.")
    assert "Approve once" in text and "rest of this session" in text
    assert len(text) <= 240


@pytest.mark.parametrize("command", OTHER_WRITES)
def test_한_번_승인하면_다른_쓰기도_세션_동안_허용한다(home, command):
    grant_write()
    output = guard.handle(bash(command), "claude")
    assert decision(output) == "allow"
    assert "Approved earlier in this session" in reason(output)


def test_한_번_승인하면_mcp_쓰기도_허용한다(home):
    grant_write()
    assert decision(guard.handle(mcp(JIRA_TOOL), "claude")) == "allow"


def test_mcp_쓰기_승인도_cli_쓰기를_허용한다(home):
    run_approved(lambda name, sid: mcp(JIRA_TOOL, name, sid))
    assert decision(guard.handle(bash(APPLY), "claude")) == "allow"


def test_mcp_쓰기_질문도_도구_이름을_말한다(home):
    output = guard.handle(mcp(JIRA_TOOL), "claude")
    assert decision(output) == "ask"
    assert JIRA_TOOL in reason(output)
    assert "Approve once" in reason(output)


def test_승인_기록은_하나의_키다(home):
    grant_write()
    run_approved(lambda name, sid: bash(OTHER_WRITES[0], name, sid))
    assert state_mod._load("claude", "s1")["approved"] == ["write:session"]


def test_다른_세션으로_옮겨가지_않는다(home):
    grant_write(session="s1")
    assert decision(guard.handle(bash(OTHER_WRITES[0], session="s2"), "claude")) == "ask"


def test_삭제는_승인_뒤에도_매번_묻고_이유에_드러난다(home):
    grant_write()
    command = "kubectl delete pod x --context dev -n web"
    output = guard.handle(bash(command), "claude")
    assert decision(output) == "ask"
    assert "every time" in reason(output)
    assert "kubectl delete pod x on (default) dev/web" in reason(output)
    guard.handle(bash(command, "PostToolUse"), "claude")
    assert decision(guard.handle(bash(command), "claude")) == "ask"


def test_삭제만_승인해서는_쓰기_승인이_생기지_않는다(home):
    command = "kubectl delete pod x --context dev -n web"
    run_approved(lambda name, sid: bash(command, name, sid))
    assert decision(guard.handle(bash(OTHER_WRITES[0]), "claude")) == "ask"


def test_삭제가_섞인_복합_명령을_승인하면_쓰기_부분은_세션_승인이_된다(home):
    command = f"{APPLY} && kubectl delete pod x --context dev -n web"
    output = guard.handle(bash(command), "claude")
    assert decision(output) == "ask" and "every time" in reason(output)
    guard.handle(bash(command, "PostToolUse"), "claude")
    assert decision(guard.handle(bash(OTHER_WRITES[0]), "claude")) == "allow"


@pytest.mark.parametrize("command", ["printenv", "bash /nonexistent/run.sh"])
def test_민감하거나_분류할_수_없는_호출은_승인_뒤에도_매번_묻는다(home, command):
    grant_write()
    output = guard.handle(bash(command), "claude")
    assert decision(output) == "ask"
    assert "every time" in reason(output)


def test_요청_명령은_하나의_세션_쓰기_키를_받는다(home):
    command = "python3 {} request --key write:session --why 'Deploy the change'".format(REPO_ROOT / "scripts/approval_guard.py")
    outcome = guard._request_outcome(command, str(home))
    assert outcome is not None and outcome.kind == "request"
    output = guard.handle(bash(command), "claude")
    assert decision(output) == "ask"


def test_요청_명령은_예전_키도_받는다(home):
    command = "python3 {} request --key 'kubectl:apply@(default) dev/web' --why 'Deploy'".format(
        REPO_ROOT / "scripts/approval_guard.py")
    outcome = guard._request_outcome(command, str(home))
    assert outcome is not None and outcome.kind == "request"


def test_codex는_처음_쓰기를_코드로_막고_승인_뒤_다른_쓰기를_통과시킨다(home):
    first = guard.handle(bash(APPLY), "codex")
    assert decision(first) == "deny"
    code = CODE.search(reason(first)).group(1)
    assert "Approval required: kubectl apply on (default) dev/web" in reason(first)
    prompt = {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": f"승인 {code}"}
    assert guard.handle(prompt, "codex") is not None
    assert guard.handle(bash(APPLY), "codex") is None
    guard.handle(bash(APPLY, "PostToolUse"), "codex")
    assert guard.handle(bash(OTHER_WRITES[0]), "codex") is None
    permission = guard.handle(bash(OTHER_WRITES[0], "PermissionRequest"), "codex")
    assert permission["hookSpecificOutput"]["decision"]["behavior"] == "allow"
    assert state_mod._load("codex", "s1")["approved"] == ["write:session"]


def test_codex는_삭제를_세션_승인_뒤에도_코드로_막는다(home):
    first = guard.handle(bash(APPLY), "codex")
    code = CODE.search(reason(first)).group(1)
    guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": f"승인 {code}"}, "codex")
    output = guard.handle(bash("kubectl delete pod x --context dev -n web"), "codex")
    assert decision(output) == "deny"
    assert "Approval required" in reason(output)


def test_메인_세션의_쓰기_승인은_자식_세션이_물려받는다(home, monkeypatch):
    state_mod.record_approved("claude", "parent", ["write:session"])
    monkeypatch.setenv("HEI5ENBUG_PARENT_SESSION", "claude:parent")
    output = guard.handle(bash(OTHER_WRITES[0], session="child"), "claude")
    assert decision(output) == "allow"
    assert "Approved in the main session" in reason(output)
