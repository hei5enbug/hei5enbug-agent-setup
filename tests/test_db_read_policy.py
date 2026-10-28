import csv
import io
import json
import time

import pytest

from test_approval_guard import bash_event, datagrip_guard, guard, state, state_mod

import datagrip_sql  # noqa: E402
import db_read_policy as policy  # noqa: E402

TABULARIS = "mcp__tabularis__run_query"
DATAGRIP = datagrip_guard.TOOL_NAME
READ = "SELECT id, name FROM orders WHERE id = 7"
PLAN_JSON = json.dumps([{"Plan": {"Node Type": "Seq Scan", "Total Cost": 123.4, "Plan Rows": 56}}])
PLAN_TEXT_LINES = ["Limit  (cost=0.00..4278.65 rows=1 width=52)", "  ->  Seq Scan on orders  (cost=0.00..9.00 rows=3)"]
PG_DEV, PG_PROD, MS_PROD, MS_DEV, PG_APPROVAL = "11111111-0000-4000-8000-000000000001", \
    "11111111-0000-4000-8000-000000000002", "11111111-0000-4000-8000-000000000003", \
    "11111111-0000-4000-8000-000000000004", "11111111-0000-4000-8000-000000000005"


@pytest.fixture(autouse=True, params=["parser", "regex"])
def sql_parser(request, monkeypatch):
    if request.param == "regex":
        monkeypatch.setattr(datagrip_sql, "pglast_parser", None)
    return request.param


@pytest.fixture(autouse=True)
def config_home(state, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(state / "config"))
    return state / "config" / "hei5enbug-agent-setup"


@pytest.fixture
def limits_file(config_home):
    config_home.mkdir(parents=True)
    return config_home / "db-read-limits.json"


@pytest.fixture
def connections(state, monkeypatch):
    directory = state / "tabularis"
    directory.mkdir()
    monkeypatch.setenv("HEI5ENBUG_TABULARIS_DIR", str(directory))
    entries = [
        {"id": "devpg", "name": "demo-dev-pg", "params": {"driver": "postgresql"}},
        {"id": "prodpg", "name": "AcmeProdPG", "params": {"driver": "postgresql"}},
        {"id": "prodms", "name": "acme-prod-sql", "params": {"driver": "sqlserver"}},
        {"id": "devms", "name": "Acme Dev SQL", "params": {"driver": "sqlserver"}},
        {"id": "approval", "name": "Acme 운영 승인 DB", "params": {"driver": "postgresql"}},
    ]
    (directory / "connections.json").write_text(json.dumps(entries))
    return directory


@pytest.fixture
def project(state):
    root = state / "project"
    (root / ".idea").mkdir(parents=True)
    sources = [(PG_DEV, "demo-dev-pg", "postgresql"), (PG_PROD, "AcmeProdPG", "postgresql"),
               (MS_PROD, "acme-prod-sql", "sqlserver.ms"), (MS_DEV, "Acme Dev SQL", "sqlserver.ms"),
               (PG_APPROVAL, "Acme 운영 승인 DB", "postgresql")]
    body = "".join(f'<data-source name="{name}" uuid="{uuid}"><driver-ref>{driver}</driver-ref></data-source>'
                   for uuid, name, driver in sources)
    (root / ".idea" / "dataSources.xml").write_text(f"<project><component>{body}</component></project>")
    return root


def tabularis_event(connection, query, name="PreToolUse", session="s1", response=None, **extra):
    event = {"hook_event_name": name, "session_id": session, "tool_name": TABULARIS,
             "tool_input": {"connection_id": connection, "query": query, **extra}}
    if response is not None:
        event["tool_response"] = response
    return event


def datagrip_event(project, connection, query, name="PreToolUse", session="s1", response=None):
    event = {"hook_event_name": name, "session_id": session, "tool_name": DATAGRIP,
             "tool_input": {"projectPath": str(project), "connectionId": connection, "queryText": query}}
    if response is not None:
        event["tool_response"] = response
    return event


def tabularis_result(cell_rows):
    return [{"type": "text", "text": json.dumps({"columns": ["QUERY PLAN"], "rows": cell_rows, "affected_rows": 0,
                                                 "truncated": False, "pagination": None})}]


def datagrip_result(cells, header="QUERY PLAN"):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([header])
    for cell in cells:
        writer.writerow([cell])
    return [{"type": "text", "text": json.dumps({"resultSetId": "r1", "text": buffer.getvalue()})}]


def plan_form(read=READ):
    return f"EXPLAIN (FORMAT JSON) {read}"


def decision(output):
    return output["hookSpecificOutput"]["permissionDecision"] if output else None


def reason(output):
    return output["hookSpecificOutput"]["permissionDecisionReason"]


def updated(output):
    return output["hookSpecificOutput"].get("updatedInput")


def record(connection="prodpg", read=READ, cost=100.0, rows=10.0, tool="tabularis", host="claude", session="s1"):
    state_mod.store_plan(host, session, tool, connection, policy.read_digest(read), cost, rows)


class TestSanitizedDestructiveCheck:
    @pytest.mark.parametrize("sql", [
        "SELECT CASE WHEN note LIKE '%delete%' THEN 'delete' ELSE 'keep' END AS action FROM dbo.Jobs",
        "SELECT 1 AS id -- delete this later\nFROM dbo.Jobs",
        "SELECT 1 /* drop truncate delete */ AS id",
        "SELECT [delete], [drop table] FROM dbo.[truncate]",
        "SELECT \"delete\" FROM dbo.Jobs",
        "SELECT is_deleted, delete_flag, dropped_at FROM dbo.Jobs",
    ])
    def test_sql_server_keywords_in_literals_comments_and_identifiers_are_reads(self, sql):
        """SQL Server 조회에서 delete 등이 리터럴·주석·식별자에만 있으면 파괴적이 아니라 읽기다."""
        # given
        postgres = False
        # when
        destructive, read = datagrip_guard.is_destructive(sql, postgres), datagrip_guard.is_read(sql, postgres)
        # then
        assert destructive is False
        assert read is True

    @pytest.mark.parametrize("sql", [
        "SELECT 1; DELETE FROM dbo.Jobs", "DROP TABLE dbo.Jobs", "TRUNCATE TABLE dbo.Jobs",
        "SELECT 'x' AS a; delete from dbo.Jobs -- cleanup", "EXEC dbo.Cleanup",
        "SELECT 1 AS insert, 2 AS delete",
    ])
    def test_bare_keywords_in_code_stay_destructive_or_not_read(self, sql):
        """코드에 delete·drop·truncate가 그대로 있거나 EXEC로 시작하면 읽기가 아니다."""
        # given
        postgres = False
        # when
        read = datagrip_guard.is_read(sql, postgres)
        # then
        assert read is False
        assert datagrip_guard.is_destructive(sql, postgres) is True

    def test_tabularis_and_datagrip_classify_the_keyword_reads_as_reads(self, connections, project):
        """같은 SQL을 tabularis와 DataGrip 분류기가 모두 읽기로 본다."""
        # given
        sql = "SELECT CASE WHEN st.text LIKE '%delete%' THEN 'delete' END AS action FROM dbo.Jobs st"
        # when
        tabularis = guard.classify_mcp(TABULARIS, {"connection_id": "devms", "query": sql})
        datagrip = datagrip_guard.classify_query(datagrip_event(project, MS_DEV, sql)["tool_input"])
        # then
        assert (tabularis.kind, datagrip.kind) == ("read", "read")

    def test_unterminated_text_keeps_the_raw_destructive_check(self):
        """정리할 수 없는 SQL은 원문에 delete가 있으면 파괴적으로 본다."""
        # given
        sql = "SELECT 'unterminated; DELETE FROM dbo.Jobs"
        # when
        destructive = datagrip_guard.is_destructive(sql, False)
        # then
        assert destructive is True


