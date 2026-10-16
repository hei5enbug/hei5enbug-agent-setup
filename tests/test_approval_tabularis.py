import json
from pathlib import Path

import pytest

from test_approval_guard import guard, state, state_mod


TOOL = "mcp__tabularis__run_query"
PASSWORD = "tabularis-password-must-never-appear"


@pytest.fixture
def connections(state, monkeypatch):
    directory = state / "tabularis"
    directory.mkdir()
    monkeypatch.setenv("HEI5ENBUG_TABULARIS_DIR", str(directory))
    entries = [
        {"id": "pg", "name": "demo postgres", "params": {"driver": "postgresql", "password": PASSWORD}},
        {"id": "ms", "name": "demo sqlserver", "params": {"driver": "sqlserver", "password": PASSWORD}},
        {"id": "entra", "name": "demo entra", "params": {"driver": "sqlserver-entra", "password": PASSWORD}},
        {"id": "marked", "name": "운영 승인", "params": {"driver": "postgresql", "password": PASSWORD}},
        {"id": "other", "name": "demo sqlite", "params": {"driver": "sqlite", "password": PASSWORD}},
        {"id": "broken", "name": "missing driver", "params": None},
    ]
    path = directory / "connections.json"
    path.write_text(json.dumps(entries))
    return path


def test_tabularis_reads_the_object_form_of_connections_file(connections):
    """실제 tabularis는 connections.json을 groups·connections·tags를 가진 객체로 저장하므로 그 형식도 읽는다."""
    # given
    entries = json.loads(connections.read_text())
    connections.write_text(json.dumps({"groups": [], "connections": entries, "tags": []}))
    # when
    outcomes = [guard.classify_tabularis({"connection_id": name, "query": sql}).kind for name, sql in [
        ("pg", "SELECT 1"), ("demo postgres", "UPDATE t SET a=1"), ("marked", "SELECT 1"), ("unknown", "SELECT 1")]]
    # then
    assert outcomes == ["read", "write", "always", "always"]


@pytest.mark.parametrize(("connection", "sql", "expected"), [
    ("pg", "SELECT 1", "read"), ("demo postgres", "SELECT 1", "read"),
    ("ms", "DECLARE @v INT; SET @v = 1; SELECT @v", "read"), ("entra", "SELECT 1", "read"),
    ("pg", "INSERT INTO t VALUES (1)", "write"), ("ms", "UPDATE t SET a=1", "write"),
    ("marked", "SELECT 1", "always"), ("운영 승인", "INSERT INTO t VALUES (1)", "always"),
    ("other", "SELECT 1", "always"), ("unknown", "SELECT 1", "always"),
    ("missing driver", "SELECT 1", "always"),
    ("pg", "SELECT 'delete'", "always"), ("pg", "SELECT 1 -- drop", "always"),
    ("pg", "TRUNCATE t", "always"), ("pg", "DO $$ BEGIN NULL; END $$", "always"),
    ("pg", "CALL proc()", "always"), ("ms", "EXEC proc", "always"), ("entra", "EXECUTE proc", "always"),
    ("pg", "SELECT 'unterminated", "always"),
])
def test_tabularis_uses_connection_metadata_and_the_matching_sql_classifier(connections, connection, sql, expected):
    """tabularis는 연결 이름과 드라이버에 따라 SQL을 읽기·쓰기·항상 승인으로 분류한다."""
    # given
    arguments = {"connection_id": connection, "query": sql, "limit": 10}
    # when
    outcome = guard.classify_mcp(TOOL, arguments)
    # then
    assert outcome.kind == expected
    assert PASSWORD not in repr(outcome)
    if expected == "write":
        assert outcome.keys == ["mcp:session"]
    if expected == "always":
        resolved = {"운영 승인": "marked", "missing driver": "broken"}.get(connection, connection)
        assert outcome.keys[0].startswith(f"sql:always:tabularis:{resolved}:")


