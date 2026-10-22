import json
import re
import shlex
import sys
from pathlib import Path

import pytest

from test_approval_guard import (
    APPROVAL_ID, bash_event, datagrip_guard, fake_bin, guard, project,
    query_event, state, state_mod,
)
from test_approval_tabularis import connections


def decision_of(output):
    return output["hookSpecificOutput"]["permissionDecision"] if output else None


WRITES = [
    "kubectl apply -f a --context dev", "kubectl $VERB pods", "eval kubectl get pods",
    "echo x | xargs sh -c 'kubectl get'", "kubectl exec pod -- ls", "kubectl port-forward pod 8080:80",
    "kubectl cp a pod:/a", "kubectl attach pod", "kubectl debug pod", "kubectl run web --image=web",
    "python3 -c 'import subprocess; subprocess.run([\"echo\", \"hello\"])'",
    "python3 -c 'import boto3; boto3.client(\"s3\").list_buckets()'", "python3 tool.py --execute",
    "git push origin main", "git tag v1", "gh pr create", "gh issue comment 1 --body x",
    "gh workflow run ci", "gh api repos/demo/x -f name=x", "gh api /x --input body.json",
    "git -C . push origin main", "git tag -a v1 -m release", "python3 -c 'print(1)' --execute",
    "python3 --execute - <<'PY'\nprint(1)\nPY", "git tag --force v1", "git tag --delete v1", "git tag -d v1",
    "git tag -f v1",
]
ALWAYS = [
    "kubectl delete pod x", "terraform destroy", "helm uninstall web", "eval kubectl delete pod x",
    "sh -c 'kubectl delete pod x'", "python3 -c 'import subprocess; subprocess.run([\"kubectl\", \"delete\", \"pod\", \"x\"])'",
    "python3 -c 'import boto3; boto3.client(\"s3\").delete_bucket(Bucket=\"x\")'",
    "git push --force", "git push --force-with-lease=main:abc", "git push --force-if-includes",
    "git push --delete origin main", "git push --mirror", "git push --prune", "git push -fd origin main",
    "git -C . push --force", "git clean --force",
    "git push origin +main", "git push origin :main", "git reset --hard", "git clean -df",
    "git checkout -f main", "git checkout --force main", "git checkout -- .", "git checkout .",
    "git restore .", "git restore :/", "git stash drop", "git stash clear",
    "gh repo delete x", "gh api /x -X DELETE", "npm publish", "pnpm publish", "yarn publish",
    "yarn npm publish", "uv publish", "poetry publish", "twine upload dist/*", "cargo publish", "gem push x.gem",
    "codex exec --dangerously-bypass-approvals-and-sandbox x", "codex exec --dangerously-bypass-hook-trust x",
    "codex exec -s danger-full-access x", "codex exec --sandbox=danger-full-access x",
    "codex exec -c 'sandbox_mode=\"danger-full-access\"' x", "printenv",
]


@pytest.fixture(autouse=True)
def isolated(state, monkeypatch):
    monkeypatch.delenv("HEI5ENBUG_PARENT_SESSION", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)


def grant(host, session="s1"):
    event = bash_event("kubectl apply -f a --context dev", session=session)
    guard.handle(event, host)
    if host == "claude":
        guard.handle({**event, "hook_event_name": "PostToolUse"}, host)
    else:
        guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": session, "prompt": "승인"}, host)


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("command", WRITES)
def test_other_writes_share_one_approval(state, fake_bin, host, command):
    """한 번 승인한 뒤에는 다른 쓰기도 추가 질문 없이 실행한다."""
    # given
    grant(host)
    event = bash_event(command, cwd=state)
    # when
    output = guard.handle(event, host)
    # then
    assert decision_of(output) == ("allow" if host == "claude" else None)
    assert guard.classify_text(command, str(state)).kind == "write"


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("command", ALWAYS)
def test_irreversible_calls_still_ask(state, fake_bin, host, command):
    """파괴적 호출과 민감한 읽기는 세션 승인 뒤에도 승인을 요구한다."""
    # given
    grant(host)
    event = bash_event(command, cwd=state)
    # when
    output = guard.handle(event, host)
    # then
    assert decision_of(output) == ("ask" if host == "claude" else "deny")


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("tool,arguments", [
    ("mcp__demo__createItem", {}), ("mcp__demo__unknownThing", {}),
    ("mcp__tabularis__run_query", {"connection_id": "marked", "query": "INSERT INTO t VALUES (1)"}),
])
def test_mcp_writes_share_approval(connections, fake_bin, host, tool, arguments):
    """MCP 쓰기와 승인 표시 연결의 조회도 공통 세션 승인을 사용한다."""
    # given
    grant(host)
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": arguments, "session_id": "s1"}
    # when
    output = guard.handle(event, host)
    # then
    assert decision_of(output) == ("allow" if host == "claude" else None)


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_marked_datagrip_write_uses_session_approval(state, project, fake_bin, host):
    """DataGrip 승인 표시 연결의 쓰기는 세션 승인 뒤 실행한다."""
    # given
    grant(host)
    event = query_event(project, APPROVAL_ID, "INSERT INTO t VALUES (1)")
    # when
    output = datagrip_guard.handle(event) if host == "claude" else datagrip_guard.codex_pre_tool_use(event["tool_input"], "s1")
    # then
    assert decision_of(output) == ("allow" if host == "claude" else None)


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("child", [False, True])
def test_approval_lasts_for_the_rest_of_the_session(state, fake_bin, monkeypatch, host, child):
    """쓰기 승인과 자식 세션의 승인 상속은 열두 시간이 지나도 세션이 끝날 때까지 유지된다."""
    # given
    clock = [100000.0]
    monkeypatch.setattr(state_mod.time, "time", lambda: clock[0])
    grant(host, "parent")
    event = bash_event("gh pr create", session="parent")
    clock[0] += 12 * 60 * 60 + 1
    guard.handle({**event, "hook_event_name": "PostToolUse"}, host)
    if child:
        monkeypatch.setenv("HEI5ENBUG_PARENT_SESSION", host + ":parent")
        event["session_id"] = "child"
    # when
    output = guard.handle(event, host)
    # then
    assert decision_of(output) == ("allow" if host == "claude" else None)


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_legacy_approval_without_a_time_is_still_approved(state, fake_bin, host):
    """승인 시각이 없는 예전 승인 기록도 세션 승인으로 인정한다."""
    # given
    directory = state_mod.state_dir()
    directory.mkdir(parents=True)
    (directory / f"{host}-s1.json").write_text(json.dumps({"approved": ["write:session"]}))
    # when
    output = guard.handle(bash_event("gh pr create"), host)
    # then
    assert decision_of(output) == ("allow" if host == "claude" else None)