class TestSqlServerSessionStatements:
    @pytest.mark.parametrize("statement", [
        "SET NOCOUNT ON", "set nocount off", "SET LOCK_TIMEOUT 5000", "SET LOCK_TIMEOUT -1",
        "SET DEADLOCK_PRIORITY LOW", "SET DEADLOCK_PRIORITY NORMAL", "SET DEADLOCK_PRIORITY -5",
        "SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED", "SET TRANSACTION ISOLATION LEVEL READ COMMITTED",
        "SET TRANSACTION ISOLATION LEVEL SNAPSHOT",
        "SET ARITHABORT ON", "SET ANSI_NULLS OFF", "SET ANSI_WARNINGS ON", "SET ANSI_PADDING ON",
        "SET QUOTED_IDENTIFIER ON", "SET CONCAT_NULL_YIELDS_NULL OFF", "SET XACT_ABORT ON",
        "SET STATISTICS IO ON", "SET STATISTICS TIME OFF",
        "SET SHOWPLAN_XML ON", "SET SHOWPLAN_ALL OFF", "SET SHOWPLAN_TEXT ON",
    ])
    def test_listed_session_statements_count_as_reads_beside_a_read(self, statement):
        """허용 목록의 SET 문은 다른 문이 모두 읽기일 때 읽기로 센다."""
        # given
        sql = f"{statement};\nSELECT id FROM dbo.Jobs"
        # when
        read = datagrip_guard.is_read(sql, False)
        # then
        assert read is True

    @pytest.mark.parametrize("sql", [
        "SET NOCOUNT ON; DELETE FROM dbo.Jobs", "SET NOCOUNT ON; UPDATE dbo.Jobs SET a = 1",
        "SET IDENTITY_INSERT dbo.Jobs ON; SELECT 1", "SET LOCK_TIMEOUT abc; SELECT 1",
        "SET DEADLOCK_PRIORITY HIGH; SELECT 1", "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE; SELECT 1",
        "SET ANSI_NULLS MAYBE; SELECT 1", "SET ROWCOUNT 0; SELECT 1", "SET NOCOUNT ON; EXEC dbo.Run",
    ])
    def test_other_set_statements_and_mixed_writes_are_not_reads(self, sql):
        """목록에 없는 SET 문이나 쓰기가 섞인 묶음은 읽기가 아니다."""
        # given
        postgres = False
        # when
        read = datagrip_guard.is_read(sql, postgres)
        # then
        assert read is False

    def test_session_settings_reports_the_bounds_a_read_already_sets(self):
        """읽기가 이미 정한 LOCK_TIMEOUT과 DEADLOCK_PRIORITY를 알려 준다."""
        # given
        sql = "set lock_timeout 30000;\nSET DEADLOCK_PRIORITY NORMAL;\nSELECT 1"
        # when
        found = datagrip_guard.session_settings(sql)
        # then
        assert found == {"lock_timeout", "deadlock_priority"}


class TestConnectionEnvironment:
    @pytest.mark.parametrize("name", [
        "demo-dev-pg", "AcmeDev", "acme_test_db", "ACME QA", "AcmeStaging", "acme.stg.pg", "[Sandbox] acme",
        "Acme Local", "acme-stage", "AcmeDevelopment", "AcmeTesting", "DemoPG", "acme develop",
        "Acme 개발 DB", "Acme테스트", "Acme 스테이징", "Acme 검증DB", "Acme 로컬",
    ])
    def test_development_words_and_korean_markers_make_a_connection_non_production(self, name):
        """대소문자 경계·구분자로 나눈 토큰이나 한국어 표지가 개발 계열이면 운영이 아니다."""
        # given
        candidate = name
        # when
        production = policy.is_production(candidate)
        # then
        assert production is False

    @pytest.mark.parametrize("name", [
        "AcmeProdPG", "acme-prod-sql", "Acme 운영 DB", "Acme 승인 DB", "acme", "Acmedeveloper", "contest-db",
        "AcmeDEVOPS", "", "   ", None, 7, "Demo 운영 DB", "demo-prod-pg", "AcmeTestLive", "Acme 개발 운영",
    ])
    def test_every_other_name_including_approval_and_unknown_is_production(self, name):
        """표지가 없는 이름, 승인이 든 이름, 알 수 없는 이름은 운영이다."""
        # given
        candidate = name
        # when
        production = policy.is_production(candidate)
        # then
        assert production is True


class TestPlanEstimateParsing:
    @pytest.mark.parametrize("wrap", ["blocks", "string", "content-object", "payload-object"])
    def test_tabularis_json_plan_is_read_from_every_response_shape(self, wrap):
        """tabularis 결과의 JSON 계획은 블록 목록·문자열·content 객체·본문 객체에서 모두 읽는다."""
        # given
        payload = {"columns": ["QUERY PLAN"], "rows": [[PLAN_JSON]], "affected_rows": 0, "truncated": False}
        block = {"type": "text", "text": json.dumps(payload)}
        response = {"blocks": [block], "string": json.dumps(payload), "content-object": {"content": [block]},
                    "payload-object": payload}[wrap]
        # when
        estimate = policy.plan_estimate(response)
        # then
        assert estimate == (123.4, 56.0)

    def test_tabularis_plan_cell_that_is_already_parsed_json_is_read(self):
        """tabularis가 JSON 계획을 이미 해석한 값으로 주어도 읽는다."""
        # given
        response = tabularis_result([[json.loads(PLAN_JSON)]])
        # when
        estimate = policy.plan_estimate(response)
        # then
        assert estimate == (123.4, 56.0)

    def test_tabularis_text_plan_uses_the_first_line_upper_cost_and_rows(self):
        """텍스트 계획은 첫 줄의 위쪽 비용과 rows를 쓴다."""
        # given
        response = tabularis_result([[line] for line in PLAN_TEXT_LINES])
        # when
        estimate = policy.plan_estimate(response)
        # then
        assert estimate == (4278.65, 1.0)

    def test_datagrip_csv_json_plan_is_read(self):
        """DataGrip CSV의 JSON 계획 한 칸에서 비용과 rows를 읽는다."""
        # given
        response = datagrip_result([PLAN_JSON])
        # when
        estimate = policy.plan_estimate(response)
        # then
        assert estimate == (123.4, 56.0)

    def test_datagrip_csv_text_plan_is_read(self):
        """DataGrip CSV의 텍스트 계획 첫 줄에서 비용과 rows를 읽는다."""
        # given
        response = datagrip_result(PLAN_TEXT_LINES)
        # when
        estimate = policy.plan_estimate(response)
        # then
        assert estimate == (4278.65, 1.0)

    @pytest.mark.parametrize("response", [
        [{"type": "text", "text": json.dumps({"errorMessage": "relation does not exist"})}],
        [{"type": "text", "text": json.dumps({"error": "syntax error"})}],
        {"isError": True, "content": [{"type": "text", "text": "boom"}]},
        tabularis_result([]),
        datagrip_result([]),
        [{"type": "text", "text": "not json"}],
        "plain text",
        None, 5, [], {},
        tabularis_result([[json.dumps([{"Plan": {"Node Type": "Seq Scan"}}])]]),
        tabularis_result([[json.dumps([{"Plan": {"Total Cost": "high", "Plan Rows": 1}}])]]),
        tabularis_result([["Seq Scan on orders"]]),
        datagrip_result(["Seq Scan on orders  (cost=0.00..9.00)"]),
    ])
    def test_errors_empty_and_unparseable_results_give_no_estimate(self, response):
        """오류·빈 결과·해석할 수 없는 결과에서는 추정치를 만들지 않는다."""
        # given
        candidate = response
        # when
        estimate = policy.plan_estimate(candidate)
        # then
        assert estimate is None


