import re
from concurrent.futures import ThreadPoolExecutor

import pytest

from test_approval_guard import PG_ID, bash_event, datagrip_guard, fake_bin, guard, project, query_event, state, state_mod


STOP_REASON = (
    "This approval was requested three times without the call completing (declines included); "
    "stop retrying and tell the user."
)


def decision(output):
    return output["hookSpecificOutput"]["permissionDecision"] if output else None


def reason(output):
    return output["hookSpecificOutput"]["permissionDecisionReason"] if output else ""


def code(output):
    return re.search(r"(?:승인|approve) ([A-Z2-9]{6})", reason(output))[1]


def outcome(kind="always", keys=("key-a",), every_time=True):
    return state_mod.Outcome(kind, list(keys), ["Requested action"], every_time=every_time and kind in ("always", "sensitive"))


def count(key="key-a", host="codex", session="s1"):
    return state_mod._load(host, session).get("request_counts", {}).get(key, 0)


def approved_attempt(action=None, tool_id="first"):
    action = action or outcome()
    denied = state_mod.pre_decision("codex", "s1", action, tool_id)
    state_mod.approve_text("codex", "s1", "승인 " + code(denied))
    state_mod.pre_decision("codex", "s1", action, tool_id)
    return code(denied)


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("kind", ["always", "sensitive", "write", "request"])
def test_fourth_uncompleted_approval_request_is_denied_without_a_new_ask_or_code(state, host, kind):
    """같은 키의 미완료 승인 요청이 세 번이면 네 번째 요청은 코드 없이 중단을 안내한다."""
    # given
    action = outcome(kind)
    previous = [state_mod.pre_decision(host, "s1", action) for _ in range(3)]
    pending = dict(state_mod._load(host, "s1")["pending"])
    # when
    output = state_mod.pre_decision(host, "s1", action)
    # then
    assert all(decision(value) == ("ask" if host == "claude" else "deny") for value in previous)
    assert decision(output) == "deny"
    assert reason(output) == STOP_REASON
    assert count(state_mod.WRITE_KEY if kind in ("write", "request") else "key-a", host) == 3
    assert state_mod._load(host, "s1")["pending"] == pending


@pytest.mark.parametrize("kind", ["always", "sensitive", "write", "request"])
def test_third_issued_code_is_honored_after_the_user_approves_it(state, kind):
    """세 번째로 발급한 코드를 승인하면 한도에 도달했어도 해당 재시도를 실행한다."""
    # given
    action = outcome(kind)
    issued = [state_mod.pre_decision("codex", "s1", action) for _ in range(3)]
    state_mod.approve_text("codex", "s1", "승인 " + code(issued[-1]))
    # when
    output = state_mod.pre_decision("codex", "s1", action, "approved-third")
    # then
    assert output is None
    assert count(state_mod.WRITE_KEY if kind in ("write", "request") else "key-a") == 3


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_a_completed_call_resets_the_count_for_its_keys(state, host):
    """호출이 완료되면 해당 키의 미완료 승인 요청 횟수를 초기화한다."""
    # given
    action = outcome()
    issued = [state_mod.pre_decision(host, "s1", action) for _ in range(3)]
    if host == "codex":
        state_mod.approve_text(host, "s1", "승인 " + code(issued[-1]))
        state_mod.pre_decision(host, "s1", action, "done")
    # when
    state_mod.after_call(host, "s1", action, "done")
    # then
    assert count(host=host) == 0


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_completed_call_allows_a_new_approval_request(state, host):
    """완료된 호출 뒤에는 새 승인 요청을 첫 번째 횟수부터 다시 발급한다."""
    # given
    action = outcome()
    for _ in range(3):
        state_mod.pre_decision(host, "s1", action)
    state_mod.after_call(host, "s1", action)
    # when
    output = state_mod.pre_decision(host, "s1", action)
    # then
    assert decision(output) == ("ask" if host == "claude" else "deny")
    assert reason(output) != STOP_REASON
    assert count(host=host) == 1


@pytest.mark.parametrize(("host", "session", "key"), [
    ("codex", "s1", "key-b"), ("codex", "s2", "key-a"), ("claude", "s1", "key-a"),
])
def test_request_budgets_are_separate_for_each_host_session_and_key(state, host, session, key):
    """승인 요청 한도는 호스트·세션·키마다 독립적으로 계산한다."""
    # given
    for _ in range(3):
        state_mod.pre_decision("codex", "s1", outcome())
    # when
    output = state_mod.pre_decision(host, session, outcome(keys=(key,)))
    # then
    assert reason(output) != STOP_REASON
    assert count() == 3
    assert count(key, host, session) == 1


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_already_approved_session_keys_do_not_spend_or_block_a_compound_request(state, host):
    """이미 승인된 세션 쓰기 키는 일회 승인을 요청할 때 횟수를 늘리거나 요청을 막지 않는다."""
    # given
    for _ in range(3):
        state_mod.pre_decision(host, "s1", outcome("write"))
    state_mod.record_approved(host, "s1", [state_mod.WRITE_KEY])
    action = state_mod.Outcome("always", ["key-b"], ["Requested action"], writes=["key-a"])
    # when
    output = state_mod.pre_decision(host, "s1", action)
    # then
    assert decision(output) == ("ask" if host == "claude" else "deny")
    assert reason(output) != STOP_REASON
    assert count(state_mod.WRITE_KEY, host) == 3
    assert count("key-b", host) == 1