@pytest.mark.parametrize("count", [0, 1, 2])
@pytest.mark.parametrize("prompt", ["승인", " 승인! ", "approve", "ApPrOvE。", "승인."])
def test_plain_approval_requires_one_request(state, count, prompt):
    """단독 승인 문장은 대기 요청이 정확히 하나일 때만 해당 요청을 승인한다."""
    # given
    for index in range(count):
        state_mod.request_code("codex", "s1", [f"always:{index}"], [])
    # when
    approved = state_mod.approve_text("codex", "s1", prompt)
    # then
    assert bool(approved) == (count == 1)
    assert len(state_mod._load("codex", "s1")["pending"]) == (0 if count == 1 else count)


@pytest.mark.parametrize("command", [
    "cat > f <<'EOF'\nkubectl delete pod x\n$(az account show)\npsql\nEOF",
    "cat >> f <<'X'\nkubectl delete pod x\nX", "tee f <<EOF\nkubectl delete pod x\nEOF",
    "python3 -c 's=\"kubectl delete pod x; az\"; print(s)'",
    "python3 - <<'PY'\ns = 'kubectl delete pod x; az'\nprint(s)\nPY",
    'az datafactory pipeline-run show --run-id "$R"', 'az datafactory trigger-run query-by-factory --factory-name "$F"',
    'az rest --method get --url "$B/x"', "psql -h localhost -c 'delete from t'", "PGHOST=127.0.0.1 psql",
    "psql -h ::1", "psql -h /var/run/postgresql", "mysql -h localhost -e 'select 1'",
    "redis-cli -h 127.0.0.1 get x", "mongosh mongodb://localhost/db --eval 'db.x.find()'",
    "git tag --list", "git tag -v v1", "git clean -nfd", "git restore --staged .", "git status",
    "gh pr view 1", "gh api /x", "gh api /x -X GET", "rm file", "rm -rf build", "rm -r /tmp/demo",
])
def test_benign_calls_do_not_ask(state, fake_bin, command):
    """데이터·순수 파이썬·변수 조회·로컬 DB와 안전한 로컬 작업은 질문하지 않는다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind in ("read", "pass")


@pytest.mark.parametrize("body,expected", [
    ('s="kubectl delete pod x"\nprint(s)', "pass"),
    ('import subprocess\ns="kubectl delete pod x"\nprint(s)', "pass"),
    ('import subprocess\nsubprocess.run(["echo", "x"])', "write"),
    ('from subprocess import run as invoke\ninvoke(["echo", "x"])', "write"),
    ('import subprocess\nsubprocess.run(["kubectl", "delete", "pod", "x"])', "always"),
    ('import azure.identity', "write"),
])
@pytest.mark.parametrize("mode", ["inline", "heredoc", "script"])
def test_python_execution_is_classified_by_behavior(state, fake_bin, body, expected, mode):
    """파이썬은 실행 방식에 관계없이 실제 프로세스와 SDK 호출 여부로 분류한다."""
    # given
    path = state / "tool.py"
    path.write_text(body)
    command = {"inline": "python3 -c " + shlex.quote(body), "heredoc": "python3 - <<'PY'\n" + body + "\nPY",
               "script": "python3 " + str(path)}[mode]
    expected = "read" if expected == "pass" and mode != "inline" and "import" not in body else expected
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize("header", ["#!/usr/bin/env node", "binary"])
def test_other_executables_are_not_scanned(state, header):
    """셸이나 파이썬이 아닌 실행 파일 내부의 CLI 단어는 검사하지 않는다."""
    # given
    executable = state / "tool"
    executable.write_text(header + "\nkubectl delete pod x\n")
    # when
    outcome = guard.classify_text("./tool --write src/a.tsx", str(state))
    # then
    assert outcome.kind == "pass"


@pytest.mark.parametrize("suffix,expected", [
    ("--add-dir ../outside", "write"), ("--add-dir .", "pass"), ("-C ../outside", "write"), ("--cd .", "pass"),
])
def test_codex_external_directories_need_approval(state, suffix, expected):
    """Codex 작업자가 세션 폴더 밖을 허용받으면 쓰기 승인을 요구한다."""
    # given
    command = "codex exec " + suffix + " task"
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize("operand", ["/", "~", ".", "..", "/opt/outside", "./.git", "$UNKNOWN", "$(pwd)", "/opt/*"])
def test_recursive_protected_removal_always_asks(state, operand):
    """보호 경로와 해석할 수 없는 경로의 재귀 삭제는 항상 승인을 요구한다."""
    # given
    command = "rm -rf " + operand
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "always"


@pytest.mark.parametrize("command,expected", [
    ("env | grep '^SAFE_DEMO='", "read"), ("printenv SAFE_DEMO", "read"), ("printenv DEMO_TOKEN", "sensitive"),
    ("env | rg '^DEMO_TOKEN='", "sensitive"), ("env | grep -c TOKEN", "read"), ("env | grep TOKEN | wc -l", "read"),
    ("env | grep '['", "sensitive"), ("env | grep '^SAFE_DEMO=' | sort | head -2", "read"),
])
def test_environment_filter_checks_matched_names(state, monkeypatch, command, expected):
    """환경 필터는 일치한 변수 이름과 개수 출력 여부에 따라 민감도를 결정한다."""
    # given
    monkeypatch.setenv("SAFE_DEMO", "value")
    monkeypatch.setenv("DEMO_TOKEN", "fixture-value")
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize("tool,arguments,expected", [
    ("getIssueLinkTypes", {}, "read"), ("get_x", {}, "read"), ("listX", {}, "read"), ("searchX", {}, "read"),
    ("atlassianUserInfo", {}, "read"), ("whoami", {}, "read"), ("unknown", {"action": "get"}, "read"),
    ("get_x", {"action": "create"}, "write"), ("get_x", {"action": "delete"}, "always"),
    ("getDeletedItems", {}, "read"), ("get_delete", {}, "always"), ("unknown", {}, "write"),
])
def test_mcp_action_and_read_names(state, tool, arguments, expected):
    """MCP는 명시된 동작과 읽기 동사를 우선하고 삭제 동작은 항상 승인받는다."""
    # given
    name = "mcp__demo__" + tool
    # when
    outcome = guard.classify_mcp(name, arguments)
    # then
    assert outcome.kind == expected


def test_internal_failure_stays_always(state):
    """분류기 내부 예외는 세션 승인으로 우회할 수 없다."""
    # given
    def broken():
        raise RuntimeError("failure")
    # when
    outcome = guard._classify_safely(broken, "demo")
    # then
    assert outcome.kind == "always"


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_session_approval_keeps_its_first_grant_after_days(state, fake_bin, monkeypatch, host):
    """세션 승인은 며칠이 지나도 유지되고 다시 승인해도 최초 승인 시각을 바꾸지 않는다."""
    # given
    clock = [100000.0]
    monkeypatch.setattr(state_mod.time, "time", lambda: clock[0])
    grant(host)
    clock[0] += 3 * 24 * 60 * 60
    grant(host)
    # when
    output = guard.handle(bash_event("gh pr create"), host)
    # then
    assert decision_of(output) == ("allow" if host == "claude" else None)
    assert state_mod._load(host, "s1")["approved_at"][state_mod.WRITE_KEY] == 100000.0


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_approving_mixed_call_also_approves_writes(state, fake_bin, host):
    """삭제와 쓰기가 섞인 호출을 승인하면 쓰기 부분은 세션 승인으로 남는다."""
    # given
    event = bash_event("kubectl apply -f a --context dev; kubectl delete pod x")
    guard.handle(event, host)
    if host == "claude":
        guard.handle({**event, "hook_event_name": "PostToolUse"}, host)
    else:
        state_mod.approve_text(host, "s1", "승인")
    # when
    output = guard.handle(bash_event("gh pr create"), host)
    # then
    assert decision_of(output) == ("allow" if host == "claude" else None)


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_marked_destructive_queries_still_ask(connections, project, fake_bin, host):
    """승인 표시 연결의 삭제 쿼리는 세션 승인 뒤에도 매번 승인을 요구한다."""
    # given
    grant(host)
    arguments = query_event(project, APPROVAL_ID, "DELETE FROM t")["tool_input"]
    event = {"hook_event_name": "PreToolUse", "tool_name": guard.TABULARIS_TOOL, "session_id": "s1",
             "tool_input": {"connection_id": "marked", "query": "DELETE FROM t"}}
    # when
    outputs = [guard.handle(event, host), datagrip_guard.decide(arguments, "s1") if host == "claude"
               else datagrip_guard.codex_pre_tool_use(arguments, "s1")]
    # then
    assert all(decision_of(output) == ("ask" if host == "claude" else "deny") for output in outputs)


@pytest.mark.parametrize("suffix,expected", [("--add-dir /opt/outside", "write"), ("--add-dir .", "pass")])
def test_role_runner_external_access_is_a_write(state, suffix, expected):
    """역할 실행기의 추가 디렉터리도 세션 밖이면 쓰기 승인을 요구한다."""
    # given
    command = "python3 /plugin/scripts/role_runner.py implementation " + suffix
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == expected


def test_session_project_directory_overrides_event_cwd(state, monkeypatch):
    """프로젝트 디렉터리가 설정되면 작업자 경로 비교는 이벤트 폴더 대신 프로젝트를 기준으로 한다."""
    # given
    project_dir = state / "project"
    project_dir.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_dir))
    # when
    outcome = guard.classify_text("codex exec --add-dir . task", str(state))
    # then
    assert outcome.kind == "write"


@pytest.mark.parametrize("command,expected", [
    ("TARGET=/opt/outside; rm -rf $TARGET", "always"), ("TARGET=build; rm -r $TARGET", "pass"),
    ("TARGET=/tmp/example; rm -r $TARGET", "pass"), ("rm -rf ~/.cache/example", "pass"),
    ("rm -rf build/*", "pass"), ("cd nested; rm -rf ..", "always"),
])
def test_recursive_removal_resolves_variables_and_directory(state, command, expected):
    """재귀 삭제는 앞선 변수 대입과 디렉터리 이동을 반영해 보호 경로를 판정한다."""
    # given
    (state / "nested").mkdir()
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize("area", ["pr", "issue", "release", "repo", "workflow", "secret", "variable", "label", "gist"])
@pytest.mark.parametrize("verb", ["create", "edit", "comment", "review", "close", "reopen", "ready", "merge", "run",
                                   "set", "upload", "transfer", "fork", "sync", "lock", "unlock", "delete"])
def test_gh_verbs_apply_to_every_area(state, area, verb):
    """GitHub CLI의 쓰기와 삭제 동사는 영역에 관계없이 같은 승인 정책을 따른다."""
    # given
    command = f"gh {area} {verb} item"
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == ("always" if verb == "delete" else "write")


@pytest.mark.parametrize("body,expected", [('s="kubectl delete pod x"; print(s)', "pass"),
                                          ('import subprocess; subprocess.run(["echo", "x"])', "write")])
def test_python_stdin_file_is_classified(state, body, expected):
    """표준 입력 파일로 받은 파이썬도 실제 프로세스 실행 여부로 분류한다."""
    # given
    (state / "program").write_text(body)
    # when
    outcome = guard.classify_text("python3 - < program", str(state))
    # then
    assert outcome.kind == expected


def test_shell_wrapped_python_strings_are_data(state):
    """하위 셸이 순수 파이썬을 실행해도 문자열 속 삭제 명령에는 승인을 요구하지 않는다."""
    # given
    inner = shlex.join(["python3", "-c", 's="kubectl delete pod x"; print(s)'])
    command = shlex.join(["bash", "-c", inner])
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "pass"


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("command", ["kubectl get secret db -o json", "python3 /plugin/scripts/approval_state.py"])
def test_blocked_calls_stay_blocked_after_approval(state, fake_bin, host, command):
    """비밀 출력과 자기 승인 시도는 세션 승인이 있어도 차단한다."""
    # given
    grant(host)
    event = bash_event(command)
    # when
    output = guard.handle(event, host)
    # then
    assert decision_of(output) == "deny"


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_reads_need_no_approval(state, fake_bin, host):
    """일반 조회는 세션 승인이 없어도 즉시 실행한다."""
    # given
    event = bash_event("kubectl get pods")
    # when
    output = guard.handle(event, host)
    # then
    assert decision_of(output) == ("allow" if host == "claude" else None)
    assert not state_mod._load(host, "s1")["approved"]


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_destructive_mcp_still_asks(state, fake_bin, host):
    """MCP 삭제 도구도 세션 승인 뒤에 별도 승인을 요구한다."""
    # given
    grant(host)
    event = {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "mcp__demo__deleteItem", "tool_input": {}}
    # when
    output = guard.handle(event, host)
    # then
    assert decision_of(output) == ("ask" if host == "claude" else "deny")


@pytest.mark.parametrize("option", ["-X POST", "--method=PATCH", "-f x=1", "-F x=1", "--field x=1", "--raw-field x=1", "--input body.json"])
def test_gh_api_write_options_need_session_approval(state, option):
    """GitHub API의 명시적 변경 메서드와 POST를 암시하는 인자는 모두 쓰기로 분류한다."""
    # given
    command = "gh api /x " + option
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "write"


@pytest.mark.parametrize("action", ["delete", "purge", "drop", "truncate", "destroy"])
def test_destructive_sdk_call_names_always_ask(state, action):
    """SDK 호출 이름에 파괴 동작이 포함되면 항상 승인을 요구한다."""
    # given
    command = "python3 -c " + shlex.quote(f"import boto3; boto3.client('s3').{action}_item()")
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "always"


@pytest.mark.parametrize("command,expected", [
    ("rm -rf build dist *.egg-info", "pass"), ("rm -rf src/*.pyc", "pass"), ("rm -rf *", "always"),
    ("rm -rf .git*", "always"), ("rm -rf /opt/*.log", "always"),
])
def test_recursive_glob_removal_judges_the_parent_folder(state, command, expected):
    """재귀 삭제의 glob이 마지막 이름에만 있으면 상위 폴더 안의 항목으로 보고, 폴더 전체나 .git을 지우는 패턴은 매번 묻는다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize("command,expected", [
    ("kubectl exec pod -- rm -rf /data", "always"),
    ("kubectl exec pod -- sh -c 'psql -c \"DROP TABLE t\"'", "always"),
    ("docker --context prod exec web rm -rf /srv", "always"),
    ("kubectl exec pod -- curl -s localhost", "write"),
])
def test_exec_with_destructive_inner_command_always_asks(state, fake_bin, command, expected):
    """파드나 컨테이너 안에서 되돌릴 수 없는 명령을 실행하면 매번 묻고, 그 밖의 exec는 세션 쓰기다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == expected


def test_missing_executable_is_left_to_the_host(state):
    """없는 실행 파일은 실행될 수 없으므로 쓰기로 묻지 않는다."""
    # given
    command = "./node_modules/.bin/prettier --write src/a.tsx"
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "pass"


@pytest.mark.parametrize("command", ["git restore src/a.py", "git clean -n", "git restore --staged ."])
def test_git_restore_and_clean_without_loss_are_left_to_the_host(state, command):
    """되돌릴 수 없는 손실이 없는 restore와 clean은 조회로 허용하지 않고 호스트 판단에 맡긴다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == "pass"