class TestPlanCapture:
    def test_successful_production_postgres_plan_is_recorded_for_the_session(self, connections):
        """운영 PostgreSQL 계획문이 성공하면 같은 읽기 텍스트의 추정치를 세션에 기록한다."""
        # given
        event = tabularis_event("prodpg", plan_form(), "PostToolUse", response=tabularis_result([[PLAN_JSON]]))
        # when
        guard.handle(event, "claude")
        # then
        found = state_mod.recorded_plan("claude", "s1", "tabularis", "prodpg", policy.read_digest(READ))
        assert (found["cost"], found["rows"]) == (123.4, 56.0)
        assert (state_mod.state_dir() / "db-plans" / "claude-s1.json").exists()

    def test_datagrip_plan_with_the_read_only_prelude_is_recorded_under_the_connection_id(self, project):
        """DataGrip이 읽기 전용 접두를 붙여 실행한 계획문도 접두를 빼고 기록한다."""
        # given
        query = datagrip_guard.READ_ONLY_PRELUDE + plan_form()
        event = datagrip_event(project, PG_PROD, query, "PostToolUse", response=datagrip_result(PLAN_TEXT_LINES))
        # when
        guard.handle(event, "claude")
        # then
        found = state_mod.recorded_plan("claude", "s1", "datagrip", PG_PROD, policy.read_digest(READ))
        assert (found["cost"], found["rows"]) == (4278.65, 1.0)

    @pytest.mark.parametrize("response", [
        tabularis_result([]), [{"type": "text", "text": json.dumps({"error": "x"})}], "garbage",
    ])
    def test_error_empty_and_unparseable_results_record_nothing(self, connections, response):
        """오류·빈 결과·해석 불가 결과는 아무것도 기록하지 않는다."""
        # given
        event = tabularis_event("prodpg", plan_form(), "PostToolUse", response=response)
        # when
        guard.handle(event, "claude")
        # then
        assert state_mod.recorded_plan("claude", "s1", "tabularis", "prodpg", policy.read_digest(READ)) is None

    @pytest.mark.parametrize(("connection", "query", "name"), [
        ("devpg", plan_form(), "PostToolUse"),
        ("prodms", "SELECT 1", "PostToolUse"),
        ("prodpg", READ, "PostToolUse"),
        ("prodpg", f"EXPLAIN (ANALYZE) {READ}", "PostToolUse"),
        ("prodpg", plan_form(), "PostToolUseFailure"),
    ])
    def test_only_production_postgres_plan_statements_are_recorded(self, connections, connection, query, name):
        """개발 연결, SQL Server, 계획이 아닌 읽기, ANALYZE, 실패 이벤트는 기록하지 않는다."""
        # given
        event = tabularis_event(connection, query, name, response=tabularis_result([[PLAN_JSON]]))
        # when
        guard.handle(event, "claude")
        # then
        assert not (state_mod.state_dir() / "db-plans").exists()

    def test_records_expire_after_thirty_minutes_and_older_entries_are_dropped(self, connections, monkeypatch):
        """기록은 30분 안에서만 쓰고, 새 기록을 쓸 때 오래된 항목은 지운다."""
        # given
        start = time.time()
        record("prodpg")
        digest = policy.read_digest(READ)
        # when
        monkeypatch.setattr(state_mod.time, "time", lambda: start + 29 * 60)
        fresh = state_mod.recorded_plan("claude", "s1", "tabularis", "prodpg", digest)
        monkeypatch.setattr(state_mod.time, "time", lambda: start + 31 * 60)
        expired = state_mod.recorded_plan("claude", "s1", "tabularis", "prodpg", digest)
        record("prodpg", "SELECT 2")
        # then
        stored = json.loads((state_mod.plan_path("claude", "s1")).read_text())["plans"]
        assert fresh is not None
        assert expired is None
        assert [entry["digest"] for entry in stored] == [policy.read_digest("SELECT 2")]

    def test_records_are_isolated_by_session_host_tool_connection_and_read(self, connections):
        """기록은 세션·호스트·도구·연결·읽기 텍스트가 모두 같을 때만 찾는다."""
        # given
        record("prodpg")
        digest = policy.read_digest(READ)
        # when
        found = {
            "same": state_mod.recorded_plan("claude", "s1", "tabularis", "prodpg", digest),
            "session": state_mod.recorded_plan("claude", "s2", "tabularis", "prodpg", digest),
            "host": state_mod.recorded_plan("codex", "s1", "tabularis", "prodpg", digest),
            "tool": state_mod.recorded_plan("claude", "s1", "datagrip", "prodpg", digest),
            "connection": state_mod.recorded_plan("claude", "s1", "tabularis", "other", digest),
            "read": state_mod.recorded_plan("claude", "s1", "tabularis", "prodpg", policy.read_digest("SELECT 2")),
        }
        # then
        assert found["same"] is not None
        assert [key for key, value in found.items() if value is None] == ["session", "host", "tool", "connection", "read"]


