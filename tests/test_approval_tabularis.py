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
        {"id": "prodpg", "name": "acme-prod-pg", "params": {"driver": "postgresql", "password": PASSWORD}},
        {"id": "prodms", "name": "AcmeProdSQL", "params": {"driver": "sqlserver", "password": PASSWORD}},
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
    assert outcomes == ["read", "write", "forbidden", "write"]


@pytest.mark.parametrize(("connection", "sql", "expected"), [
    ("pg", "SELECT 1", "read"), ("demo postgres", "SELECT 1", "read"),
    ("ms", "DECLARE @v INT; SET @v = 1; SELECT @v", "read"), ("entra", "SELECT 1", "read"),
    ("pg", "INSERT INTO t VALUES (1)", "write"), ("ms", "UPDATE t SET a=1", "write"),
    ("marked", "SELECT 1", "forbidden"), ("운영 승인", "INSERT INTO t VALUES (1)", "write"),
    ("other", "SELECT 1", "write"), ("unknown", "SELECT 1", "write"),
    ("missing driver", "SELECT 1", "write"),
    ("pg", "SELECT 'delete'", "read"), ("pg", "SELECT 1 -- drop", "read"), ("pg", "SELECT 1; DROP TABLE t", "always"),
    ("ms", "SELECT 'delete' AS [delete] -- drop", "read"), ("ms", "SET NOCOUNT ON; SELECT 1", "read"),
    ("pg", "TRUNCATE t", "always"), ("pg", "DO $$ BEGIN NULL; END $$", "write"), ("prodpg", "DO $$ BEGIN NULL; END $$", "always"),
    ("pg", "CALL proc()", "always"), ("ms", "EXEC proc", "always"), ("entra", "EXECUTE proc", "always"),
    ("pg", "SELECT 'unterminated", "write"),
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


SAFE_DO = "DO $$ BEGIN UPDATE demo_items SET n = 1 WHERE id = 1; INSERT INTO demo_items (id) VALUES (2); COMMIT; END $$"


@pytest.mark.parametrize(("connection", "sql", "expected"), [
    ("pg", "DELETE FROM demo_items WHERE id = 1", "write"),
    ("pg", "DELETE FROM demo_items m USING demo_backup b WHERE m.id = b.id", "write"),
    ("pg", "WITH s AS (SELECT id FROM demo_backup) DELETE FROM demo_items USING s WHERE demo_items.id = s.id", "write"),
    ("pg", SAFE_DO, "write"),
    ("pg", "DO LANGUAGE plpgsql $body$ BEGIN PERFORM set_config('lock_timeout', '1s', false); END $body$", "write"),
    ("ms", "DELETE FROM demo_items WHERE id = 1", "always"),
    ("entra", "DELETE t FROM demo_items t JOIN demo_backup b ON t.id = b.id WHERE b.n = 1", "always"),
    ("pg", "DO $$ BEGIN IF true THEN NULL; END $$", "always"),
    ("pg", "DO $$ BEGIN PERFORM \"pg_terminate_backend\"(1); END $$", "always"),
    ("pg", "DELETE FROM demo_items", "always"),
    ("pg", "DELETE FROM demo_items -- WHERE id = 1", "always"),
    ("pg", "DELETE FROM demo_items USING (SELECT id FROM demo_backup WHERE n > 1) s", "always"),
    ("pg", "WITH s AS (SELECT id FROM demo_backup WHERE n > 1) DELETE FROM demo_items USING s", "always"),
    ("pg", "DELETE FROM demo_items WHERE id = 1; DROP TABLE demo_backup", "always"),
    ("pg", "DROP TABLE demo_items", "always"),
    ("pg", "TRUNCATE demo_items", "always"),
    ("pg", "CALL demo_proc()", "always"),
    ("pg", "DO $$ BEGIN DROP TABLE demo_items; END $$", "always"),
    ("pg", "DO $$ BEGIN EXECUTE 'DELETE FROM demo_items WHERE id = 1'; END $$", "always"),
    ("pg", "DO $$ BEGIN DELETE FROM demo_items; END $$", "always"),
    ("pg", "DO $$ BEGIN NULL; END $$; TRUNCATE demo_items", "always"),
    ("pg", "DO $$ BEGIN PERFORM $1; END $$", "always"),
    ("ms", "DELETE FROM demo_items", "always"),
    ("ms", "EXEC demo_proc", "always"),
    ("entra", "EXECUTE demo_proc", "always"),
    ("prodpg", "DELETE FROM demo_items WHERE id = 1", "always"),
    ("prodpg", SAFE_DO, "always"),
    ("marked", "DELETE FROM demo_items WHERE id = 1", "always"),
    ("marked", SAFE_DO, "always"),
    ("prodms", "DELETE FROM demo_items WHERE id = 1", "always"),
    ("other", "DELETE FROM demo_items WHERE id = 1", "always"),
    ("unknown", "DELETE FROM demo_items WHERE id = 1", "always"),
])
def test_tabularis_waives_only_targeted_postgres_writes_on_development_connections(
        connections, connection, sql, expected):
    """tabularis는 개발 연결의 WHERE 있는 DELETE와 안전한 DO만 세션 쓰기로 낮추고 운영·미확인 연결과 나머지는 매번 묻는다."""
    # given
    arguments = {"connection_id": connection, "query": sql}
    # when
    outcome = guard.classify_mcp(TOOL, arguments)
    # then
    assert (outcome.kind, outcome.every_time) == (expected, expected == "always")
    if expected == "write":
        assert outcome.keys == ["mcp:session"]


@pytest.mark.parametrize(("host", "approved_decision", "asked_decision"), [("claude", "allow", "ask"), ("codex", None, "deny")])
def test_tabularis_targeted_delete_follows_the_session_write_approval_on_each_host(
        connections, host, approved_decision, asked_decision):
    """tabularis의 WHERE 있는 DELETE는 두 호스트 모두 세션 쓰기 승인을 따르고, WHERE 없는 DELETE는 승인 뒤에도 다시 묻는다."""
    # given
    def event(sql):
        return {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": TOOL,
                "tool_input": {"connection_id": "pg", "query": sql}}
    state_mod.record_approved(host, "s1", [state_mod.WRITE_KEY])
    # when
    approved = guard.handle(event("DELETE FROM demo_items WHERE id = 1"), host)
    asked = guard.handle(event("DELETE FROM demo_items"), host)
    # then
    assert (approved["hookSpecificOutput"]["permissionDecision"] if approved else None) == approved_decision
    assert asked["hookSpecificOutput"]["permissionDecision"] == asked_decision


@pytest.mark.parametrize("contents", [None, "{invalid", "{}", "null", '[{"id":"p","name":"broken","params":null}]'])
def test_tabularis_missing_or_unreadable_metadata_always_asks(connections, contents):
    """tabularis 연결 파일이 없거나 해석할 수 없으면 읽기 쿼리도 세션 쓰기 승인을 요구한다."""
    # given
    if contents is None:
        connections.unlink()
    else:
        connections.write_text(contents)
    # when
    outcome = guard.classify_mcp(TOOL, {"connection_id": "p", "query": "SELECT 1"})
    # then
    assert outcome.kind == "write"
    assert outcome.keys == ["mcp:session"]


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
    outcome = guard.classify_mcp(TOOL, {"connection_id": "p", "query": "UPDATE t SET a=1"})
    # then
    assert outcome.kind == "write"
    assert outcome.keys == ["mcp:session"]


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
def test_tabularis_production_reads_ignore_mcp_session_approval(connections, host):
    """tabularis의 운영 연결 조회는 세션 쓰기 승인이 있어도 계획 없이는 거부한다."""
    # given
    state_mod.record_approved(host, "s1", [state_mod.WRITE_KEY])
    event = {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": TOOL,
             "tool_input": {"connection_id": "marked", "query": "SELECT 1", "limit": 5}}
    # when
    output = guard.handle(event, host)
    # then
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "EXPLAIN (FORMAT JSON) SELECT 1" in output["hookSpecificOutput"]["permissionDecisionReason"]
    assert PASSWORD not in json.dumps(output)


def test_tabularis_success_uses_the_shared_approval_post_handler(connections):
    """질문한 tabularis 쓰기가 완료되면 공통 세션 쓰기 승인으로 기록한다."""
    # given
    event = {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": TOOL,
             "tool_input": {"connection_id": "pg", "query": "UPDATE t SET a=1"}}
    guard.handle({**event, "hook_event_name": "PreToolUse"}, "claude")
    # when
    guard.handle(event, "claude")
    # then
    assert state_mod._load("claude", "s1")["approved"] == [state_mod.WRITE_KEY]


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