@pytest.mark.parametrize("command,expected", [
    ('az rest --method get --url "$B/x?api-version=1"', "read"),
    ("az rest --method get --url https://management.azure.com/subscriptions?api-version=2020-01-01", "read"),
    ("az rest --method get --url https://other.example.com/x", "write"),
    ("az rest --method get --url https://management.azure.com/x --resource https://other.example.com", "write"),
])
def test_az_rest_get_is_read_only_for_the_management_endpoint(state, fake_bin, command, expected):
    """az rest GET은 관리 엔드포인트나 풀 수 없는 변수 주소일 때만 조회이고, 다른 주소나 --resource 지정은 쓰기로 묻는다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize("command,expected", [
    ("gh api graphql -f query='query { viewer { login } }'", "read"),
    ("gh api graphql -f query='mutation { addStar(input: {}) { clientMutationId } }'", "write"),
    ("gh api graphql -F query=@q.graphql", "write"),
])
def test_gh_graphql_queries_are_reads_and_mutations_are_writes(state, command, expected):
    """gh api graphql의 query는 조회이고 mutation이나 파일로 넘긴 본문은 쓰기다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == expected


def test_failed_approved_write_still_grants_the_session_approval(state, fake_bin):
    """승인한 쓰기가 실패해도 Claude는 PostToolUseFailure에서 세션 승인을 기록해 다음 쓰기를 묻지 않는다."""
    # given
    first = bash_event("curl -X POST https://example.test/a", session="s1", cwd=state)
    guard.handle(first, "claude")
    guard.handle({**first, "hook_event_name": "PostToolUseFailure", "error": "Exit code 7"}, "claude")
    # when
    output = guard.handle(bash_event("curl -X POST https://example.test/b", session="s1", cwd=state), "claude")
    # then
    assert decision_of(output) == "allow"