class TestTabularisReadPolicy:
    def test_non_production_read_runs_as_before(self, connections):
        """개발 연결의 읽기는 계획 없이 그대로 실행한다."""
        # given
        event = tabularis_event("devpg", READ, limit=5000)
        # when
        output = guard.handle(event, "claude")
        # then
        assert decision(output) == "allow"
        assert updated(output) is None

    def test_plan_statement_is_a_read_on_a_production_connection(self, connections):
        """EXPLAIN(ANALYZE 제외)은 운영 연결에서도 계획 없이 읽기다."""
        # given
        event = tabularis_event("prodpg", plan_form())
        # when
        output = guard.handle(event, "claude")
        # then
        assert decision(output) == "allow"
        assert updated(output) is None

    def test_explain_analyze_on_production_is_not_a_read(self, connections):
        """EXPLAIN ANALYZE는 읽기가 아니므로 세션 쓰기 승인을 묻는다."""
        # given
        event = tabularis_event("prodpg", f"EXPLAIN ANALYZE {READ}")
        # when
        output = guard.handle(event, "claude")
        # then
        assert decision(output) == "ask"

    def test_production_read_without_a_plan_is_denied_with_the_exact_plan_form(self, connections):
        """계획 기록이 없는 운영 읽기는 묻지 않고 거부하며 실행할 EXPLAIN 형식을 알려 준다."""
        # given
        event = tabularis_event("prodpg", READ + ";")
        # when
        output = guard.handle(event, "claude")
        # then
        assert decision(output) == "deny"
        assert f"`{plan_form()}`" in reason(output)
        assert "ANALYZE" in reason(output)

    def test_approval_in_the_name_no_longer_asks_for_reads(self, connections):
        """이름에 승인이 있어도 읽기는 묻지 않고 운영 규칙(계획 필요)을 따른다."""
        # given
        event = tabularis_event("approval", READ)
        # when
        output = guard.handle(event, "claude")
        # then
        assert decision(output) == "deny"

    def test_read_with_a_plan_record_runs_with_a_result_limit(self, connections):
        """같은 읽기의 계획 기록이 한도 이하이면 앞뒤 공백과 끝 세미콜론이 달라도 묻지 않고 실행한다."""
        # given
        variant = "  SELECT id, name FROM orders WHERE id = 7 ;; \n"
        record("prodpg")
        event = tabularis_event("prodpg", variant, limit=5000)
        # when
        output = guard.handle(event, "claude")
        # then
        assert decision(output) == "allow"
        assert updated(output)["limit"] == 1000
        assert updated(output)["query"] == variant

    @pytest.mark.parametrize(("extra", "expected"), [
        ({}, 100), ({"limit": 5}, 5), ({"limit": 1000}, 1000), ({"limit": 5000}, 1000),
        ({"limit": "many"}, 100), ({"limit": 0}, 100), ({"limit": True}, 100),
    ])
    def test_tabularis_limit_is_the_smaller_of_the_request_and_the_maximum(self, connections, extra, expected):
        """tabularis limit은 요청값(기본 100)과 최대 결과 행 수 중 작은 값이 된다."""
        # given
        record("prodpg")
        event = tabularis_event("prodpg", READ, **extra)
        # when
        output = guard.handle(event, "claude")
        # then
        assert updated(output)["limit"] == expected

    def test_a_different_read_text_does_not_reuse_the_record(self, connections):
        """계획한 것과 다른 읽기 텍스트는 기록을 쓰지 못하고 거부된다."""
        # given
        record("prodpg")
        event = tabularis_event("prodpg", READ + " OR id = 8")
        # when
        output = guard.handle(event, "claude")
        # then
        assert decision(output) == "deny"

    def test_plan_then_identical_read_runs_end_to_end(self, connections):
        """계획을 실행하고 성공 결과가 기록되면 같은 읽기가 실행된다."""
        # given
        denied = guard.handle(tabularis_event("prodpg", READ), "claude")
        guard.handle(tabularis_event("prodpg", plan_form(), "PostToolUse", response=tabularis_result([[PLAN_JSON]])),
                     "claude")
        # when
        output = guard.handle(tabularis_event("prodpg", READ), "claude")
        # then
        assert decision(denied) == "deny"
        assert decision(output) == "allow"

    @pytest.mark.parametrize(("cost", "rows", "allowed"), [
        (10000, 100000, True), (10000.5, 10, False), (10, 100001, False), (20000, 5, False),
    ])
    def test_estimate_over_a_limit_asks_every_time_and_names_cost_and_rows(self, connections, cost, rows, allowed):
        """추정 비용이나 행 수가 한도를 넘으면 매번 묻고 값을 알려 주며, 한도 이하는 실행한다."""
        # given
        record("prodpg", cost=cost, rows=rows)
        event = tabularis_event("prodpg", READ)
        # when
        output = guard.handle(event, "claude")
        # then
        if allowed:
            assert decision(output) == "allow"
        else:
            assert decision(output) == "ask"
            assert f"estimated cost {cost:g}, rows {rows:g}" in reason(output)
            assert reason(output).startswith("Asks every time:")

    def test_over_limit_ask_does_not_carry_a_session_approval(self, connections):
        """한도를 넘은 읽기는 세션 쓰기 승인이 있어도 다시 묻는다."""
        # given
        state_mod.record_approved("claude", "s1", [state_mod.WRITE_KEY])
        record("prodpg", cost=50000)
        # when
        output = guard.handle(tabularis_event("prodpg", READ), "claude")
        # then
        assert decision(output) == "ask"

    def test_record_with_a_non_numeric_estimate_asks_every_time(self, connections):
        """기록의 추정치를 해석할 수 없으면 매번 묻는다."""
        # given
        record("prodpg", cost="unknown", rows=None)
        # when
        output = guard.handle(tabularis_event("prodpg", READ), "claude")
        # then
        assert decision(output) == "ask"
        assert "unparsed plan" in reason(output)

    def test_multi_statement_production_read_cannot_be_planned_and_asks(self, connections):
        """한 문장으로 계획할 수 없는 운영 읽기는 매번 묻는다."""
        # given
        event = tabularis_event("prodpg", "SELECT 1; SELECT 2")
        # when
        output = guard.handle(event, "claude")
        # then
        assert decision(output) == "ask"
        assert "cannot be planned" in reason(output)

    def test_sql_server_production_read_runs_without_a_plan_with_safeguards(self, connections):
        """SQL Server 운영 읽기는 계획 없이 실행하되 잠금 제한 접두와 결과 행 제한을 붙인다."""
        # given
        event = tabularis_event("prodms", "SELECT id FROM dbo.Jobs", limit=7000)
        # when
        output = guard.handle(event, "claude")
        # then
        assert decision(output) == "allow"
        assert updated(output)["query"] == "SET LOCK_TIMEOUT 5000;\nSET DEADLOCK_PRIORITY LOW;\nSELECT id FROM dbo.Jobs"
        assert updated(output)["limit"] == 1000

    @pytest.mark.parametrize("sql", [
        "SET LOCK_TIMEOUT 3000;\nSELECT 1", "set deadlock_priority -5; SELECT 1",
        "SET LOCK_TIMEOUT 0; SET DEADLOCK_PRIORITY LOW; SELECT 1",
    ])
    def test_sql_server_prefix_always_comes_first_even_when_the_read_sets_safe_values(self, connections, sql):
        """읽기가 한도 안의 값을 직접 정해도 가드의 접두가 항상 맨 앞에 붙는다."""
        # given
        event = tabularis_event("prodms", sql)
        # when
        output = guard.handle(event, "claude")
        # then
        assert updated(output)["query"] == "SET LOCK_TIMEOUT 5000;\nSET DEADLOCK_PRIORITY LOW;\n" + sql

    def test_sql_server_non_production_read_is_not_changed(self, connections):
        """SQL Server 개발 연결의 읽기는 바꾸지 않는다."""
        # given
        event = tabularis_event("devms", "SELECT id FROM dbo.Jobs", limit=7000)
        # when
        output = guard.handle(event, "claude")
        # then
        assert decision(output) == "allow"
        assert updated(output) is None

    def test_codex_gets_the_same_production_decisions(self, connections):
        """Codex도 운영 읽기를 같은 규칙으로 거부하거나 입력을 고쳐 허용한다."""
        # given
        denied = guard.handle(tabularis_event("prodpg", READ), "codex")
        record("prodpg", host="codex")
        # when
        allowed = guard.handle(tabularis_event("prodpg", READ), "codex")
        # then
        assert decision(denied) == "deny"
        assert decision(allowed) == "allow"
        assert updated(allowed)["limit"] == 100

    @pytest.mark.parametrize(("connection", "sql", "kind"), [
        ("prodpg", "UPDATE orders SET a = 1", "write"),
        ("prodpg", "INSERT INTO orders VALUES (1)", "write"),
        ("prodms", "UPDATE dbo.Jobs SET a = 1", "write"),
        ("prodpg", "DELETE FROM orders", "always"),
        ("prodms", "DROP TABLE dbo.Jobs", "always"),
        ("devpg", "TRUNCATE orders", "always"),
        ("devpg", "UPDATE orders SET a = 1", "write"),
        ("approval", "UPDATE orders SET a = 1", "write"),
        ("approval", "DELETE FROM orders", "always"),
    ])
    def test_writes_and_destructive_statements_keep_their_outcomes_on_every_connection(self, connections, connection, sql, kind):
        """쓰기와 파괴적 문장은 모든 연결에서 기존 결과를 유지한다."""
        # given
        arguments = {"connection_id": connection, "query": sql}
        # when
        outcome = guard.classify_mcp(TABULARIS, arguments, host="claude", session="s1")
        # then
        assert outcome.kind == kind


