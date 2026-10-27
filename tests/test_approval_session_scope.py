"""Acceptance checks: the opt-in `session` approval scope asks once per session except for three critical kinds."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import approval_guard as guard  # noqa: E402
import approval_state as state_mod  # noqa: E402
import datagrip_guard  # noqa: E402
import db_read_policy  # noqa: E402

PROD_ID = "11111111-1111-4111-8111-111111111111"
STAGING_ID = "22222222-2222-4222-8222-222222222222"
FIRST = "kubectl apply -f a --context demo-dev -n web"
NONPROD_DELETE = "kubectl delete pod x --context demo-dev -n web"
EVERY_TIME = "curl -X DELETE https://example.com/item"
JIRA_TOOL = "mcp__claude_ai_Atlassian__createJiraIssue"
CODE = re.compile(r"(?:승인|approve) ([A-Z2-9]{6})")
CRITICAL_COMMANDS = [
    "git reset --hard",
    "git clean -fd",
    "git checkout -- file",
    "git checkout .",
    "git restore file",
    "git worktree remove --force x",
    "git worktree remove -f x",
    "kubectl delete pod x --context demo-prod -n web",
    "kubectl delete pod x --context mystery -n web",
    "kubectl delete pod x -n web",
    "helm uninstall rel --kube-context demo-prod -n web",
    "aws ec2 terminate-instances --instance-ids i-1 --profile demo-prod --region us-east-1",
    "psql -h demo-prod-db -d app -c 'DROP TABLE t'",
    "terraform destroy",
    "terraform apply -destroy",
    "terraform apply -auto-approve -destroy",
]
PRODUCTION_SQL = ["DELETE FROM t WHERE id = 1", "DROP TABLE t", "TRUNCATE t"]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
    monkeypatch.setenv("HEI5ENBUG_RESPONSE_LANGUAGE", "English")
    state_mod.prompt_language.cache_clear()
    for name in ("HEI5ENBUG_PARENT_SESSION", "KUBECONFIG", "AWS_PROFILE", "AWS_REGION", "CLOUDSDK_CORE_PROJECT",
                 "DOCKER_CONTEXT", "PLUGIN_ROOT", "CLAUDE_PROJECT_DIR", "HEI5ENBUG_LANGUAGE",
                 "CLAUDE_PLUGIN_OPTION_APPROVAL_SCOPE", "HEI5ENBUG_APPROVAL_SCOPE", "PGHOST", "PGDATABASE",
                 "PGSERVICE", "HELM_KUBECONTEXT", "HEI5ENBUG_TABULARIS_DIR"):
        monkeypatch.delenv(name, raising=False)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("kubectl", "az"):
        (bin_dir / name).write_text("#!/bin/sh\necho fake\n")
        (bin_dir / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    return tmp_path


def use_scope(monkeypatch, value):
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_APPROVAL_SCOPE", value)
    monkeypatch.setenv("HEI5ENBUG_APPROVAL_SCOPE", value)


@pytest.fixture
def session_scope(home, monkeypatch):
    use_scope(monkeypatch, "session")
    return home


@pytest.fixture
def project(home):
    root = home / "project"
    (root / ".idea").mkdir(parents=True)
    (root / ".idea" / "dataSources.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<project version="4">\n'
        '  <component name="DataSourceManagerImpl" format="xml" multifile-model="true">\n'
        f'    <data-source source="LOCAL" name="demo-prod" uuid="{PROD_ID}"><driver-ref>postgresql</driver-ref></data-source>\n'
        f'    <data-source source="LOCAL" name="demo-staging2" uuid="{STAGING_ID}"><driver-ref>postgresql</driver-ref></data-source>\n'
        "  </component>\n</project>\n",
        encoding="utf-8",
    )
    return root


def bash(command, name="PreToolUse", session="s1", cwd=None):
    event = {"hook_event_name": name, "tool_name": "Bash", "tool_input": {"command": command}, "session_id": session}
    return {**event, "cwd": str(cwd)} if cwd is not None else event


def mcp(tool, name="PreToolUse", session="s1"):
    return {"hook_event_name": name, "tool_name": tool, "tool_input": {"title": "t"}, "session_id": session}


def query(project, connection_id, sql, name="PreToolUse", session="s1"):
    return {
        "hook_event_name": name, "tool_name": datagrip_guard.TOOL_NAME, "session_id": session,
        "tool_input": {"projectPath": str(project), "connectionId": connection_id, "queryText": sql},
    }


def decision(output):
    return output["hookSpecificOutput"]["permissionDecision"] if output else None


def reason(output):
    return output["hookSpecificOutput"]["permissionDecisionReason"]


def completed(event, host="claude"):
    """Ask, then record the way the host does after the user approves and the call completes."""
    asked = guard.handle(event, host)
    guard.handle({**event, "hook_event_name": "PostToolUse"}, host)
    return asked


def approved(session="s1", host="claude"):
    return state_mod._load(host, session)["approved"]


def approve_code(output, session="s1", host="codex"):
    prompt = f"승인 {CODE.search(reason(output)).group(1)}"
    guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": session, "prompt": prompt}, host)


def test_기본_범위는_tiered라_세션_쓰기_승인_뒤에도_매번_묻는다(home):
    # given
    completed(bash(FIRST))
    # when
    output = guard.handle(bash(NONPROD_DELETE), "claude")
    # then
    assert decision(output) == "ask"
    assert "Asks every time" in reason(output)
    assert state_mod.ALL_KEY not in approved()


def test_session_범위는_첫_승인이_끝나면_이후_묻는_호출을_모두_허용한다(session_scope, project):
    # given
    first = completed(bash(FIRST))
    assert decision(first) == "ask" and reason(first).startswith("Session approval: ")
    assert "Approve once" in reason(first) and "will not ask" in reason(first)
    assert state_mod.ALL_KEY in approved()
    # when
    later = {
        "write": bash("helm upgrade rel chart --kube-context demo-dev -n web"),
        "sensitive": bash("printenv"),
        "nonprod kubectl delete": bash(NONPROD_DELETE),
        "every-time": bash(EVERY_TIME),
        "mcp write": mcp(JIRA_TOOL),
        "mcp delete": mcp("mcp__demo__delete_item"),
        "nonprod sql": query(project, STAGING_ID, "DELETE FROM t"),
        "nonprod drop": query(project, STAGING_ID, "DROP TABLE t"),
    }
    results = {label: decision(guard.handle(event, "claude")) for label, event in later.items()}
    # then
    assert results == {label: "allow" for label in later}


def test_session_범위는_첫_질문이_민감_조회여도_이후_쓰기를_허용한다(session_scope):
    completed(bash("printenv"))
    assert decision(guard.handle(bash(FIRST), "claude")) == "allow"


def test_session_범위는_승인_전에는_묻고_승인이_끝나기_전에는_허용하지_않는다(session_scope):
    first = guard.handle(bash(FIRST), "claude")
    assert decision(first) == "ask"
    assert decision(guard.handle(bash(NONPROD_DELETE), "claude")) == "ask"


def test_session_범위의_다른_세션은_승인을_물려받지_않는다(session_scope):
    completed(bash(FIRST))
    assert decision(guard.handle(bash(NONPROD_DELETE, session="s2"), "claude")) == "ask"


@pytest.mark.parametrize("command", CRITICAL_COMMANDS)
def test_session_범위에서도_작업_버리기와_운영_인프라_삭제는_매번_묻는다(session_scope, command):
    # given
    completed(bash(FIRST, cwd=session_scope))
    event = bash(command, cwd=session_scope)
    # when
    outcomes = [guard.classify_text(command, str(session_scope))]
    first = completed(event)
    second = guard.handle(event, "claude")
    # then
    assert outcomes[0].critical and outcomes[0].every_time
    assert decision(first) == "ask" and "Asks every time" in reason(first)
    assert decision(second) == "ask"
    assert state_mod.ALL_KEY in approved()


@pytest.mark.parametrize("sql", PRODUCTION_SQL)
def test_session_범위에서도_운영_연결의_파괴적_sql은_매번_묻는다(session_scope, project, sql):
    # given
    completed(bash(FIRST))
    event = query(project, PROD_ID, sql)
    # when
    first = completed(event)
    second = guard.handle(event, "claude")
    # then
    assert datagrip_guard.classify_query(event["tool_input"]).critical
    assert decision(first) == "ask" and "Asks every time" in reason(first)
    assert decision(second) == "ask"


def test_tiered_범위는_작업_버리기를_새로_묻지_않는다(home):
    for command in ("git checkout -- file", "git restore file", "git worktree remove --force x"):
        assert guard.classify_text(command, str(home)).kind == "pass"
    assert guard.classify_text("git reset --hard", str(home)).kind == "always"


def test_크리티컬_승인은_그_호출만_덮고_세션_승인을_만들지_않는다(session_scope):
    # given
    first = completed(bash("git reset --hard", cwd=session_scope))
    # when
    later = guard.handle(bash(NONPROD_DELETE), "claude")
    # then
    assert "Asks every time" in reason(first)
    assert state_mod.ALL_KEY not in approved()
    assert decision(later) == "ask" and reason(later).startswith("Session approval: ")


def test_운영이_아닌_삭제와_깨끗한_작업은_크리티컬이_아니다(session_scope, project):
    nonprod = guard.classify_text(NONPROD_DELETE, str(session_scope))
    assert nonprod.kind == "always" and nonprod.every_time and not nonprod.critical
    assert not datagrip_guard.classify_query(query(project, STAGING_ID, "DELETE FROM t")["tool_input"]).critical
    assert not guard.classify_text("git push --force origin main", str(session_scope)).critical


def test_크리티컬은_복합_명령에서_하나만_있어도_유지된다(session_scope):
    outcome = guard.classify_text(f"{NONPROD_DELETE} && git clean -fd", str(session_scope))
    assert outcome.critical and outcome.kind == "always"


def test_session_범위에서_거부는_승인_뒤에도_거부로_남는다(session_scope):
    # given
    completed(bash(FIRST))
    state_file = state_mod.state_dir() / "claude-s1.json"
    denied = [
        bash("kubectl get secret db -o json --context demo-dev -n web"),
        bash(f"touch {state_file}"),
        {"hook_event_name": "PreToolUse", "tool_name": "Write", "session_id": "s1",
         "tool_input": {"file_path": str(state_file), "content": "x"}},
    ]
    # when
    results = [decision(guard.handle(event, "claude")) for event in denied]
    # then
    assert results == ["deny"] * len(denied)


def test_session_범위에서도_같은_크리티컬_호출을_세_번_넘게_묻지_않는다(session_scope):
    event = bash("git reset --hard", cwd=session_scope)
    results = [decision(guard.handle(event, "claude")) for _ in range(4)]
    assert results == ["ask", "ask", "ask", "deny"]


def test_session_범위의_알_수_없는_세션은_기억하지_않는다(session_scope):
    event = {**bash(NONPROD_DELETE), "session_id": None}
    assert decision(guard.handle(event, "claude")) == "ask"
    assert decision(guard.handle({**event, "hook_event_name": "PostToolUse"}, "claude")) is None
    assert decision(guard.handle(event, "claude")) == "ask"


def test_session_범위의_claude_권한_요청도_같은_검사를_거친다(session_scope):
    # given
    request = lambda command: guard.handle(bash(command, "PermissionRequest", cwd=session_scope), "claude")
    assert request(NONPROD_DELETE) is None
    completed(bash(FIRST))
    # when
    allowed = request(NONPROD_DELETE)
    # then
    assert allowed["hookSpecificOutput"]["decision"]["behavior"] == "allow"
    assert request("git reset --hard") is None
    assert request("kubectl delete pod x --context demo-prod -n web") is None


def test_session_범위의_파일_편집_질문은_세션_승인으로_이어진다(session_scope, monkeypatch):
    # given
    folder = session_scope / "work"
    folder.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(folder))
    event = lambda name: {"hook_event_name": name, "tool_name": "Write", "session_id": "s1", "cwd": str(folder),
                          "tool_input": {"file_path": str(folder / "a.txt"), "content": "x"}}
    # when
    asked = guard.handle(event("PermissionRequest"), "claude")
    guard.handle(event("PostToolUse"), "claude")
    # then
    assert asked is None
    assert state_mod.ALL_KEY in approved()
    assert guard.handle(bash(NONPROD_DELETE, "PermissionRequest"), "claude")["hookSpecificOutput"]["decision"]


def test_session_범위는_한도_파일_변경도_같은_검사를_거친다(session_scope):
    command = f"tee {db_read_policy.limits_path()}"
    outcome = guard._limits_command_outcome(command, str(session_scope))
    assert outcome.every_time and not outcome.critical
    assert decision(guard.handle(bash(command), "claude")) == "ask"
    completed(bash(FIRST))
    assert decision(guard.handle(bash(command), "claude")) == "allow"


def test_session_범위의_codex는_승인_한_번_뒤_비크리티컬을_통과시킨다(session_scope):
    # given
    first = guard.handle(bash(FIRST), "codex")
    assert decision(first) == "deny" and "rest of this session" in reason(first)
    approve_code(first)
    guard.handle(bash(FIRST), "codex")
    guard.handle(bash(FIRST, "PostToolUse"), "codex")
    # when
    later = guard.handle(bash(NONPROD_DELETE), "codex")
    permission = guard.handle(bash(NONPROD_DELETE, "PermissionRequest"), "codex")
    # then
    assert state_mod.ALL_KEY in approved(host="codex")
    assert later is None
    assert permission["hookSpecificOutput"]["decision"]["behavior"] == "allow"
    assert state_mod.permission_allowed("codex", "s1", guard.classify_text(EVERY_TIME, str(session_scope)))


def test_session_범위의_codex는_크리티컬마다_새_코드를_요구한다(session_scope):
    # given
    first = guard.handle(bash(FIRST), "codex")
    approve_code(first)
    command = "kubectl delete pod x --context demo-prod -n web"
    # when
    ask = guard.handle(bash(command), "codex")
    approve_code(ask)
    run = guard.handle(bash(command), "codex")
    guard.handle(bash(command, "PostToolUse"), "codex")
    again = guard.handle(bash(command), "codex")
    # then
    assert decision(ask) == "deny" and "Approval required" in reason(ask) and "rest of this session" not in reason(ask)
    assert run is None
    assert decision(again) == "deny" and "Approval required" in reason(again)
    assert not state_mod.permission_allowed("codex", "s1", guard.classify_text(command, str(session_scope)))


def test_session_범위의_codex는_크리티컬_승인으로_세션_승인을_만들지_않는다(session_scope):
    ask = guard.handle(bash("git reset --hard", cwd=session_scope), "codex")
    approve_code(ask)
    assert state_mod.ALL_KEY not in approved(host="codex")
    assert decision(guard.handle(bash(NONPROD_DELETE), "codex")) == "deny"


@pytest.mark.parametrize("parent_host", ["claude", "codex"])
@pytest.mark.parametrize("host", ["claude", "codex"])
def test_자식_세션은_부모의_세션_승인으로_비크리티컬만_허용한다(home, monkeypatch, parent_host, host):
    # given
    monkeypatch.setenv("PLUGIN_ROOT", str(REPO_ROOT)) if host == "codex" else None
    state_mod.record_approved(parent_host, "parent", [state_mod.ALL_KEY])
    monkeypatch.setenv("HEI5ENBUG_PARENT_SESSION", f"{parent_host}:parent")
    # when
    allowed = guard.handle(bash(NONPROD_DELETE, session="child"), host)
    critical = [guard.handle(bash(command, session="child", cwd=home), host)
                for command in ("git reset --hard", "kubectl delete pod x --context demo-prod -n web")]
    # then
    assert not state_mod.session_scope()
    assert (decision(allowed) == "allow") if host == "claude" else allowed is None
    assert [decision(output) for output in critical] == ["deny", "deny"]


def test_자식_세션은_부모에_세션_승인이_없으면_tiered처럼_거부한다(session_scope, monkeypatch):
    monkeypatch.setenv("HEI5ENBUG_PARENT_SESSION", "claude:parent")
    assert decision(guard.handle(bash(NONPROD_DELETE, session="child"), "claude")) == "deny"


def test_부모에_세션_승인이_없으면_자식_옵션이_session이어도_다른_계열_부모를_넓히지_않는다(home, monkeypatch):
    # given
    monkeypatch.setenv("PLUGIN_ROOT", str(REPO_ROOT))
    monkeypatch.setenv("HEI5ENBUG_APPROVAL_SCOPE", "session")
    state_mod.record_approved("claude", "parent", [state_mod.WRITE_KEY])
    monkeypatch.setenv("HEI5ENBUG_PARENT_SESSION", "claude:parent")
    # when
    output = guard.handle(bash(NONPROD_DELETE, session="child"), "codex")
    # then
    assert decision(output) == "deny"


@pytest.mark.parametrize("value", ["", "bogus", "tiered", "all"])
def test_알_수_없는_옵션_값은_tiered로_동작한다(home, monkeypatch, value):
    # given
    use_scope(monkeypatch, value)
    completed(bash(FIRST))
    # when
    output = guard.handle(bash(NONPROD_DELETE), "claude")
    # then
    assert not state_mod.session_scope()
    assert decision(output) == "ask" and "Asks every time" in reason(output)
    assert state_mod.ALL_KEY not in approved()


def test_codex는_codex_환경_변수에서_범위를_읽는다(home, monkeypatch):
    monkeypatch.setenv("PLUGIN_ROOT", str(REPO_ROOT))
    monkeypatch.setenv("HEI5ENBUG_APPROVAL_SCOPE", "session")
    assert state_mod.session_scope()
    monkeypatch.setenv("HEI5ENBUG_APPROVAL_SCOPE", "tiered")
    assert not state_mod.session_scope()


@pytest.mark.parametrize("name", ["example-test2", "example-qa", "example-staging3", "demo-dev12", "local1"])
def test_숫자_접미사가_붙은_개발_단어도_운영이_아니다(name):
    assert not db_read_policy.is_production(name)


@pytest.mark.parametrize("name", ["example-prod2", "example-cluster9", "", None, "example-prod2-test1", "dev-prd3"])
def test_숫자_접미사가_붙은_운영_단어와_알_수_없는_이름은_운영이다(name):
    assert db_read_policy.is_production(name)


def fake_kubectl(home, context):
    script = home / "bin" / "kubectl"
    script.write_text(f'#!/bin/sh\ncase "$*" in *current-context*) echo {context};; *) echo fake;; esac\n')
    script.chmod(0o755)


@pytest.mark.parametrize("command", [
    "PGHOST=demo-prod psql -d demo-dev -c 'DROP TABLE t'",
    "env PGHOST=demo-prod psql -d demo-dev -c 'DROP TABLE t'",
    "PGDATABASE=demo-prod psql -h demo-dev -c 'DROP TABLE t'",
    "psql -d demo-dev -c 'DROP TABLE t'",
    "PGSERVICE=demo-prod psql -h demo-dev -c 'DROP TABLE t'",
    "sqlcmd -d demo-dev -Q 'DROP TABLE t'",
    "SQLCMDSERVER=demo-prod sqlcmd -d demo-dev -Q 'DROP TABLE t'",
])
def test_데이터베이스_환경_변수와_알_수_없는_호스트는_운영으로_본다(session_scope, command):
    outcome = guard.classify_text(command, str(session_scope))
    assert outcome.kind == "always" and outcome.critical


def test_데이터베이스_환경_변수가_개발_대상이면_크리티컬이_아니다(session_scope, monkeypatch):
    monkeypatch.setenv("PGHOST", "demo-dev")
    monkeypatch.setenv("PGDATABASE", "demo-dev")
    assert not guard.classify_text("psql -c 'DROP TABLE t'", str(session_scope)).critical
    assert not guard.classify_text("psql -h demo-dev -d demo-dev -c 'DROP TABLE t'", str(session_scope)).critical


def test_helm_컨텍스트_환경_변수도_운영이면_크리티컬이다(session_scope, monkeypatch):
    # given
    fake_kubectl(session_scope, "demo-dev")
    classify = lambda command: guard.classify_text(command, str(session_scope))
    # then
    assert not classify("helm uninstall rel -n web").critical
    assert classify("HELM_KUBECONTEXT=demo-prod helm uninstall rel -n web").critical
    assert not classify("HELM_KUBECONTEXT=demo-prod helm uninstall rel --kube-context demo-dev -n web").critical
    monkeypatch.setenv("HELM_KUBECONTEXT", "demo-prod")
    assert classify("helm uninstall rel -n web").critical


@pytest.mark.parametrize("command", [
    "git restore --pathspec-from-file=paths.txt",
    "git restore --pathspec-from-file paths.txt",
    "git checkout --pathspec-from-file=paths.txt",
    "git checkout HEAD --pathspec-from-file=paths.txt",
])
def test_pathspec_파일로_작업을_버리는_호출도_범위에_따라_매번_묻는다(home, monkeypatch, command):
    # given
    assert guard.classify_text(command, str(home)).kind == "pass"
    use_scope(monkeypatch, "session")
    # when
    outcome = guard.classify_text(command, str(home))
    # then
    assert outcome.kind == "always" and outcome.critical and outcome.every_time
    assert not guard.classify_text("git restore --staged --pathspec-from-file=paths.txt", str(home)).critical


@pytest.mark.parametrize("command", [
    "psql -h demo-prod -f cleanup.sql",
    "psql -h demo-dev -f cleanup.sql",
    "mysql -h demo-dev -e 'INSERT INTO t VALUES (1)'",
    "kubectl get pods 'unterminated",
    "bash ./missing-script.sh",
])
def test_session_범위의_분류_실패는_모두_매번_묻는_크리티컬이다(session_scope, command):
    # given
    outcome = guard.classify_text(command, str(session_scope))
    completed(bash(FIRST))
    event = bash(command, cwd=session_scope)
    # when
    results = [decision(guard.handle(event, "claude")) for _ in range(2)]
    # then
    assert outcome.kind == "always" and outcome.critical and outcome.every_time
    assert results == ["ask", "ask"]


def test_tiered_범위의_분류_실패는_그대로_쓰기_승인을_따른다(home):
    outcome = guard.classify_text("mysql -h demo-dev -e 'INSERT INTO t VALUES (1)'", str(home))
    assert outcome.kind == "write" and not outcome.every_time


def test_session_범위의_알_수_없는_데이터_연결은_매번_묻는_크리티컬이다(session_scope, project):
    # given
    completed(bash(FIRST))
    unknown = query(project, "33333333-3333-4333-8333-333333333333", "INSERT INTO t VALUES (1)")
    # when
    outcome = datagrip_guard.classify_query(unknown["tool_input"])
    # then
    assert outcome.kind == "always" and outcome.critical and outcome.every_time
    assert decision(guard.handle(unknown, "claude")) == "ask"


def test_session_범위의_알_수_없는_tabularis_연결은_매번_묻는_크리티컬이다(session_scope, monkeypatch):
    # given
    folder = session_scope / "tabularis"
    folder.mkdir()
    (folder / "connections.json").write_text(
        '[{"id": "c1", "name": "demo-dev", "params": {"driver": "mystery"}}]', encoding="utf-8")
    monkeypatch.setenv("HEI5ENBUG_TABULARIS_DIR", str(folder))
    # when
    outcome = guard.classify_tabularis({"connection_id": "c1", "query": "INSERT INTO t VALUES (1)"})
    # then
    assert outcome.kind == "always" and outcome.critical and outcome.every_time


COMPOUND = "git clean -fd && kubectl apply -f a --context demo-dev"


def test_session_범위의_크리티컬_복합_호출_승인은_세션_승인을_남기지_않는다(session_scope):
    # given
    first = completed(bash(COMPOUND, cwd=session_scope))
    # when
    later = guard.handle(bash(FIRST), "claude")
    # then
    assert decision(first) == "ask"
    assert approved() == []
    assert decision(later) == "ask" and reason(later).startswith("Session approval: ")


def test_session_범위의_codex_크리티컬_복합_호출_승인은_그_호출만_덮는다(session_scope):
    # given
    ask = guard.handle(bash(COMPOUND, cwd=session_scope), "codex")
    approve_code(ask)
    # when
    run = guard.handle(bash(COMPOUND, cwd=session_scope), "codex")
    guard.handle(bash(COMPOUND, "PostToolUse", cwd=session_scope), "codex")
    # then
    assert run is None
    assert approved(host="codex") == []
    assert decision(guard.handle(bash(FIRST), "codex")) == "deny"


def test_tiered_범위의_크리티컬_복합_호출_승인은_쓰기_승인을_남긴다(home):
    completed(bash(COMPOUND, cwd=home))
    assert state_mod.WRITE_KEY in approved()
    assert decision(guard.handle(bash(FIRST), "claude")) == "allow"


def test_다른_질문이_세션_승인을_주어도_한도가_찬_호출은_다음_사용자_메시지까지_거부된다(session_scope):
    # given
    asked = [decision(guard.handle(bash(NONPROD_DELETE), "claude")) for _ in range(3)]
    completed(bash(FIRST))
    assert state_mod.ALL_KEY in approved()
    # when
    stopped = guard.handle(bash(NONPROD_DELETE), "claude")
    guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "continue"}, "claude")
    after_prompt = guard.handle(bash(NONPROD_DELETE), "claude")
    # then
    assert asked == ["ask"] * 3
    assert decision(stopped) == "deny"
    assert decision(after_prompt) == "allow"


def run_git(root, *args):
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    subprocess.run(["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com", "-c", "commit.gpgsign=false",
                    "-C", str(root), *args], check=True, capture_output=True, env=env)


def make_repo(root):
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "build").mkdir()
    (root / "src" / "app.py").write_text("print(1)\n", encoding="utf-8")
    (root / "src" / "clean.py").write_text("print(2)\n", encoding="utf-8")
    (root / "docs" / "guide.md").write_text("guide\n", encoding="utf-8")
    (root / ".gitignore").write_text("build/\n", encoding="utf-8")
    run_git(root, "init", "-q", "-b", "main")
    run_git(root, "add", ".")
    run_git(root, "commit", "-q", "-m", "init")
    (root / "build" / "out.o").write_text("object\n", encoding="utf-8")
    return root


@pytest.fixture
def repo(session_scope):
    return make_repo(session_scope / "repo")


@pytest.fixture
def dirty(repo):
    (repo / "src" / "app.py").write_text("print(3)\n", encoding="utf-8")
    (repo / "docs" / "notes.txt").write_text("notes\n", encoding="utf-8")
    return repo


def classify_in(command, folder):
    return guard.classify_text(command, str(folder))


def assert_every_time_critical(outcome):
    assert outcome.kind == "always" and outcome.critical and outcome.every_time
    assert guard.DISCARD_LABEL in outcome.descriptions


@pytest.mark.parametrize("command", [
    "rm src/app.py",
    "rm -f src/app.py",
    "rm -rf src",
    "rm -r src/",
    "rm -rf docs",
    "rm docs/notes.txt",
    "rm -rf docs/notes.txt",
    "rm src/*.py",
    "rm -rf .",
])
def test_session_범위에서_수정된_추적_파일과_추적되지_않은_파일의_삭제는_매번_묻는다(dirty, command):
    # given
    completed(bash(FIRST, cwd=dirty))
    event = bash(command, cwd=dirty)
    # when
    outcome = classify_in(command, dirty)
    results = [decision(guard.handle(event, "claude")) for _ in range(2)]
    # then
    assert_every_time_critical(outcome)
    assert results == ["ask", "ask"]
    assert state_mod.ALL_KEY in approved()


def test_session_범위에서_다른_git_루트의_변경된_작업_삭제도_매번_묻는다(repo, dirty, session_scope):
    # given
    other = make_repo(session_scope / "other")
    (other / "src" / "app.py").write_text("print(9)\n", encoding="utf-8")
    run_git(repo, "stash", "-q")
    clean_cwd = repo
    completed(bash(FIRST, cwd=clean_cwd))
    command = f"rm -rf {other / 'src'}"
    # when
    outcome = classify_in(command, clean_cwd)
    results = [decision(guard.handle(bash(command, cwd=clean_cwd), "claude")) for _ in range(2)]
    # then
    assert_every_time_critical(outcome)
    assert results == ["ask", "ask"]


def test_session_범위에서_스테이지된_변경이_있는_파일의_삭제도_매번_묻는다(repo):
    # given
    (repo / "src" / "app.py").write_text("print(4)\n", encoding="utf-8")
    run_git(repo, "add", "src/app.py")
    # when
    outcome = classify_in("rm src/app.py", repo)
    # then
    assert_every_time_critical(outcome)


@pytest.mark.parametrize("command", [
    "rm src/clean.py",
    "rm -f src/clean.py",
    "rm -rf build",
    "rm build/out.o",
    "rm -rf build/out.o",
])
def test_session_범위에서_깨끗한_추적_파일과_무시된_빌드_산출물의_삭제는_크리티컬이_아니다(repo, command):
    # given
    completed(bash(FIRST, cwd=repo))
    # when
    outcome = classify_in(command, repo)
    # then
    assert not outcome.critical and not outcome.every_time
    assert decision(guard.handle(bash(command, cwd=repo), "claude")) in (None, "allow")


def test_session_범위에서_다른_파일이_변경돼_있어도_삭제_대상이_깨끗하면_크리티컬이_아니다(dirty):
    assert not classify_in("rm src/clean.py", dirty).critical
    assert not classify_in("rm -rf build", dirty).critical


def test_session_범위에서_작업_트리_밖_경로의_삭제는_그대로다(session_scope):
    # given
    outside = session_scope / "plain"
    outside.mkdir()
    (outside / "a.txt").write_text("a\n", encoding="utf-8")
    # when
    outcome = classify_in("rm -rf plain", session_scope)
    # then
    assert not outcome.critical


def test_session_범위에서_git_상태를_알_수_없으면_삭제는_매번_묻는다(repo, monkeypatch):
    # given
    monkeypatch.setattr(guard, "_git_probe", lambda *args: None)
    # when
    outcomes = [classify_in(command, repo) for command in ("rm src/clean.py", "rm -rf build")]
    # then
    for outcome in outcomes:
        assert_every_time_critical(outcome)


def test_session_범위에서_git_조회가_시간_초과되면_삭제는_매번_묻는다(repo, monkeypatch):
    # given
    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 3)
    monkeypatch.setattr(guard.subprocess, "run", slow)
    # when
    outcome = classify_in("rm src/clean.py", repo)
    # then
    assert_every_time_critical(outcome)


def test_session_범위에서_이전_명령이_파일을_바꿀_수_있으면_무시된_파일만_크리티컬이_아니다(repo):
    # given
    first = classify_in("touch marker && rm src/clean.py", repo)
    second = classify_in("touch marker && rm build/out.o", repo)
    # then
    assert_every_time_critical(first)
    assert not second.critical


def test_session_범위에서_git_밖_폴더_아래_저장소의_변경된_작업_삭제는_매번_묻는다(session_scope, monkeypatch):
    # given
    workspace = session_scope / "workspace"
    inner = make_repo(workspace / "inner")
    (inner / "src" / "app.py").write_text("print(5)\n", encoding="utf-8")
    monkeypatch.setattr(guard, "_temporary", lambda path, env: False)
    # when
    dirty_outcome = classify_in("rm -rf workspace", session_scope)
    run_git(inner, "checkout", "-q", "--", "src/app.py")
    clean_outcome = classify_in("rm -rf workspace", session_scope)
    # then
    assert_every_time_critical(dirty_outcome)
    assert not clean_outcome.critical


@pytest.mark.parametrize("command", [
    "find . -name '*.py' -delete",
    "find src -name app.py -delete",
    "find . -name app.py -exec rm {} \\;",
    "find docs -type f -delete",
    "find . -name app.py -fprint out.txt -delete",
])
def test_session_범위에서_find_삭제도_변경된_작업이_걸리면_매번_묻는다(dirty, command):
    assert_every_time_critical(classify_in(command, dirty))


@pytest.mark.parametrize("command", [
    "find . -name '*.pyc' -delete",
    "find build -name '*.o' -delete",
    "find src -name clean.py -delete",
    "find . -name app.py",
])
def test_session_범위에서_find는_지워지는_파일이_깨끗하거나_삭제가_없으면_크리티컬이_아니다(dirty, command):
    assert not classify_in(command, dirty).critical


@pytest.mark.parametrize("command", ["git rm -f src/app.py", "git rm -rf src", "git rm --force docs/guide.md src/app.py"])
def test_session_범위에서_강제_git_rm은_수정된_추적_파일이면_매번_묻는다(dirty, command):
    outcome = classify_in(command, dirty)
    assert outcome.kind == "always" and outcome.critical and outcome.every_time


@pytest.mark.parametrize("command", [
    "git rm --cached src/app.py",
    "git rm -f --cached src/app.py",
    "git rm src/app.py",
    "git rm -f src/clean.py",
    "git rm -fn src/app.py",
])
def test_session_범위에서_캐시만_지우거나_깨끗한_git_rm은_크리티컬이_아니다(dirty, command):
    assert not classify_in(command, dirty).critical


CREDENTIAL_PROMPT_CONFIG = {
    "GIT_CONFIG_COUNT": "2",
    "GIT_CONFIG_KEY_0": "credential.interactive",
    "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "credential.guiPrompt",
    "GIT_CONFIG_VALUE_1": "false",
}


def test_상속된_GIT_CONFIG가_자격_증명_프롬프트만_끄면_깨끗한_git_rm은_크리티컬이_아니다(dirty, monkeypatch):
    # given
    for name, value in CREDENTIAL_PROMPT_CONFIG.items():
        monkeypatch.setenv(name, value)
    # when
    outcome = classify_in("git rm -f src/clean.py", dirty)
    # then
    assert not outcome.critical


@pytest.mark.parametrize("assignments", [
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.worktree GIT_CONFIG_VALUE_0=../other",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/tmp/work/hooks",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.rm GIT_CONFIG_VALUE_0='!rm -rf src'",
    "GIT_CONFIG_COUNT=3 GIT_CONFIG_KEY_0=credential.interactive GIT_CONFIG_VALUE_0=false"
    " GIT_CONFIG_KEY_1=credential.guiPrompt GIT_CONFIG_VALUE_1=false"
    " GIT_CONFIG_KEY_2=core.worktree GIT_CONFIG_VALUE_2=../other",
    "GIT_CONFIG_COUNT=x GIT_CONFIG_KEY_0=credential.interactive GIT_CONFIG_VALUE_0=false",
    "GIT_CONFIG_COUNT=0",
    "GIT_CONFIG_KEY_1=core.worktree",
    "GIT_CONFIG_PARAMETERS=\"'core.worktree'='../other'\"",
])
def test_명령에_붙은_GIT_CONFIG는_상속된_자격_증명_설정이_있어도_강제_git_rm을_크리티컬로_만든다(dirty, monkeypatch, assignments):
    # given
    for name, value in CREDENTIAL_PROMPT_CONFIG.items():
        monkeypatch.setenv(name, value)
    # when
    outcome = classify_in(f"{assignments} git rm -f src/clean.py", dirty)
    # then
    assert outcome.critical


@pytest.mark.parametrize("extra", [
    {"GIT_CONFIG_COUNT": "3", "GIT_CONFIG_KEY_2": "core.hooksPath", "GIT_CONFIG_VALUE_2": "/tmp/work/hooks"},
    {"GIT_CONFIG_KEY_2": "alias.rm", "GIT_CONFIG_VALUE_2": "!rm -rf src"},
    {"GIT_CONFIG_PARAMETERS": "'core.worktree'='../other'"},
])
def test_상속된_GIT_CONFIG에_다른_키가_섞이면_강제_git_rm은_크리티컬이다(dirty, monkeypatch, extra):
    # given
    for name, value in {**CREDENTIAL_PROMPT_CONFIG, **extra}.items():
        monkeypatch.setenv(name, value)
    # when
    outcome = classify_in("git rm -f src/clean.py", dirty)
    # then
    assert outcome.critical


def test_session_범위의_삭제_검사는_같은_명령_안에서_저장소마다_한_번만_상태를_읽는다(dirty, monkeypatch):
    # given
    calls = []
    original = guard._git_probe
    monkeypatch.setattr(guard, "_git_probe", lambda directory, env, *args: calls.append(args) or original(directory, env, *args))
    # when
    outcome = classify_in("rm src/app.py; rm src/app.py", dirty)
    # then
    assert outcome.critical
    assert sum("status" in args for args in calls) == 1


@pytest.mark.parametrize("command", [
    "rm src/app.py",
    "rm -rf src",
    "rm -rf docs",
    "find . -name app.py -delete",
    "git rm -f src/app.py",
])
def test_tiered_범위의_삭제_분류는_바뀌지_않고_git을_읽지_않는다(home, monkeypatch, command):
    # given
    repo_root = make_repo(home / "repo")
    (repo_root / "src" / "app.py").write_text("print(3)\n", encoding="utf-8")
    (repo_root / "docs" / "notes.txt").write_text("notes\n", encoding="utf-8")
    monkeypatch.setattr(guard, "_git_probe", lambda *args: pytest.fail("tiered scope must not probe git"))
    # when
    outcome = classify_in(command, repo_root)
    # then
    assert outcome.kind == "pass" and not outcome.critical and not outcome.every_time