def test_hooks_register_the_failure_event_like_post_tool_use():
    """hooks.json은 PostToolUseFailure를 PostToolUse와 같은 matcher로 승인 가드에 연결한다."""
    # given
    hooks = json.loads((Path(guard.__file__).resolve().parents[1] / "hooks/hooks.json").read_text())["hooks"]
    # when
    post = [entry for entry in hooks["PostToolUse"] if "approval_guard.py" in entry["hooks"][0]["command"]]
    failure = hooks.get("PostToolUseFailure", [])
    # then
    assert len(post) == 1 and len(failure) == 1
    assert failure[0]["matcher"] == post[0]["matcher"]
    assert "approval_guard.py" in failure[0]["hooks"][0]["command"]


@pytest.mark.parametrize("post", ["PostToolUse", "PostToolUseFailure"])
def test_unasked_inflight_write_does_not_regrant_the_approval(state, fake_bin, monkeypatch, post):
    """기존 승인으로 시작한 쓰기가 끝나도 승인을 새로 기록하지 않고 최초 승인 시각을 유지한다."""
    # given
    clock = [100000.0]
    monkeypatch.setattr(state_mod.time, "time", lambda: clock[0])
    grant("claude")
    event = bash_event("gh pr create", cwd=state, tool_use_id="allowed")
    guard.handle(event, "claude")
    clock[0] += 60
    # when
    guard.handle({**event, "hook_event_name": post}, "claude")
    # then
    data = state_mod._load("claude", "s1")
    assert data["approved"] == [state_mod.WRITE_KEY]
    assert data["approved_at"][state_mod.WRITE_KEY] == 100000.0
    assert data["asked"] == []