class TestDataGripReadPolicy:
    def test_production_postgres_read_without_a_plan_is_denied_then_runs_after_the_plan(self, project):
        """DataGrip 운영 PostgreSQL 읽기는 계획 전에는 거부하고 계획 기록 뒤에는 읽기 전용 접두로 실행한다."""
        # given
        tool_input = datagrip_event(project, PG_PROD, READ)["tool_input"]
        denied = datagrip_guard.decide(tool_input, "s1")
        guard.handle(datagrip_event(project, PG_PROD, datagrip_guard.READ_ONLY_PRELUDE + plan_form(), "PostToolUse",
                                    response=datagrip_result([PLAN_JSON])), "claude")
        # when
        output = datagrip_guard.decide(tool_input, "s1")
        # then
        assert decision(denied) == "deny"
        assert f"`{plan_form()}`" in reason(denied)
        assert decision(output) == "allow"
        assert updated(output)["queryText"] == datagrip_guard.READ_ONLY_PRELUDE + READ

    def test_plan_statement_and_non_production_reads_run_without_a_record(self, project):
        """계획문과 개발 연결 읽기는 기록 없이 실행한다."""
        # given
        plan = datagrip_event(project, PG_PROD, plan_form())["tool_input"]
        development = datagrip_event(project, PG_DEV, READ)["tool_input"]
        # when
        outputs = [datagrip_guard.decide(plan, "s1"), datagrip_guard.decide(development, "s1")]
        # then
        assert [decision(output) for output in outputs] == ["allow", "allow"]

    def test_over_limit_estimate_asks_every_time(self, project):
        """한도를 넘은 DataGrip 운영 읽기는 매번 묻는다."""
        # given
        record(PG_PROD, cost=99999, tool="datagrip")
        # when
        output = datagrip_guard.decide(datagrip_event(project, PG_PROD, READ)["tool_input"], "s1")
        # then
        assert decision(output) == "ask"
        assert "estimated cost 99999" in reason(output)

    def test_approval_in_the_name_is_production_like_any_other_name(self, project):
        """이름에 승인이 있는 DataGrip 연결도 계획이 없으면 거부한다."""
        # given
        tool_input = datagrip_event(project, PG_APPROVAL, READ)["tool_input"]
        # when
        output = datagrip_guard.decide(tool_input, "s1")
        # then
        assert decision(output) == "deny"

    def test_sql_server_production_read_gets_the_lock_prefix_without_a_plan(self, project):
        """DataGrip SQL Server 운영 읽기는 계획 없이 잠금 제한 접두를 붙여 실행한다."""
        # given
        tool_input = datagrip_event(project, MS_PROD, "SET LOCK_TIMEOUT 3000;\nSELECT id FROM dbo.Jobs")["tool_input"]
        # when
        output = datagrip_guard.decide(tool_input, "s1")
        # then
        assert decision(output) == "allow"
        assert updated(output)["queryText"] == (
            "SET LOCK_TIMEOUT 5000;\nSET DEADLOCK_PRIORITY LOW;\nSET LOCK_TIMEOUT 3000;\nSELECT id FROM dbo.Jobs")
        assert "limit" not in updated(output)

    def test_sql_server_development_read_is_not_changed(self, project):
        """DataGrip SQL Server 개발 연결의 읽기는 바꾸지 않는다."""
        # given
        tool_input = datagrip_event(project, MS_DEV, "SELECT id FROM dbo.Jobs")["tool_input"]
        # when
        output = datagrip_guard.decide(tool_input, "s1")
        # then
        assert decision(output) == "allow"
        assert updated(output) is None

    def test_codex_denies_without_a_plan_and_rewrites_with_one(self, project):
        """Codex 사전 실행 훅도 계획이 없으면 거부하고, 있으면 읽기 전용 접두와 SQL Server 접두를 붙인다."""
        # given
        postgres = datagrip_event(project, PG_PROD, READ)["tool_input"]
        sqlserver = datagrip_event(project, MS_PROD, "SELECT id FROM dbo.Jobs")["tool_input"]
        denied = datagrip_guard.codex_pre_tool_use(postgres, "s1")
        record(PG_PROD, tool="datagrip", host="codex")
        # when
        postgres_output = datagrip_guard.codex_pre_tool_use(postgres, "s1")
        sqlserver_output = datagrip_guard.codex_pre_tool_use(sqlserver, "s1")
        # then
        assert decision(denied) == "deny"
        assert updated(postgres_output)["queryText"] == datagrip_guard.READ_ONLY_PRELUDE + READ
        assert updated(sqlserver_output)["queryText"].startswith("SET LOCK_TIMEOUT 5000;\nSET DEADLOCK_PRIORITY LOW;\n")

    def test_reads_are_not_gated_while_the_approval_guard_is_off(self, project, monkeypatch):
        """승인 가드가 꺼져 있으면 계획을 기록할 수 없으므로 읽기를 막지 않는다."""
        # given
        monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_APPROVAL_GUARD", "false")
        tool_input = datagrip_event(project, PG_PROD, READ)["tool_input"]
        # when
        output = datagrip_guard.decide(tool_input, "s1")
        # then
        assert decision(output) == "allow"

    @pytest.mark.parametrize(("connection", "sql", "kind"), [
        (PG_PROD, "UPDATE orders SET a = 1", "write"), (MS_PROD, "UPDATE dbo.Jobs SET a = 1", "write"),
        (PG_PROD, "DELETE FROM orders", "always"), (MS_PROD, "DROP TABLE dbo.Jobs", "always"),
        (PG_APPROVAL, "UPDATE orders SET a = 1", "write"), (PG_DEV, "TRUNCATE orders", "always"),
    ])
    def test_datagrip_writes_and_destructive_statements_keep_their_outcomes(self, project, connection, sql, kind):
        """DataGrip의 쓰기와 파괴적 문장도 연결 환경과 관계없이 기존 결과를 유지한다."""
        # given
        tool_input = datagrip_event(project, connection, sql)["tool_input"]
        # when
        outcome = datagrip_guard.classify_query(tool_input)
        # then
        assert outcome.kind == kind


class TestLimits:
    def test_defaults_apply_without_a_file(self, connections):
        """파일이 없으면 기본 한도를 쓴다."""
        # given
        names = ("prodpg", "AcmeProdPG")
        # when
        found = policy.limits(*names)
        # then
        assert found == {"postgres_max_cost": 10000, "max_estimated_rows": 100000, "max_result_rows": 1000,
                         "sqlserver_lock_timeout_ms": 5000}

    def test_file_default_and_connection_entries_override_per_key(self, limits_file):
        """default 항목은 기본값을, 이름이나 id가 맞는 연결 항목은 default를 키별로 덮어쓴다."""
        # given
        limits_file.write_text(json.dumps({
            "default": {"postgres_max_cost": 500, "max_result_rows": 50, "unknown_key": 1},
            "connections": {"AcmeProdPG": {"max_result_rows": 20}, "prodms": {"sqlserver_lock_timeout_ms": 900}},
        }))
        # when
        by_name, by_id, other = policy.limits("prodpg", "AcmeProdPG"), policy.limits("prodms", "x"), policy.limits("z")
        # then
        assert (by_name["postgres_max_cost"], by_name["max_result_rows"], by_name["max_estimated_rows"]) == (500, 20, 100000)
        assert (by_id["max_result_rows"], by_id["sqlserver_lock_timeout_ms"]) == (50, 900)
        assert (other["postgres_max_cost"], other["max_result_rows"]) == (500, 50)
        assert "unknown_key" not in other

    @pytest.mark.parametrize("value", [0, -5, "100", None, True, [3], float("inf"), 0.5])
    def test_non_positive_and_non_numeric_values_are_ignored(self, limits_file, value):
        """0 이하이거나 숫자가 아닌 값은 무시하고 기본값을 쓴다."""
        # given
        limits_file.write_text(json.dumps({"default": {"max_result_rows": value, "postgres_max_cost": value}},
                                          allow_nan=True))
        # when
        found = policy.limits("x")
        # then
        assert found["max_result_rows"] == 1000
        assert found["postgres_max_cost"] in (10000, 0.5)

    @pytest.mark.parametrize("contents", ["{invalid", "[]", "null", '"text"', '{"default": 3, "connections": []}', ""])
    def test_invalid_file_means_the_defaults(self, limits_file, contents):
        """읽을 수 없거나 형식이 틀린 파일이면 기본 한도를 쓴다."""
        # given
        limits_file.write_text(contents)
        # when
        found = policy.limits("x")
        # then
        assert found == policy.DEFAULT_LIMITS

    def test_local_file_changes_what_a_production_read_may_cost_and_return(self, limits_file, connections):
        """로컬 파일의 한도가 운영 읽기의 허용 비용과 결과 행 수를 바꾼다."""
        # given
        limits_file.write_text(json.dumps({"connections": {"AcmeProdPG": {"postgres_max_cost": 50, "max_result_rows": 10}}}))
        record("prodpg", cost=60)
        asked = guard.handle(tabularis_event("prodpg", READ), "claude")
        limits_file.write_text(json.dumps({"connections": {"AcmeProdPG": {"postgres_max_cost": 500, "max_result_rows": 10}}}))
        # when
        allowed = guard.handle(tabularis_event("prodpg", READ, limit=300), "claude")
        # then
        assert decision(asked) == "ask"
        assert decision(allowed) == "allow"
        assert updated(allowed)["limit"] == 10

    def test_lock_timeout_limit_sets_the_sql_server_prefix(self, limits_file, connections):
        """sqlserver_lock_timeout_ms 한도가 SQL Server 접두의 LOCK_TIMEOUT 값이 된다."""
        # given
        limits_file.write_text(json.dumps({"default": {"sqlserver_lock_timeout_ms": 1500}}))
        # when
        output = guard.handle(tabularis_event("prodms", "SELECT 1"), "claude")
        # then
        assert updated(output)["query"].startswith("SET LOCK_TIMEOUT 1500;\n")


