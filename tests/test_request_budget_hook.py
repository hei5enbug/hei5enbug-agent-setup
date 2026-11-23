"""요청 예산 훅: 프롬프트의 초기화와 한도 안내, 시작 허용, 결과 기록, 프로세스 계약."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import request_budget as budget  # noqa: E402
import request_budget_hook as hook  # noqa: E402

SESSION = "session-hook"
WORKER = "hei5enbug-agent-setup:worker"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    for name in ("HEI5ENBUG_PARENT_SESSION", "PLUGIN_ROOT", "CLAUDE_PLUGIN_OPTION_REQUEST_RUN_CAP",
                 "CLAUDE_PLUGIN_OPTION_REQUEST_RETRY_CAP", "HEI5ENBUG_PARALLEL_LIMIT_MAX"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(hook.parallel_limit, "current_limit", lambda host, cwd=".": 100)
    monkeypatch.setattr(hook.parallel_limit, "host_pid", os.getpid)


def event(name, **fields):
    return {"hook_event_name": name, "session_id": SESSION, **fields}


def launch(number, agent=WORKER, **extra):
    return hook.handle(event("PreToolUse", tool_name="Agent", tool_use_id=f"t{number}", tool_input={"subagent_type": agent, **extra}))


def fail(number, agent=WORKER):
    hook.handle(event("PostToolUseFailure", tool_name="Agent", tool_use_id=f"t{number}",
                      tool_input={"subagent_type": agent}, error="boom"))


def test_프롬프트는_개수를_0으로_되돌리고_병렬_한도를_알린다(monkeypatch):
    """한도 1에서 둘째 시작이 거부된 뒤 프롬프트가 오면 한도 안내가 나오고 다시 시작할 수 있다."""
    # given
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_REQUEST_RUN_CAP", "1")
    launch(1)
    denied = launch(2)

    # when
    output = hook.handle(event("UserPromptSubmit", prompt="next"))
    again = launch(3)

    # then
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "Parallel agent limit: 100" in output["hookSpecificOutput"]["additionalContext"]
    assert again is None


def test_목표_연속처럼_프롬프트_없이_이어지는_턴도_멈춤마다_새_요청이라_시작이_쌓이지_않는다(monkeypatch):
    """한도 10에서 프롬프트 하나 뒤 멈춤으로 끝나는 턴 열 번이 각각 아홉 시작을 하면 모두 허용되고, 멈춤 없이 이어 가면 열한 번째가 거부된다."""
    # given
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_REQUEST_RUN_CAP", "10")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_REQUEST_RETRY_CAP", "0")
    hook.handle(event("UserPromptSubmit", prompt="/goal tests pass"))
    number = 0

    # when
    continuations = []
    for _ in range(10):
        for _ in range(9):
            number += 1
            continuations.append(launch(number))
            hook.handle(event("PostToolUse", tool_name="Agent", tool_use_id=f"t{number}", tool_input={"subagent_type": WORKER}, tool_response={}))
        assert hook.handle(event("Stop", stop_hook_active=True)) is None
    uncounted = [launch(number + index) for index in range(1, 12)]

    # then
    assert continuations == [None] * 90
    assert [item is None for item in uncounted] == [True] * 10 + [False]
    assert uncounted[-1]["hookSpecificOutput"]["permissionDecisionReason"].startswith(budget.CAP_MARKER)


def test_하위_에이전트와_역할_실행기_자식의_멈춤은_요청을_새로_시작하지_않는다(monkeypatch):
    """agent_id 가 있는 멈춤과 HEI5ENBUG_PARENT_SESSION 이 있는 자식의 멈춤은 부모 세션의 개수를 그대로 둔다."""
    # given
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_REQUEST_RUN_CAP", "1")
    launch(1)

    # when
    hook.handle(event("Stop", agent_id="abc"))
    after_subagent = launch(2)
    monkeypatch.setenv("HEI5ENBUG_PARENT_SESSION", f"claude:{SESSION}")
    hook.handle(event("Stop", session_id="child-session"))
    after_child = launch(3)

    # then
    assert after_subagent["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert after_child["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_거부_결정은_한도_메시지를_담는다(monkeypatch):
    """거부 사유는 요청 한도 마커로 시작한다."""
    # given
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_REQUEST_RUN_CAP", "1")
    launch(1)

    # when
    reason = launch(2)["hookSpecificOutput"]["permissionDecisionReason"]

    # then
    assert reason.startswith(budget.CAP_MARKER)


def test_실패한_시작_뒤의_같은_유형_시작은_재시도로_센다(monkeypatch):
    """재시도 한도 1에서 실패를 두 번 겪으면 셋째 worker 시작은 거부되고 다른 유형은 허용된다."""
    # given
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_REQUEST_RUN_CAP", "0")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_REQUEST_RETRY_CAP", "1")
    for number in (1, 2):
        assert launch(number) is None
        fail(number)

    # when
    same = launch(3)
    other = launch(4, agent="hei5enbug-agent-setup:scout")

    # then
    assert same is not None and other is None


def test_오류_응답을_담은_PostToolUse도_실패로_센다(monkeypatch):
    """PostToolUse 응답에 error 가 있으면 실패로 기록해 다음 시작이 재시도가 된다."""
    # given
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_REQUEST_RUN_CAP", "0")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_REQUEST_RETRY_CAP", "1")
    for number in (1, 2):
        assert launch(number) is None
        hook.handle(event("PostToolUse", tool_name="Agent", tool_use_id=f"t{number}",
                          tool_input={"subagent_type": WORKER}, tool_response='{"error": "x"}'))

    # when
    third = launch(3)

    # then
    assert third is not None


def test_응답이_실패인지_읽는_형태():
    """error 키나 is_error 가 있는 응답은 실패이고, 평범한 문자열이나 id 만 있는 응답은 아니다."""
    # given / when
    results = [hook.response_failed('{"error": "x"}'), hook.response_failed('{"id": "a"}'),
               hook.response_failed({"is_error": True}), hook.response_failed("plain text")]

    # then
    assert results == [True, False, True, False]


def test_다른_도구와_키를_만들_수_없는_세션은_그대로_통과한다(monkeypatch):
    """Bash 호출과 잘못된 세션 ID 의 에이전트 시작은 한도 1이어도 출력이 없다."""
    # given
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_REQUEST_RUN_CAP", "1")
    unkeyed = {"hook_event_name": "PreToolUse", "session_id": "bad id", "tool_name": "Agent", "tool_input": {}}

    # when
    bash = hook.handle(event("PreToolUse", tool_name="Bash", tool_input={"command": "ls"}))
    results = [hook.handle(unkeyed) for _ in range(3)]

    # then
    assert bash is None and results == [None, None, None]


def test_자식_세션은_개수를_초기화하지_않고_부모_개수에_더한다(monkeypatch):
    """부모 세션이 지정된 환경의 프롬프트는 초기화하지 않고, 그 시작은 부모의 개수로 들어간다."""
    # given
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_REQUEST_RUN_CAP", "2")
    monkeypatch.setenv("HEI5ENBUG_PARENT_SESSION", f"claude:{SESSION}")

    # when
    prompt = hook.handle(event("UserPromptSubmit", session_id="child-own"))
    first = launch(1)
    monkeypatch.delenv("HEI5ENBUG_PARENT_SESSION")

    # then
    assert prompt is None and first is None
    assert budget.counts(("claude", SESSION))["runs"] == 1


def test_백그라운드_시작은_하위_에이전트가_멈출_때까지_자리를_지킨다(monkeypatch):
    """병렬 한도 1에서 백그라운드 시작의 PostToolUse 뒤에도 둘째는 거부되고, SubagentStop 뒤에는 허용된다."""
    # given
    monkeypatch.setattr(hook.parallel_limit, "current_limit", lambda host, cwd=".": 1)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_REQUEST_RUN_CAP", "0")
    launch(1, run_in_background=True)
    hook.handle(event("PostToolUse", tool_name="Agent", tool_use_id="t1",
                      tool_input={"subagent_type": WORKER, "run_in_background": True}, tool_response={}))

    # when
    blocked = launch(2)
    hook.handle(event("SubagentStop"))
    freed = launch(3)

    # then
    assert blocked["hookSpecificOutput"]["permissionDecisionReason"].startswith(budget.LIMIT_MARKER)
    assert freed is None


def test_프로세스는_표준_출력에_거부_결정을_JSON으로_낸다(tmp_path):
    """훅 프로세스는 허용된 첫 시작에는 출력이 없고, 한도 뒤의 둘째 시작에는 deny JSON 을 낸다."""
    # given
    env = {**os.environ, "XDG_STATE_HOME": str(tmp_path / "state"), "CLAUDE_PLUGIN_OPTION_REQUEST_RUN_CAP": "1",
           "HEI5ENBUG_PARALLEL_LIMIT_MAX": "0"}
    env.pop("HEI5ENBUG_PARENT_SESSION", None)
    env.pop("PLUGIN_ROOT", None)

    def run(number):
        payload = event("PreToolUse", tool_name="Agent", tool_use_id=f"p{number}", tool_input={"subagent_type": "x:y"})
        return subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "request_budget_hook.py")], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, check=False, timeout=30)

    # when
    first, second = run(1), run(2)

    # then
    assert first.returncode == 0 and first.stdout == ""
    assert json.loads(second.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