@pytest.mark.parametrize("post", ["PostToolUse", "PostToolUseFailure"])
def test_claude_grants_only_the_recorded_asked_call_once(state, fake_bin, monkeypatch, post):
    """Claude는 질문한 호출의 종료만 승인으로 기록하고 그 기록은 한 번만 사용한다."""
    # given
    clock = [100000.0]
    monkeypatch.setattr(state_mod.time, "time", lambda: clock[0])
    event = bash_event("gh pr create", cwd=state, tool_use_id="asked")
    guard.handle(event, "claude")
    guard.handle({**event, "hook_event_name": post, "tool_use_id": "other"}, "claude")
    before = state_mod._load("claude", "s1")
    guard.handle({**event, "hook_event_name": post}, "claude")
    granted = state_mod._load("claude", "s1")
    clock[0] += 60
    # when
    guard.handle({**event, "hook_event_name": post}, "claude")
    # then
    assert before["approved"] == []
    assert granted["approved_at"][state_mod.WRITE_KEY] == 100000.0
    assert granted["asked"] == []
    assert granted["request_counts"] == {}
    assert state_mod._load("claude", "s1")["approved_at"] == {state_mod.WRITE_KEY: 100000.0}


@pytest.mark.parametrize("header,expected", [
    ("python3 - <<'PY' && git push --force", "always"),
    ("gh repo archive owner/repo --yes; python3 - <<'PY'", "write"),
    ("cd x && python3 - <<'PY'", "read"),
    ("cd x && python3 - <<'PY' && git push --force", "always"),
])
def test_python_heredoc_keeps_other_header_segments(state, header, expected):
    """Python heredoc은 자기 세그먼트만 지우고 같은 줄의 다른 명령은 분류한다."""
    # given
    command = header + "\nprint(1)\nPY"
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize("shell", ["sh", "bash", "zsh"])
@pytest.mark.parametrize("body,expected", [("print('echo hello')", "write"),
                                          ("print('kubectl delete pod live')", "always")])