class TestLimitsFileProtection:
    @pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit", "NotebookEdit"])
    def test_file_tools_that_change_the_limits_file_ask_every_time(self, limits_file, tool):
        """편집 도구로 한도 파일을 바꾸면 매번 묻는다."""
        # given
        key = "notebook_path" if tool == "NotebookEdit" else "file_path"
        event = {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": tool,
                 "tool_input": {key: str(limits_file)}}
        # when
        output = guard.handle(event, "claude")
        # then
        assert decision(output) == "ask"
        assert output["hookSpecificOutput"]["permissionDecisionReason"].startswith("Asks every time:")

    @pytest.mark.parametrize("action", ["Update File", "Add File", "Delete File", "Move to"])
    def test_apply_patch_that_touches_the_limits_file_asks_every_time(self, limits_file, action):
        """apply_patch가 한도 파일을 수정·추가·삭제·이동하면 매번 묻는다."""
        # given
        patch = f"*** Begin Patch\n*** {action}: {limits_file}\n*** End Patch"
        event = {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "apply_patch",
                 "tool_input": {"command": patch}}
        # when
        output = guard.handle(event, "claude")
        # then
        assert decision(output) == "ask"

    def test_reading_the_limits_file_and_editing_other_files_do_not_ask(self, limits_file, state):
        """한도 파일을 읽거나 다른 파일을 고치는 것은 이 규칙으로 묻지 않는다."""
        # given
        read = {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "Read",
                "tool_input": {"file_path": str(limits_file)}}
        other = {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "Edit",
                 "tool_input": {"file_path": str(state / "notes.txt")}}
        # when
        outputs = [guard.handle(read, "claude"), guard.handle(other, "claude")]
        # then
        assert all(decision(output) != "ask" for output in outputs)

    @pytest.mark.parametrize("command", [
        "echo '{{}}' > {path}", "cp /tmp/work/new.json {path}", "mv {path} /tmp/work/old.json", "rm {path}",
        "sed -i s/1/2/ {path}", "printf x | tee {path}", "python3 -c \"open('{path}', 'w').write('{{}}')\"",
        "rm -r {folder}", "cd {folder} && echo '{{}}' > db-read-limits.json",
    ])
    def test_shell_commands_that_change_the_limits_file_ask_every_time(self, limits_file, command):
        """셸로 한도 파일을 쓰거나 옮기거나 복사해 덮거나 지우면 매번 묻는다."""
        # given
        event = bash_event(command.format(path=limits_file, folder=limits_file.parent), cwd=limits_file.parent.parent)
        # when
        output = guard.handle(event, "claude")
        # then
        assert decision(output) == "ask"
        assert output["hookSpecificOutput"]["permissionDecisionReason"].startswith("Asks every time:")

    @pytest.mark.parametrize("command", ["cat {path}", "ls -l {folder}", "grep cost {path}", "wc -c {path}"])
    def test_shell_commands_that_only_read_the_limits_file_do_not_ask(self, limits_file, command):
        """한도 파일을 읽기만 하는 셸 명령은 이 규칙으로 묻지 않는다."""
        # given
        event = bash_event(command.format(path=limits_file, folder=limits_file.parent), cwd=limits_file.parent.parent)
        # when
        output = guard.handle(event, "claude")
        # then
        assert output is None or decision(output) != "ask"

    @pytest.mark.parametrize("code", [
        "python3 -c 'import db_read_policy'", "python3 -c 'from db_read_policy import limits'",
        "python3 scripts/db_read_policy.py",
    ])
    def test_running_the_policy_module_is_denied_like_the_other_guard_modules(self, state, code):
        """계획 기록을 만들 수 있는 정책 모듈을 셸에서 실행하거나 가져오면 거부한다."""
        # given
        event = bash_event(code, cwd=state)
        # when
        output = guard.handle(event, "claude")
        # then
        assert decision(output) == "deny"


class TestExactPlanText:
    COMMENTED = "SELECT count(*) FROM orders -- filter\nWHERE id = 7"
    FLATTENED = "SELECT count(*) FROM orders -- filter WHERE id = 7"

    def test_digest_ignores_only_outer_whitespace_and_trailing_semicolons(self):
        """다이제스트는 앞뒤 공백과 끝 세미콜론만 무시하고 안쪽 문자는 모두 구분한다."""
        # given
        same = ["  SELECT 1 ;; \n", "SELECT 1;", "SELECT 1"]
        different = ["SELECT  1", "SELECT\n1", "select 1", "SELECT 1 -- c", "SELECT 1; SELECT 2"]
        # when
        digests = {text: policy.read_digest(text) for text in [*same, *different]}
        # then
        assert len({digests[text] for text in same}) == 1
        assert all(digests[text] != digests["SELECT 1"] for text in different)
        assert policy.read_digest(self.COMMENTED) != policy.read_digest(self.FLATTENED)

    def test_plan_form_and_plan_statement_round_trip_the_exact_text(self):
        """계획문에서 접두를 뗀 읽기 텍스트는 원문과 바이트 단위로 같다."""
        # given
        read = "SELECT  a,\n\tb FROM t -- note\nWHERE x = 'a  b'"
        # when
        shape = datagrip_guard.read_shape(policy.plan_form(read + " ;"))
        # then
        assert shape == ("plan", read)
        assert policy.plan_form(read) == "EXPLAIN (FORMAT JSON) " + read

    def test_record_matches_only_the_identical_text(self, connections):
        """계획한 텍스트와 안쪽 문자가 하나라도 다른 읽기는 기록을 쓰지 못한다."""
        # given
        guard.handle(tabularis_event("prodpg", policy.plan_form(self.COMMENTED), "PostToolUse",
                                     response=tabularis_result([[PLAN_JSON]])), "claude")
        # when
        same = guard.handle(tabularis_event("prodpg", self.COMMENTED + ";"), "claude")
        flattened = guard.handle(tabularis_event("prodpg", self.FLATTENED), "claude")
        spaced = guard.handle(tabularis_event("prodpg", self.COMMENTED.replace("count(*)", "count( * )")), "claude")
        # then
        assert decision(same) == "allow"
        assert decision(flattened) == "deny"
        assert decision(spaced) == "deny"
        assert f"`{policy.plan_form(self.FLATTENED)}`" in reason(flattened)