def test_granted_once_keys_are_honored_when_another_key_needs_approval(state):
    """한도에 도달한 일회 키도 이미 승인돼 있으면 다른 키만 새로 요청한다."""
    # given
    single = outcome()
    denied = [state_mod.pre_decision("codex", "s1", single) for _ in range(3)]
    state_mod.approve_text("codex", "s1", "승인 " + code(denied[-1]))
    compound = outcome(keys=("key-a", "key-b"))
    # when
    output = state_mod.pre_decision("codex", "s1", compound)
    # then
    assert "approve " in reason(output)
    assert count() == 3
    assert count("key-b") == 1
    assert state_mod._load("codex", "s1")["pending"][code(output)]["once_keys"] == ["key-b"]


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_exhausted_key_blocks_a_compound_without_spending_another_keys_budget(state, host):
    """복합 호출의 한 키가 한도를 넘으면 다른 키의 횟수를 쓰지 않고 거부한다."""
    # given
    for _ in range(3):
        state_mod.pre_decision(host, "s1", outcome())
    # when
    output = state_mod.pre_decision(host, "s1", outcome(keys=("key-a", "key-b")))
    # then
    assert reason(output) == STOP_REASON
    assert count("key-b", host) == 0


def test_completion_resets_only_the_completed_calls_keys(state):
    """완료 처리는 다른 키의 미완료 요청 횟수를 보존한다."""
    # given
    for _ in range(3):
        state_mod.pre_decision("codex", "s1", outcome())
    state_mod.pre_decision("codex", "s1", outcome(keys=("key-b",)))
    # when
    state_mod.after_call("codex", "s1", outcome())
    # then
    assert count() == 0
    assert count("key-b") == 1


def test_interrupted_once_approval_can_be_reused_once_without_a_new_code(state):
    """완료 기록이 없는 일회 승인은 다음 같은 키 호출에서 코드 없이 한 번 재사용한다."""
    # given
    action = outcome()
    approved_attempt(action)
    # when
    output = state_mod.pre_decision("codex", "s1", action, "retry")
    # then
    assert output is None
    assert count() == 1
    assert state_mod.permission_allowed("codex", "s1", action, "retry")
    assert not state_mod.permission_allowed("codex", "s1", action, "first")


def test_second_interruption_requires_another_counted_request(state):
    """같은 일회 승인을 재사용한 호출도 중단되면 다음 요청은 새 코드와 횟수를 받는다."""
    # given
    action = outcome()
    previous_code = approved_attempt(action)
    state_mod.pre_decision("codex", "s1", action, "retry")
    # when
    output = state_mod.pre_decision("codex", "s1", action, "second-interruption")
    # then
    assert decision(output) == "deny"
    assert code(output) != previous_code
    assert count() == 2


def test_interrupted_approval_cannot_be_reused_for_a_different_key(state):
    """중단된 일회 승인은 다른 키의 호출에는 재사용할 수 없다."""
    # given
    approved_attempt()
    # when
    output = state_mod.pre_decision("codex", "s1", outcome(keys=("key-b",)), "other")
    # then
    assert decision(output) == "deny"
    assert count("key-b") == 1


def test_completing_a_reused_call_clears_its_approval_and_budget(state):
    """재사용한 호출이 완료되면 일회 승인과 미완료 요청 횟수를 함께 정리한다."""
    # given
    action = outcome()
    approved_attempt(action)
    state_mod.pre_decision("codex", "s1", action, "retry")
    # when
    state_mod.after_call("codex", "s1", action, "retry")
    # then
    assert count() == 0
    assert not state_mod.permission_allowed("codex", "s1", action, "retry")
    assert state_mod._load("codex", "s1")["inflight"] == []


def test_two_interruptions_per_code_still_stop_after_three_requests(state):
    """각 코드의 호출이 두 번씩 중단돼도 승인 요청 세 번 뒤에는 반복을 중단한다."""
    # given
    action = outcome()
    for index in range(3):
        approved_attempt(action, f"first-{index}")
        state_mod.pre_decision("codex", "s1", action, f"retry-{index}")
    # when
    output = state_mod.pre_decision("codex", "s1", action, "fourth-request")
    # then
    assert decision(output) == "deny"
    assert reason(output) == STOP_REASON
    assert count() == 3


def test_concurrent_requests_cannot_issue_more_than_three_codes(state):
    """동시에 요청해도 같은 키에는 세 번을 넘겨 승인 코드를 발급하지 않는다."""
    # given
    action = outcome()
    def attempt(_):
        return state_mod.pre_decision("codex", "s1", action)
    # when
    with ThreadPoolExecutor(max_workers=4) as executor:
        outputs = list(executor.map(attempt, range(4)))
    # then
    assert sum(reason(value) == STOP_REASON for value in outputs) == 1
    assert sum("approve " in reason(value) for value in outputs) == 3
    assert count() == 3


def test_datagrip_claude_always_asks_use_the_same_bound(state, project):
    """Claude의 DataGrip 항상 승인 호출도 별도 훅과 함께 요청 한도를 한 번씩 계산한다."""
    # given
    event = query_event(project, PG_ID, "DELETE FROM t")
    for _ in range(3):
        guard.handle(event, "claude")
        datagrip_guard.handle(event)
    # when
    output = guard.handle(event, "claude")
    # then
    assert decision(output) == "deny"
    assert reason(output) == STOP_REASON


def test_datagrip_claude_writes_are_not_counted_twice(state, project):
    """DataGrip 일반 쓰기는 전용 훅에서만 횟수를 늘려 한 호출을 두 번 세지 않는다."""
    # given
    event = query_event(project, PG_ID, "UPDATE t SET a=1")
    guard.handle(event, "claude")
    # when
    datagrip_guard.handle(event)
    # then
    assert count(state_mod.WRITE_KEY, "claude") == 1