def test_python_heredoc_output_piped_to_shell_is_unclassified(state, shell, body, expected):
    """Python 출력을 셸로 실행하면 분류 불가 쓰기이며 파괴적 텍스트는 매번 묻는다."""
    # given
    command = "python3 - <<'PY' | " + shell + "\n" + body + "\nPY"
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize("command", [
    'env | grep -c "$(kubectl delete pod live)"',
    'env | grep -c "`kubectl delete pod live`"',
    'env | grep -c "$PATTERN"', "env | grep '^HOME=' | head .env",
    "env | grep '^HOME=' | sort .env", "env | grep '^HOME=' | wc -l .env",
    "env | grep '^HOME=' | head -n 2 .env", "env | grep '^HOME=' | head 2",
])
def test_environment_shortcut_declines_expansions_and_filter_file_operands(state, command):
    """환경 필터의 확장식과 파일 인자는 빠른 읽기 판정으로 우회하지 않는다."""
    # given
    text = command
    # when
    outcome = guard._environment_filter(text)
    # then
    assert outcome is None


@pytest.mark.parametrize("command", [
    'env | grep -c "$(kubectl delete pod live)"',
    'env | grep -c "`kubectl delete pod live`"', "env | grep '^HOME=' | head .env",
])
@pytest.mark.parametrize("host", ["claude", "codex"])
def test_environment_shortcut_cannot_hide_calls_requiring_each_approval(state, fake_bin, command, host):
    """환경 필터 뒤의 파괴 명령과 보호 파일 읽기는 세션 승인 뒤에도 매번 묻는다."""
    # given
    grant(host)
    event = bash_event(command, cwd=state)
    # when
    output = guard.handle(event, host)
    # then
    assert decision_of(output) == ("ask" if host == "claude" else "deny")


@pytest.mark.parametrize("function,keyword", [("subprocess.run", "args"), ("subprocess.Popen", "args"),
                                               ("subprocess.call", "args"), ("os.system", "command"),
                                               ("os.popen", "cmd")])
@pytest.mark.parametrize("inner,expected", [('kubectl get secret db -o json', "secret"),
                                          ('kubectl delete pod live', "always")])
def test_python_process_keyword_commands_are_classified(state, fake_bin, function, keyword, inner, expected):
    """키워드 인자로 전달한 Python 프로세스 명령도 비밀과 파괴 동작을 분류한다."""
    # given
    value = repr(shlex.split(inner) if keyword == "args" else inner)
    command = "python3 -c " + shlex.quote(f"import subprocess, os; {function}({keyword}={value})")
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize("body", [
    'import psycopg; conn = psycopg.connect("host=db"); conn.execute("DROP TABLE t")',
    'import sqlalchemy; conn.execute("DELETE FROM t")',
    'import pymysql; conn.execute("DROP DATABASE db")',
    'import psycopg2; conn.execute("DROP SCHEMA public")',
    'import psycopg; conn.execute("TRUNCATE TABLE t")',
    'import boto3; operation = "kubectl delete pod live"',
    'import subprocess; subprocess.run(["echo", "DROP TABLE t"])',
])
def test_python_process_or_sdk_destructive_text_always_asks(state, fake_bin, body):
    """프로세스를 실행하거나 SDK를 가져온 Python의 파괴적 텍스트는 매번 묻는다."""
    # given
    command = "python3 -c " + shlex.quote(body)
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "always"