class TestSqlServerSafeguardBypass:
    UNSAFE = "SET LOCK_TIMEOUT -1; SET DEADLOCK_PRIORITY 10; SELECT * FROM dbo.Jobs;"

    def classify(self, sql, connection="prodms"):
        return guard.classify_mcp(TABULARIS, {"connection_id": connection, "query": sql}, host="claude", session="s1")

    @pytest.mark.parametrize("sql", [
        "SET LOCK_TIMEOUT 0; SELECT 1", "SET LOCK_TIMEOUT 5000;\nSELECT 1", "set lock_timeout 3000; select 1",
        "SET DEADLOCK_PRIORITY LOW; SELECT 1", "SET DEADLOCK_PRIORITY -5; SELECT 1", "set deadlock_priority -10; select 1",
        "SELECT 'SET LOCK_TIMEOUT -1' AS s -- SET DEADLOCK_PRIORITY 10",
        "SET NOCOUNT ON; SELECT 1",
    ])
    def test_settings_inside_the_bounds_keep_the_read_enforced(self, connections, sql):
        """한도 안의 LOCK_TIMEOUT과 DEADLOCK_PRIORITY(와 리터럴·주석 속 문구)는 읽기로 실행한다."""
        # given
        candidate = sql
        # when
        outcome = self.classify(candidate)
        # then
        assert (outcome.kind, outcome.exe) == ("read", policy.ENFORCE_SQLSERVER)

    @pytest.mark.parametrize(("sql", "setting"), [
        (UNSAFE, "LOCK_TIMEOUT"),
        ("SET LOCK_TIMEOUT -1; SELECT 1", "LOCK_TIMEOUT"),
        ("SET LOCK_TIMEOUT 5001; SELECT 1", "LOCK_TIMEOUT"),
        ("SET LOCK_TIMEOUT 99999999999999999999; SELECT 1", "LOCK_TIMEOUT"),
        ("SET DEADLOCK_PRIORITY 10; SELECT 1", "DEADLOCK_PRIORITY"),
        ("SET DEADLOCK_PRIORITY 0; SELECT 1", "DEADLOCK_PRIORITY"),
        ("SET DEADLOCK_PRIORITY -4; SELECT 1", "DEADLOCK_PRIORITY"),
        ("SET DEADLOCK_PRIORITY NORMAL; SELECT 1", "DEADLOCK_PRIORITY"),
        ("set lock_timeout -1;select 1", "LOCK_TIMEOUT"),
        ("/* x */ SET   Lock_Timeout\n-1; SELECT 1", "LOCK_TIMEOUT"),
        ("SET LOCK_TIMEOUT 1000; SELECT 1; SET LOCK_TIMEOUT -1; SELECT 2", "LOCK_TIMEOUT"),
        ("SET DEADLOCK_PRIORITY LOW; SELECT 1; set deadlock_priority 5; SELECT 2", "DEADLOCK_PRIORITY"),
        ("SELECT 1; SET \uff2c\uff2f\uff23\uff2b_TIMEOUT -1", "LOCK_TIMEOUT"),
    ])
    def test_settings_that_loosen_the_safeguards_ask_every_time_and_name_the_setting(self, connections, sql, setting):
        """안전장치를 푸는 SET 문은 어느 위치에 있든 매번 묻고 설정 이름을 알려 준다."""
        # given
        candidate = sql
        # when
        outcome = self.classify(candidate)
        # then
        assert outcome.kind == "always"
        assert outcome.every_time is True
        assert setting in outcome.descriptions[0]

    @pytest.mark.parametrize("sql", [
        "SET LOCK_TIMEOUT @t; SELECT 1", "SET DEADLOCK_PRIORITY HIGH; SELECT 1", "SET DEADLOCK_PRIORITY @p; SELECT 1",
        "SET LOCK_TIMEOUT 5000 SELECT 1",
    ])
    def test_settings_the_allowlist_does_not_accept_are_not_reads(self, connections, sql):
        """변수나 HIGH 같은 값은 읽기 허용 목록을 통과하지 못한다."""
        # given
        candidate = sql
        # when
        outcome = self.classify(candidate)
        # then
        assert outcome.kind != "read"

    def test_unsafe_read_asks_through_the_hook_and_never_reaches_the_prefix_path(self, connections):
        """훅 경로에서도 안전장치를 푸는 읽기는 입력을 고쳐 허용하지 않고 묻는다."""
        # given
        event = tabularis_event("prodms", self.UNSAFE)
        # when
        output = guard.handle(event, "claude")
        # then
        assert decision(output) == "ask"
        assert updated(output) is None

    def test_non_production_connection_is_not_checked(self, connections):
        """개발 연결의 읽기는 SET 값을 검사하지 않고 그대로 읽기다."""
        # given
        candidate = self.UNSAFE
        # when
        outcome = self.classify(candidate, "devms")
        # then
        assert (outcome.kind, outcome.exe) == ("read", None)

    def test_local_lock_timeout_limit_changes_the_accepted_maximum(self, connections, limits_file):
        """sqlserver_lock_timeout_ms 한도가 읽기가 정할 수 있는 LOCK_TIMEOUT의 상한이 된다."""
        # given
        limits_file.write_text(json.dumps({"default": {"sqlserver_lock_timeout_ms": 1500}}))
        # when
        kinds = [self.classify(f"SET LOCK_TIMEOUT {value}; SELECT 1").kind for value in (1500, 1501)]
        # then
        assert kinds == ["read", "always"]

    def test_datagrip_applies_the_same_check(self, project):
        """DataGrip 경로도 안전장치를 푸는 SQL Server 운영 읽기를 매번 묻는다."""
        # given
        unsafe = datagrip_event(project, MS_PROD, self.UNSAFE)["tool_input"]
        safe = datagrip_event(project, MS_PROD, "SET LOCK_TIMEOUT 100;\nSELECT 1")["tool_input"]
        # when
        asked, allowed = datagrip_guard.decide(unsafe, "s1"), datagrip_guard.decide(safe, "s1")
        # then
        assert decision(asked) == "ask"
        assert updated(asked) is None
        assert updated(allowed)["queryText"].startswith("SET LOCK_TIMEOUT 5000;\nSET DEADLOCK_PRIORITY LOW;\n")