@pytest.mark.parametrize("contents", [None, "{invalid", "{}", "null", '[{"id":"p","name":"broken","params":null}]'])
def test_tabularis_missing_or_unreadable_metadata_always_asks(connections, contents):
    """tabularis 연결 파일이 없거나 해석할 수 없으면 읽기 쿼리도 항상 승인을 요구한다."""
    # given
    if contents is None:
        connections.unlink()
    else:
        connections.write_text(contents)
    # when
    outcome = guard.classify_mcp(TOOL, {"connection_id": "p", "query": "SELECT 1"})
    # then
    assert outcome.kind == "always"
    assert outcome.keys[0].startswith("sql:always:tabularis:")


def test_tabularis_projects_only_id_name_and_driver(connections):
    """tabularis 연결 조회 결과에는 id·name·driver 세 필드만 남긴다."""
    # given
    connection_id = "pg"
    # when
    connection = guard.tabularis_connection(connection_id)
    # then
    assert connection == ("pg", "demo postgres", "postgresql")
    assert PASSWORD not in repr(connection)


@pytest.mark.parametrize(("platform", "environment", "relative"), [
    ("darwin", {}, "Library/Application Support/tabularis"),
    ("linux", {}, ".config/tabularis"),
    ("linux", {"XDG_CONFIG_HOME": "config-home"}, "config-home/tabularis"),
    ("win32", {"APPDATA": "roaming"}, "roaming/tabularis"),
])
def test_tabularis_resolves_each_platform_config_directory(state, monkeypatch, platform, environment, relative):
    """tabularis 연결 파일은 운영체제별 설정 폴더에서 찾는다."""
    # given
    monkeypatch.delenv("HEI5ENBUG_TABULARIS_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(state))
    monkeypatch.setattr(guard.sys, "platform", platform)
    for key, value in environment.items():
        monkeypatch.setenv(key, str(state / value))
    path = state / relative / "connections.json"
    path.parent.mkdir(parents=True)
    path.write_text('[{"id":"p","name":"승인 DB","params":{"driver":"postgresql"}}]')
    # when
    outcome = guard.classify_mcp(TOOL, {"connection_id": "p", "query": "SELECT 1"})
    # then
    assert outcome.kind == "always"
    assert outcome.keys[0].startswith("sql:always:tabularis:p:")


@pytest.mark.parametrize("tool", ["list_connections", "list_databases", "list_tables", "get_table_schema"])
def test_other_tabularis_tools_keep_the_read_name_rules(connections, tool):
    """tabularis의 다른 조회 도구는 기존 이름 규칙대로 승인 없이 읽는다."""
    # given
    name = "mcp__tabularis__" + tool
    # when
    outcome = guard.classify_mcp(name, {})
    # then
    assert outcome.kind == "read"


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_tabularis_marked_reads_ignore_mcp_session_approval(connections, host):
    """tabularis의 승인 표시 연결은 MCP 세션 승인이 있어도 읽기마다 승인을 요구한다."""
    # given
    state_mod.record_approved(host, "s1", ["mcp:session"])
    event = {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": TOOL,
             "tool_input": {"connection_id": "marked", "query": "SELECT 1", "limit": 5}}
    # when
    output = guard.handle(event, host)
    # then
    assert output["hookSpecificOutput"]["permissionDecision"] == ("ask" if host == "claude" else "deny")
    assert PASSWORD not in json.dumps(output)


def test_tabularis_success_uses_the_shared_approval_post_handler(connections):
    """tabularis 쓰기가 완료되면 기존 MCP 세션 승인 처리로 기록한다."""
    # given
    event = {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": TOOL,
             "tool_input": {"connection_id": "pg", "query": "UPDATE t SET a=1"}}
    # when
    guard.handle(event, "claude")
    # then
    assert state_mod.is_approved("claude", "s1", ["mcp:session"])


def test_database_tool_priority_fits_the_existing_instruction_budget():
    """DB 조회 지침은 tabularis·DataGrip·비밀 전달 CLI 순서를 짧은 길이 안에서 명시한다."""
    # given
    path = Path(__file__).resolve().parents[1] / "instructions/infrastructure-access.md"
    # when
    text = path.read_text()
    # then
    assert "tabularis" in text and "list_connections" in text and "run_query" in text
    assert "small `limit`" in text
    assert text.index("tabularis") < text.index("DataGrip") < text.index("secret_exec")
    assert len(text.splitlines()) <= 25