@pytest.mark.parametrize("command", [
    "npm --registry=https://r.example publish", "pnpm --registry=https://r.example publish",
    "yarn --verbose npm publish", "uv --verbose publish", "poetry --no-interaction publish",
    "cargo --locked publish", "twine --verbose upload dist/*", "gem --verbose push x.gem",
])
def test_package_publishing_after_options_always_asks(state, command):
    """옵션 뒤에 오는 패키지 게시 동사도 매번 승인을 요구한다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == "always"


@pytest.mark.parametrize("command", [
    "codex -C /outside exec --dangerously-bypass-approvals-and-sandbox task",
    "codex --dangerously-bypass-hook-trust exec task", "codex --sandbox=danger-full-access e task",
    "codex -s danger-full-access task", "codex -c 'sandbox_mode=\"danger-full-access\"' task",
    "codex --config 'sandbox.mode=\"danger-full-access\"' exec task",
    "codex exec -s workspace-write -s danger-full-access task",
])
def test_codex_bypass_is_always_before_or_without_exec(state, command):
    """Codex 샌드박스 우회는 하위 명령의 위치나 유무와 관계없이 매번 묻는다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == "always"


@pytest.mark.parametrize("option", ["-c", "--config", "-C", "--cd", "--add-dir", "-s", "--sandbox", "-m", "--model",
                                    "-p", "--profile", "-i", "--image", "-a", "--ask-for-approval", "--enable",
                                    "--disable", "--local-provider", "-o", "--output-last-message", "--output-schema"])
@pytest.mark.parametrize("subcommand", ["exec", "e"])
def test_codex_global_options_do_not_hide_external_directories(state, option, subcommand):
    """Codex 전역 옵션의 값을 건너뛰어 exec와 e의 외부 폴더 쓰기를 찾는다."""
    # given
    command = f"codex {option} . --add-dir /outside {subcommand} task"
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "write"


@pytest.mark.parametrize("prefix", ["docker exec app", "docker exec -it -u root app", "podman exec app",
                                    "kubectl exec pod --", "oc exec pod --"])
@pytest.mark.parametrize("inner,expected", [("git reset --hard", "always"), ("git push --force", "always"),
                                          ("kubectl get secret db -o json", "secret")])
def test_container_exec_uses_inner_command_classifier(state, fake_bin, prefix, inner, expected):
    """컨테이너 exec의 내부 명령에도 일반 분류기를 적용해 파괴와 비밀 판정을 유지한다."""
    # given
    command = prefix + " " + inner
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize("sql,action,expected", [("UPDATE accounts SET enabled=false", "query", "write"),
                                               ("SELECT 1", "create", "read"), ("SELECT 1", "delete", "always"),
                                               ("DROP TABLE t", "query", "always")])
