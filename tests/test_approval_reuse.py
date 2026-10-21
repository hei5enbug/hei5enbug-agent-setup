import re

import pytest

from test_approval_guard import bash_event, fake_bin, guard, state, state_mod  # noqa: F401


def decision(output):
    return output["hookSpecificOutput"]["permissionDecision"] if output else None


def reason(output):
    return output["hookSpecificOutput"]["permissionDecisionReason"] if output else ""


def mcp_event(tool, tool_input, tool_use_id):
    return {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": tool, "tool_input": tool_input,
            "tool_use_id": tool_use_id}


def approve_and_finish(event, host):
    """Approve the call the way the user would on each host, then let it complete."""
    first = guard.handle(event, host)
    if host == "codex":
        code = re.search(r"(?:승인|approve) ([A-Z2-9]{6})", reason(first))[1]
        guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "승인 " + code}, host)
        guard.handle(event, host)
    guard.handle({**event, "hook_event_name": "PostToolUse"}, host)
    return first


def asked(output, host):
    return decision(output) == ("ask" if host == "claude" else "deny")


def passed(output, host):
    return decision(output) == ("allow" if host == "claude" else None)


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_an_approved_sensitive_read_covers_every_sensitive_read_of_the_session(state, fake_bin, host):
    """민감 조회는 한 번 승인하면 다른 민감 조회도 세션 동안 다시 묻지 않는다."""
    # given
    first = approve_and_finish(bash_event("printenv", cwd=state, tool_use_id="first"), host)
    # when
    other = guard.handle(bash_event("cat .env", cwd=state, tool_use_id="second"), host)
    # then
    assert asked(first, host)
    assert passed(other, host)
    if host == "claude":
        assert reason(other).startswith("Approved earlier in this session:")


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_a_sensitive_approval_does_not_cover_writes(state, fake_bin, host):
    """민감 조회 승인은 쓰기 승인을 만들지 않으므로 이어지는 쓰기는 따로 묻는다."""
    # given
    approve_and_finish(bash_event("printenv", cwd=state, tool_use_id="first"), host)
    # when
    output = guard.handle(bash_event("kubectl apply -f a.yaml -n web --context dev", cwd=state, tool_use_id="second"), host)
    # then
    assert asked(output, host)


EVERY_TIME_COMMANDS = [
    "git push --force origin main",
    "git push origin :old-branch",
    "git reset --hard",
    "git clean -fd",
    "git checkout .",
    "git stash clear",
    "rm -rf /usr/local/share/example-data",
    "kubectl delete pod x --context dev -n web",
    "helm uninstall web --kube-context dev",
    "gh repo delete owner/repo --yes",
    "codex exec --dangerously-bypass-approvals-and-sandbox 'task'",
]


@pytest.mark.parametrize("command", EVERY_TIME_COMMANDS)
def test_every_time_actions_are_marked_at_classification(state, fake_bin, command):
    """매번 묻는 목록의 작업은 분류 단계에서 매번 묻는 작업으로 표시된다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


@pytest.mark.parametrize("command", [
    "docker --context prod rm -f c1", "docker --context prod rmi img", "docker --context prod system prune",
    "docker --context prod compose down -v", "npm publish",
    "curl -X DELETE https://example.com/item/1",
])
def test_formerly_reusable_destructive_actions_ask_every_time(state, fake_bin, command):
    """예전에 키별 1회로 재사용하던 삭제와 배포 작업은 매번 묻는 작업으로 분류된다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("command", [
    "git push --force origin main", "git reset --hard", "rm -rf /usr/local/share/example-data",
    "kubectl delete pod x --context dev -n web", "gh repo delete owner/repo --yes",
])
def test_every_time_actions_ask_again_after_an_approval(state, fake_bin, host, command):
    """매번 묻는 목록의 작업은 한 번 승인한 뒤 같은 명령을 다시 실행해도 다시 묻는다."""
    # given
    approve_and_finish(bash_event(command, cwd=state, tool_use_id="first"), host)
    # when
    again = guard.handle(bash_event(command, cwd=state, tool_use_id="second"), host)
    # then
    assert asked(again, host)
    if host == "claude":
        assert reason(again).startswith("Asks every time:")


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_destructive_sql_through_mcp_asks_every_time(state, fake_bin, host):
    """MCP 도구로 보내는 파괴적 SQL은 승인한 뒤에도 매번 다시 묻는다."""
    # given
    tool, tool_input = "mcp__db__run_query", {"query": "DROP TABLE orders"}
    approve_and_finish(mcp_event(tool, tool_input, "first"), host)
    # when
    again = guard.handle(mcp_event(tool, tool_input, "second"), host)
    # then
    assert guard.classify_mcp(tool, tool_input).every_time is True
    assert asked(again, host)


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_a_list_action_inside_a_compound_keeps_the_whole_call_every_time(state, fake_bin, host):
    """한 번 승인한 삭제와 매번 묻는 작업을 이어 붙이면 호출 전체가 매번 묻는 작업이 된다."""
    # given
    approve_and_finish(bash_event("docker --context prod rm -f c1", cwd=state, tool_use_id="first"), host)
    command = "docker --context prod rm -f c1; git push --force origin main"
    # when
    output = guard.handle(bash_event(command, cwd=state, tool_use_id="second"), host)
    # then
    assert guard.classify_text(command, str(state)).every_time is True
    assert asked(output, host)
    if host == "claude":
        assert reason(output).startswith("Asks every time:")