class TestQuotedIdentifiersAreNotDestructive:
    @pytest.mark.parametrize(("sql", "postgres"), [
        ('SELECT 1 AS "delete"', True), ('SELECT "drop", "truncate" FROM "delete"."drop"', True),
        ('SELECT 1 AS "delete"', False), ('SELECT [delete], "drop" FROM [truncate]', False),
        ('UPDATE "delete" SET a = 1', True), ('INSERT INTO "drop" VALUES (1)', True),
    ])
    def test_quoted_identifier_contents_are_blanked_for_both_dialects(self, sql, postgres):
        """따옴표 식별자 안의 delete·drop·truncate는 파괴적 키워드로 보지 않는다."""
        # given
        candidate = sql
        # when
        destructive = datagrip_guard.is_destructive(candidate, postgres)
        # then
        assert destructive is False
        assert datagrip_guard.query_facts(candidate, postgres)[1] is False

    @pytest.mark.parametrize(("sql", "postgres"), [
        ('SELECT 1 AS "x"; DROP TABLE t', True), ('SELECT "a" FROM t; delete from t', True),
        ('SELECT 1 AS "x"; TRUNCATE t', True), ('SELECT 1 AS "x"; DROP TABLE t', False),
        ("DO $$ BEGIN EXECUTE 'DELETE FROM t'; END $$", True), ("EXEC('DELETE FROM dbo.T')", False),
        ('EXEC dbo."Cleanup"', False), ('SELECT "x" FROM t WHERE a = 1 DELETE FROM t', False),
        ("SELECT 1 AS delete", True), ("SELECT 1 AS delete", False),
    ])
    def test_bare_keywords_and_dynamic_statements_stay_destructive(self, sql, postgres):
        """코드의 delete·drop·truncate와 DO·EXEC로 시작하는 문장은 따옴표 식별자가 있어도 파괴적이다."""
        # given
        candidate = sql
        # when
        destructive = datagrip_guard.is_destructive(candidate, postgres)
        # then
        assert destructive is True

    def test_identifier_text_still_feeds_the_function_call_checks(self):
        """함수 호출 검사는 따옴표 식별자의 이름을 그대로 보고 위험 호출을 읽기에서 뺀다."""
        # given
        sql = 'SELECT "pg_terminate_backend"(1)'
        # when
        read = datagrip_guard.is_read(sql, True)
        # then
        assert read is False

    def test_quoted_delete_on_a_development_connection_is_no_longer_every_time(self, connections):
        """개발 연결에서 SELECT 1 AS "delete"는 매번 묻지 않는다."""
        # given
        arguments = {"connection_id": "devpg", "query": 'SELECT 1 AS "delete"'}
        # when
        outcome = guard.classify_mcp(TABULARIS, arguments, host="claude", session="s1")
        # then
        assert outcome.kind in ("read", "write")
        assert outcome.every_time is False

    def test_codex_datagrip_unsafe_read_needs_a_one_time_code_instead_of_running(self, project):
        """Codex에서는 안전장치를 푸는 SQL Server 운영 읽기가 입력 수정 없이 승인 코드 요청으로 거부된다."""
        # given
        unsafe = datagrip_event(project, MS_PROD, TestSqlServerSafeguardBypass.UNSAFE)["tool_input"]
        # when
        output = datagrip_guard.codex_pre_tool_use(unsafe, "s1")
        # then
        assert decision(output) == "deny"
        assert updated(output) is None


class TestTargetedWritesOnNonProductionConnections:
    SAFE_DO = "DO $$ BEGIN UPDATE demo_items SET n = 1 WHERE id = 1; PERFORM pg_sleep(0.05); COMMIT; END $$"
    TARGETED = "DELETE FROM demo_items m USING demo_backup b WHERE m.id = b.id"

    @pytest.mark.parametrize(("connection", "sql", "kind"), [
        (PG_DEV, TARGETED, "write"), (PG_DEV, SAFE_DO, "write"), (MS_DEV, "DELETE FROM dbo.Items WHERE id = 1", "always"),
        (PG_DEV, "DO $$ BEGIN IF true THEN NULL; END $$", "always"),
        (PG_DEV, 'DO $$ BEGIN PERFORM "pg_terminate_backend"(1); END $$', "always"),
        (PG_DEV, "DELETE FROM demo_items", "always"), (PG_DEV, "DROP TABLE demo_items", "always"),
        (PG_DEV, "TRUNCATE demo_items", "always"), (PG_DEV, "CALL demo_proc()", "always"),
        (PG_DEV, "DO $$ BEGIN EXECUTE 'x'; END $$", "always"), (MS_DEV, "EXEC dbo.Cleanup", "always"),
        (MS_DEV, "DELETE FROM dbo.Items", "always"),
        (PG_PROD, TARGETED, "always"), (PG_PROD, SAFE_DO, "always"), (MS_PROD, "DELETE FROM dbo.Items WHERE id = 1", "always"),
        (PG_APPROVAL, TARGETED, "always"), (PG_APPROVAL, SAFE_DO, "always"),
    ])
    def test_datagrip_waives_only_targeted_writes_and_only_on_development_data_sources(
            self, project, connection, sql, kind, sql_parser):
        """DataGrip은 pglast로 분류한 개발 PostgreSQL의 WHERE 있는 DELETE와 안전한 DO만 세션 쓰기로 낮춘다."""
        # given
        tool_input = datagrip_event(project, connection, sql)["tool_input"]
        plain = datagrip_guard.classify_query(datagrip_event(project, connection, "INSERT INTO demo_items (id) VALUES (1)")["tool_input"])
        kind = "always" if sql_parser == "regex" else kind
        # when
        outcome = datagrip_guard.classify_query(tool_input)
        # then
        assert (outcome.kind, outcome.every_time) == (kind, kind == "always")
        if kind == "write":
            assert (outcome.keys, outcome.every_time) == (plain.keys, plain.every_time)

    @pytest.mark.parametrize(("connection", "sql", "kind"), [
        ("devpg", TARGETED, "write"), ("devpg", SAFE_DO, "write"), ("devms", "DELETE FROM dbo.Items WHERE id = 1", "always"),
        ("devpg", 'DO $$ BEGIN PERFORM "pg_terminate_backend"(1); END $$', "always"),
        ("devpg", "DO $$ BEGIN IF true THEN NULL; END $$", "always"),
        ("devpg", "DELETE FROM demo_items", "always"), ("devpg", "DO $$ BEGIN DROP TABLE demo_items; END $$", "always"),
        ("devms", "EXEC dbo.Cleanup", "always"),
        ("prodpg", TARGETED, "always"), ("prodpg", SAFE_DO, "always"), ("prodms", "DELETE FROM dbo.Items WHERE id = 1", "always"),
        ("approval", TARGETED, "always"),
    ])
    def test_tabularis_matches_datagrip_on_the_same_environments(self, connections, connection, sql, kind, sql_parser):
        """tabularis도 같은 환경 규칙으로 분류한다."""
        # given
        arguments = {"connection_id": connection, "query": sql}
        kind = "always" if sql_parser == "regex" else kind
        # when
        outcome = guard.classify_mcp(TABULARIS, arguments, host="claude", session="s1")
        # then
        assert (outcome.kind, outcome.every_time) == (kind, kind == "always")

    @pytest.mark.parametrize(("sql", "claude_first", "claude_after", "codex_first", "codex_after"), [
        (TARGETED, "ask", "allow", "deny", None),
        (SAFE_DO, "ask", "allow", "deny", None),
        ("DELETE FROM demo_items", "ask", "ask", "deny", "deny"),
        ("DO $$ BEGIN DROP TABLE demo_items; END $$", "ask", "ask", "deny", "deny"),
    ])
    def test_datagrip_decisions_on_both_hosts_follow_the_session_write_approval(
            self, project, sql, claude_first, claude_after, codex_first, codex_after, sql_parser):
        """DataGrip 개발 연결의 WHERE 있는 DELETE와 안전한 DO는 두 호스트 모두 세션 쓰기 승인 뒤 통과하고, 나머지는 계속 묻는다."""
        # given
        tool_input = datagrip_event(project, PG_DEV, sql)["tool_input"]
        if sql_parser == "regex":
            claude_after, codex_after = "ask", "deny"
        # when
        first = (decision(datagrip_guard.decide(tool_input, "claude-s")), decision(datagrip_guard.codex_pre_tool_use(tool_input, "codex-s")))
        state_mod.record_approved("claude", "claude-s", [state_mod.WRITE_KEY])
        state_mod.record_approved("codex", "codex-s", [state_mod.WRITE_KEY])
        after = (decision(datagrip_guard.decide(tool_input, "claude-s")), decision(datagrip_guard.codex_pre_tool_use(tool_input, "codex-s")))
        # then
        assert (first, after) == ((claude_first, codex_first), (claude_after, codex_after))