def test_mcp_sql_precedes_nondestructive_action(state, sql, action, expected):
    """MCP SQL은 비파괴적 action보다 우선하고 파괴적 action은 항상 묻는다."""
    # given
    arguments = {"action": action, "sql": sql}
    # when
    outcome = guard.classify_mcp("mcp__db__query", arguments)
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize("query,expected", [
    ("# comment\nmutation { addStar(input: {}) { clientMutationId } }", "write"),
    ("# comment\n query { viewer { login } }", "read"),
    ("# mutation is mentioned only in a comment\n { viewer { login } }", "read"),
    ("query { viewer { login } } mutation { deleteIssue(input: {}) { clientMutationId } }", "write"),
    ("fragment Demo on User { login }", "write"),
])
def test_graphql_read_requires_query_start_and_no_mutation(state, query, expected):
    """GraphQL은 주석 뒤의 시작 구문과 본문 전체의 mutation 단어로 읽기를 판정한다."""
    # given
    command = "gh api graphql -f " + shlex.quote("query=" + query)
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize("command,expected", [
    ("gh repo archive owner/repo --yes", "write"), ("gh extension install owner/ext", "write"),
    ("gh auth login", "write"), ("gh auth token", "secret"), ("gh unknown action", "write"),
    ("gh pr watch 1", "read"), ("gh repo browse", "read"), ("gh pr ls", "read"),
    ("gh status", "read"), ("gh version", "read"), ("gh --version", "read"), ("gh --help", "read"),
    ("gh auth status", "read"), ("gh config get editor", "read"), ("gh config list", "read"),
    ("gh pr checkout 1", "pass"), ("gh repo clone owner/repo", "pass"),
])
def test_gh_unknown_actions_are_writes_and_auth_token_is_secret(state, command, expected):
    """gh는 알려지지 않은 동작을 쓰기로 보고 인증 토큰 출력은 비밀로 차단한다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize("operand", [".git/objects", "./.git/refs/heads", "nested/.git/hooks", "git-link/objects",
                                     ".git/objects/*"])
def test_recursive_removal_protects_git_contents_after_resolution(state, operand):
    """재귀 삭제는 경로를 해석한 뒤 .git 안의 모든 하위 경로를 보호한다."""
    # given
    (state / ".git").mkdir()
    (state / "git-link").symlink_to(state / ".git", target_is_directory=True)
    command = "rm -rf " + operand
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "always"


GUARD_PATH = Path(__file__).resolve().parents[1] / "scripts" / "approval_guard.py"


def request_command(*keys):
    return shlex.join(["python3", str(GUARD_PATH), "request", *(arg for key in keys for arg in ("--key", key)),
                       "--why", "Read the deployment secret file"])


def approve_with_code(output, host, session="s1"):
    code = re.search(r"(?:승인|approve) ([A-Z2-9]{6})", output["hookSpecificOutput"]["permissionDecisionReason"])[1]
    return guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": session, "prompt": "승인 " + code}, host)


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_sensitive_session_요청은_한_번만_묻고_호출이_끝나면_민감_조회_세션_승인을_준다(state, fake_bin, host):
    """sensitive:session 사전 승인은 한 번만 묻고, 요청 호출이 끝나면 민감 조회 세션 승인만 부여한다."""
    # given
    event = bash_event(request_command("sensitive:session"))
    # when
    first = guard.handle(event, host)
    if host == "claude":
        guard.handle({**event, "hook_event_name": "PostToolUse"}, host)
    else:
        approve_with_code(first, host)
    read = guard.handle(bash_event("cat .env", cwd=str(state)), host)
    # then
    assert decision_of(first) == ("ask" if host == "claude" else "deny")
    assert state_mod.is_approved(host, "s1", [state_mod.SENSITIVE_KEY])
    assert not state_mod.is_approved(host, "s1", [state_mod.WRITE_KEY])
    assert decision_of(read) == ("allow" if host == "claude" else None)


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_두_키를_함께_요청하면_쓰기와_민감_조회_세션_승인을_모두_준다(state, fake_bin, host):
    """write:session과 sensitive:session을 함께 요청한 호출이 끝나면 두 세션 승인이 모두 기록된다."""
    # given
    event = bash_event(request_command("write:session", "sensitive:session"))
    # when
    first = guard.handle(event, host)
    if host == "claude":
        guard.handle({**event, "hook_event_name": "PostToolUse"}, host)
    else:
        approve_with_code(first, host)
    # then
    assert decision_of(first) == ("ask" if host == "claude" else "deny")
    assert state_mod.is_approved(host, "s1", [state_mod.WRITE_KEY, state_mod.SENSITIVE_KEY])


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("key", ["sensitive:0a1b2c3d", "sensitive:session@prod", "guard:unclassified:0a1b2c3d",
                                 "unclassified", "sensitive"])
def test_요청은_다이제스트형_민감_키와_허용되지_않은_키를_거부하고_기록하지_않는다(state, fake_bin, key, host):
    """sensitive:<digest>처럼 세션 키가 아닌 키는 사전 승인 요청으로 받지 않는다."""
    # given
    event = bash_event(request_command(key))
    # when
    output = guard.handle(event, host)
    guard.handle({**event, "hook_event_name": "PostToolUse"}, host)
    # then
    assert decision_of(output) == "deny"
    assert not state_mod.is_approved(host, "s1", [key])
    assert not state_mod.is_approved(host, "s1", [state_mod.SENSITIVE_KEY])


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_부모가_민감_조회_세션을_승인하면_자식의_cat_env가_이어서_실행된다(state, fake_bin, monkeypatch, host):
    """부모가 승인한 sensitive:session은 자식 세션의 민감 조회 cat .env를 허용한다."""
    # given
    monkeypatch.setenv("HEI5ENBUG_PARENT_SESSION", host + ":parent")
    state_mod.record_approved(host, "parent", [state_mod.SENSITIVE_KEY])
    event = bash_event("cat .env", session="child", cwd=str(state))
    # when
    output = guard.handle(event, host)
    # then
    assert guard.classify_text("cat .env", str(state)).kind == "sensitive"
    assert decision_of(output) == ("allow" if host == "claude" else None)


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_부모가_모든_세션_키를_승인해도_자식의_git_push_force는_부모_세션_사유로_거부된다(state, fake_bin, monkeypatch, host):
    """매번 묻는 git push --force는 부모의 세션 승인과 무관하게 자식에서 부모 세션 사유로 거부된다."""
    # given
    monkeypatch.setenv("HEI5ENBUG_PARENT_SESSION", host + ":parent")
    state_mod.record_approved(host, "parent", [state_mod.WRITE_KEY, state_mod.SENSITIVE_KEY])
    event = bash_event("git push --force origin main", session="child", cwd=str(state))
    # when
    output = guard.handle(event, host)
    # then
    assert decision_of(output) == "deny"
    assert output["hookSpecificOutput"]["permissionDecisionReason"] == state_mod.PARENT_REASON


def test_자식의_request는_종료_코드_2로_거부되고_키를_기록하지_않는다(state, monkeypatch):
    """자식 세션은 request 명령으로 사전 승인 키를 기록할 수 없고 종료 코드 2로 끝난다."""
    # given
    monkeypatch.setenv("HEI5ENBUG_PARENT_SESSION", "claude:parent")
    monkeypatch.setattr(sys, "argv", ["approval_guard.py", "request", "--key", "sensitive:session", "--why", "Read env"])
    # when
    code = guard.main()
    # then
    assert code == 2
    assert not state_mod.is_approved("claude", "parent", [state_mod.SENSITIVE_KEY])