@pytest.mark.parametrize("name", [".env.example", ".env.local.example", ".env.sample", ".env.template", ".env.dist"])
@pytest.mark.parametrize("tool", ["Read", "Bash"])
def test_environment_templates_are_not_protected_values(state, fake_bin, name, tool):
    """.env 템플릿 파일 읽기는 보호 값 읽기가 아니므로 묻지 않는다."""
    # given
    tool_input = {"file_path": name} if tool == "Read" else {"command": "cat " + name}
    event = {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": tool, "tool_input": tool_input,
             "cwd": str(state)}
    # when
    output = guard.handle(event, "claude")
    # then
    assert decision(output) in (None, "allow")


@pytest.mark.parametrize("name", [".env", ".env.local", ".env.production", ".envrc"])
def test_real_environment_files_stay_protected(state, fake_bin, name):
    """실제 .env 파일과 .envrc 읽기는 계속 보호 값 읽기로 분류한다."""
    # given
    command = "cat " + name
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "sensitive"


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_a_reused_approval_does_not_cover_a_nested_write(state, fake_bin, host):
    """중첩 셸 안의 쓰기 키도 합쳐지므로 삭제 승인만으로 쓰기를 함께 실행하지 않는다."""
    # given
    approve_and_finish(bash_event("docker --context prod rm -f c1", cwd=state, tool_use_id="first"), host)
    command = "bash -c 'docker --context prod rm -f c1; gh issue create --title t --body b'"
    # when
    output = guard.handle(bash_event(command, cwd=state, tool_use_id="second"), host)
    # then
    assert state_mod.WRITE_KEY in state_mod.split_outcome(guard.classify_text(command, str(state)))[1]
    assert asked(output, host)


@pytest.mark.parametrize("tool_input", [
    {"action": "delete", "query": "DELETE FROM orders"},
    {"query": "DROP TABLE orders"},
])
def test_destructive_mcp_sql_is_every_time_even_with_a_destructive_name_or_action(tool_input):
    """MCP 도구 이름이나 action이 파괴적이어도 파괴적 SQL은 매번 묻는 작업으로 분류한다."""
    # given
    tool = "mcp__db__delete_rows"
    # when
    outcome = guard.classify_mcp(tool, tool_input)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


@pytest.mark.parametrize("command", [
    "psql -h db -c 'DELETE FROM orders' -f /dev/null",
    "kubectl exec pod -- docker rm -f c1",
    "oc exec pod -- docker rm -f c1",
])
def test_fallback_and_remote_exec_paths_keep_the_every_time_mark(state, fake_bin, command):
    """분류 불가 경로의 파괴적 SQL과 원격 exec 안의 파괴적 명령도 매번 묻는 작업으로 분류한다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_remote_exec_is_not_allowed_by_a_local_docker_approval(state, fake_bin, host):
    """로컬 Docker 삭제를 승인했어도 원격 exec 안의 같은 삭제는 다시 묻는다."""
    # given
    approve_and_finish(bash_event("docker --context prod rm -f c1", cwd=state, tool_use_id="first"), host)
    # when
    output = guard.handle(bash_event("kubectl exec pod -- docker rm -f c1", cwd=state, tool_use_id="second"), host)
    # then
    assert asked(output, host)
