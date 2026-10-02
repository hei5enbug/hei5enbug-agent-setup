#!/usr/bin/env python3
"""Approval guard for the DataGrip `execute_sql_query` tool, shared by Claude Code and Codex.

The data source is resolved from `<projectPath>/.idea/dataSources.xml` by matching `connectionId` to the `uuid` of a
`data-source` element. A name containing `승인` always asks. The `driver-ref` selects the database: `postgresql`, or a
value starting with `sqlserver` or `azure`. Any other driver, an unreadable file, or an unknown uuid asks.

Only queries that are certainly reads run without approval; everything else asks.
  - PostgreSQL with pglast: every statement must be SELECT, VALUES, TABLE, SHOW, or EXPLAIN of a SELECT without
    ANALYZE, and the parse tree must hold no INSERT, UPDATE, DELETE, MERGE, INTO, locking clause, or risky function
    call. Reads run in a read-only transaction through a prepended `SET LOCAL transaction_read_only = on;`.
  - PostgreSQL without pglast: a regex classifier over text with strings, quoted identifiers, and comments removed.
  - SQL Server: every statement starts with SELECT or WITH and holds no write, execute, or side-effect keyword.
    Session variable statements (DECLARE @v, SET @v =, INSERT [INTO] @v) count as reads under the same condition.
  - Control characters, invisible format characters, JDBC escapes, unterminated literals, and parse errors ask.
The guard never denies and always exits 0.

Claude Code PreToolUse prints a permission decision; PermissionRequest prints nothing. Codex PreToolUse prints an
allow with the read-only prefix for PostgreSQL reads, and PermissionRequest prints an allow for any read. Anything
undecided prints nothing, which leaves the host's own approval flow in charge.

When pglast is not importable and `$XDG_STATE_HOME/hei5enbug-agent-setup/sql-parser/bin/python` exists (default
`~/.local/state`), the script re-executes itself once with that interpreter.
"""
import json
import os
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from pglast import parser as pglast_parser
except Exception:
    pglast_parser = None

TOOL_NAME = "mcp__datagrip__execute_sql_query"
APPROVAL_MARK = "승인"
REEXEC_GUARD = "HEI5ENBUG_SQL_PARSER_REEXEC"

ALWAYS_ASK_REASON = "This data source is marked as requiring approval, so every query needs your approval."
UNKNOWN_REASON = "The DataGrip data source could not be identified from the project settings. Review the SQL and approve it."
UNSUPPORTED_REASON = "Only PostgreSQL and SQL Server data sources are checked automatically. Review the SQL and approve it."
ASK_REASON = "This query writes or cannot be classified as a read. Review the SQL and approve it."
PG_ALLOW_REASON = "Classified as a PostgreSQL read; it runs in a read-only transaction."
MSSQL_ALLOW_REASON = "Classified as a SQL Server read; it runs without approval."

READ_ONLY_PRELUDE = "SET LOCAL transaction_read_only = on;\n"
PLACEHOLDER = " __lit__ "

PRELUDE = re.compile(r"^set\s+local\s+(statement_timeout|lock_timeout|transaction_read_only)\s*(=|to)\s*'?([^';\s]+)'?$", re.I)
QUERY_START = re.compile(r"^(select|with|explain|show|table|values)\b", re.I)
KEYWORD_START = r"(?<![^\W\d])(?<![@#])"
EXPLAIN_ANALYZE = re.compile(r"^explain\s*(\(|\s)[^;]*(?<![^\W\d])analy[sz]e\b", re.I)
RISKY = re.compile(
    KEYWORD_START + r"(insert|update|delete|merge|truncate|copy|into|commit|rollback|begin|abort|savepoint|prepare|"
    r"reset|discard|call|do|lock|vacuum|grant|revoke|create|alter|drop|comment|refresh|reindex|cluster|"
    r"read_only|session_authorization|set_config|nextval|setval|dblink\w*|lo_\w+|pg_terminate_backend|"
    r"pg_cancel_backend|pg_reload_conf|pg_advisory\w*|pg_notify|pg_sleep\w*|"
    r"for\s+(key\s+)?share|query_to_xml\w*|cursor_to_xml\w*|ts_stat|crosstab\w*|http\w*|brin_\w+|"
    r"gin_clean_pending_list|set_\w+|drop_chunks|\w*compress_chunk|add_\w*policy|remove_\w*policy|"
    r"add_job|alter_job|delete_job|run_job|move_chunk|reorder_chunk|create_hypertable|attach_\w+|detach_\w+)\b",
    re.I,
)
PG_FUNCTION_CALL = re.compile(r"(?<![^\W\d])(pg_\w+)\s*\(", re.I)
QUALIFIED_CALL = re.compile(r"(?<![^\W\d])(\w+(?:\s*\.\s*\w+)+)\s*\(")
PG_SAFE_SCHEMAS = {"pg_catalog", "public", "information_schema"}
PG_SAFE_FUNCTIONS = {
    "pg_size_pretty", "pg_size_bytes", "pg_relation_size", "pg_total_relation_size", "pg_table_size",
    "pg_indexes_size", "pg_database_size", "pg_tablespace_size", "pg_column_size", "pg_relation_filenode",
    "pg_relation_filepath", "pg_get_viewdef", "pg_get_functiondef", "pg_get_function_arguments",
    "pg_get_function_identity_arguments", "pg_get_function_result", "pg_get_indexdef", "pg_get_constraintdef",
    "pg_get_triggerdef", "pg_get_ruledef", "pg_get_expr", "pg_get_partkeydef", "pg_get_statisticsobjdef",
    "pg_get_userbyid", "pg_get_serial_sequence", "pg_get_keywords", "pg_typeof", "pg_backend_pid",
    "pg_postmaster_start_time", "pg_conf_load_time", "pg_is_in_recovery", "pg_last_xact_replay_timestamp",
    "pg_current_wal_lsn", "pg_wal_lsn_diff", "pg_blocking_pids", "pg_table_is_visible",
    "pg_function_is_visible", "pg_type_is_visible", "pg_has_role", "pg_encoding_to_char",
    "pg_char_to_encoding", "pg_client_encoding", "pg_input_is_valid", "pg_column_compression",
    "pg_partition_tree", "pg_partition_root", "pg_partition_ancestors", "pg_options_to_table",
    "pg_describe_object", "pg_identify_object", "pg_tablespace_location", "pg_my_temp_schema",
    "pg_jit_available", "pg_trigger_depth", "pg_xact_commit_timestamp", "pg_current_snapshot",
    "pg_snapshot_xmin", "pg_snapshot_xmax", "pg_visible_in_snapshot", "pg_index_column_has_property",
    "pg_index_has_property", "pg_indexam_has_property",
}
PG_RISKY_FUNCTIONS = re.compile(
    r"dblink\w*|lo_\w+|set_config|nextval|setval|query_to_xml\w*|cursor_to_xml\w*|ts_stat|crosstab\w*|http\w*|"
    r"brin_\w+|gin_clean_pending_list|set_\w+|drop_chunks|\w*compress_chunk|add_\w*policy|remove_\w*policy|"
    r"add_job|alter_job|delete_job|run_job|move_chunk|reorder_chunk|create_hypertable|attach_\w+|detach_\w+",
    re.I,
)
PG_PRELUDE_SETTINGS = {"statement_timeout", "lock_timeout", "transaction_read_only"}
PG_WRITE_NODES = {"InsertStmt", "UpdateStmt", "DeleteStmt", "MergeStmt", "IntoClause", "LockingClause"}
MSSQL_START = re.compile(r"^(select|with)\b", re.I)
MSSQL_LOCAL = re.compile(
    r"^(declare\s+@\w+|set\s+@\w+\s*[-+*/%&|^]?=|insert\s+(into\s+)?@\w+(?=\s*(\(|select\b|with\b|values\b)))",
    re.I,
)
MSSQL_RISKY = re.compile(
    KEYWORD_START + r"(insert|update|delete|merge|truncate|into|exec|execute|create|alter|drop|grant|revoke|deny|"
    r"backup|restore|dbcc|kill|shutdown|waitfor|output|begin|commit|rollback|save|transaction|tran|set|declare|"
    r"use|bulk|openrowset|openquery|opendatasource|openxml|reconfigure|checkpoint|go|writetext|updatetext|"
    r"next\s+value\s+for|sp_\w+|xp_\w+|add|disable|enable|receive|send|setuser|dump|load|rename|"
    r"end\s+conversation|move\s+conversation|get\s+conversation|with\s+([\w\s,]*\b)?log)\b",
    re.I,
)
DOLLAR_TAG = re.compile(r"\$(?:[^\W\d]\w*)?\$")
UNCERTAIN_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x85\u2028\u2029]|\r(?!\n)")


def is_ident_char(ch: str) -> bool:
    return ch.isalnum() or ch in "_$"


def skip_quoted(sql: str, start: int, quote: str, backslash: bool = False) -> int:
    index = start + 1
    while index < len(sql):
        ch = sql[index]
        if backslash and ch == "\\":
            index += 2
        elif ch == quote:
            if sql[index + 1:index + 2] == quote:
                index += 2
            else:
                return index + 1
        else:
            index += 1
    raise ValueError("unterminated quoted text")


def skip_block_comment(sql: str, start: int) -> int:
    depth = 1
    index = start + 2
    while index < len(sql) and depth:
        if sql.startswith("/*", index):
            depth += 1
            index += 2
        elif sql.startswith("*/", index):
            depth -= 1
            index += 2
        else:
            index += 1
    if depth:
        raise ValueError("unterminated block comment")
    return index


def is_unicode_escape_prefix(sql: str, quote_index: int) -> bool:
    return (
        quote_index >= 2
        and sql[quote_index - 1] == "&"
        and sql[quote_index - 2] in "uU"
        and (quote_index < 3 or not is_ident_char(sql[quote_index - 3]))
    )


def sanitize(sql: str, postgres: bool) -> str:
    if UNCERTAIN_CHARS.search(sql) or any(unicodedata.category(ch) == "Cf" for ch in sql):
        raise ValueError("uncertain character")
    out = []
    index = 0
    while index < len(sql):
        ch = sql[index]
        if ch == "'":
            if postgres and is_unicode_escape_prefix(sql, index):
                raise ValueError("unicode escape string")
            escaped = postgres and index > 0 and sql[index - 1] in "eE" and (index < 2 or not is_ident_char(sql[index - 2]))
            end = skip_quoted(sql, index, "'", escaped)
            if postgres and not escaped and "\\" in sql[index:end]:
                raise ValueError("backslash in plain string")
            index = end
            out.append(PLACEHOLDER)
        elif ch == '"':
            if postgres and is_unicode_escape_prefix(sql, index):
                raise ValueError("unicode escape identifier")
            end = skip_quoted(sql, index, '"')
            if postgres:
                content = sql[index + 1:end - 1].replace('""', '"')
                out.append(" " + re.sub(r"\W", " ", content) + " ")
            else:
                out.append(PLACEHOLDER)
            index = end
        elif ch == "[" and not postgres:
            index = skip_quoted(sql, index, "]")
            out.append(PLACEHOLDER)
        elif ch == "$" and postgres:
            if (index > 0 and is_ident_char(sql[index - 1])) or not DOLLAR_TAG.match(sql, index):
                raise ValueError("stray dollar sign")
            tag = DOLLAR_TAG.match(sql, index).group(0)
            end = sql.find(tag, index + len(tag))
            if end < 0:
                raise ValueError("unterminated dollar quote")
            index = end + len(tag)
            out.append(PLACEHOLDER)
        elif sql.startswith("--", index):
            end = sql.find("\n", index)
            index = len(sql) if end < 0 else end
            out.append(" ")
        elif sql.startswith("/*", index):
            index = skip_block_comment(sql, index)
            out.append(" ")
        elif ch in "{}":
            raise ValueError("jdbc escape syntax")
        else:
            out.append(ch)
            index += 1
    return "".join(out)


def split_statements(sql: str, postgres: bool) -> list:
    return [s.strip() for s in sanitize(sql, postgres).split(";") if s.strip()]


def fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def has_unsafe_postgres_call(text: str) -> bool:
    for match in PG_FUNCTION_CALL.finditer(text):
        if match.group(1).lower() not in PG_SAFE_FUNCTIONS:
            return True
    for match in QUALIFIED_CALL.finditer(text):
        schemas = re.split(r"\s*\.\s*", match.group(1))[:-1]
        if any(schema.lower() not in PG_SAFE_SCHEMAS for schema in schemas):
            return True
    return False


def is_postgres_read_query(query: str) -> bool:
    if not QUERY_START.match(query):
        return False
    folded = fold(query)
    return not (EXPLAIN_ANALYZE.match(folded) or RISKY.search(folded) or has_unsafe_postgres_call(folded))


def postgres_read_state_regex(sql: str):
    statements = split_statements(sql, True)
    read_only = False
    index = 0
    while index < len(statements) and PRELUDE.match(statements[index]):
        name, _, value = PRELUDE.match(statements[index]).groups()
        if name.lower() == "transaction_read_only":
            if value.lower() not in ("on", "true"):
                return None
            read_only = True
        index += 1
    queries = statements[index:]
    if not queries:
        return None
    for query in queries:
        if not is_postgres_read_query(query):
            return None
    return read_only


def has_uncertain_characters(sql: str) -> bool:
    return bool(UNCERTAIN_CHARS.search(sql)) or any(unicodedata.category(ch) == "Cf" for ch in sql)


def has_plain_backslash_string(sql: str) -> bool:
    for token in pglast_parser.scan(sql):
        if token.name == "SCONST":
            text = sql[token.start:token.end + 1]
            if text.startswith("'") and "\\" in text:
                return True
    return False


def iter_nodes(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from iter_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_nodes(item)


def is_unsafe_function_call(call: dict) -> bool:
    names = [part["String"]["sval"].casefold() for part in call["funcname"]]
    if any(qualifier not in PG_SAFE_SCHEMAS for qualifier in names[:-1]):
        return True
    name = names[-1]
    return (name.startswith("pg_") and name not in PG_SAFE_FUNCTIONS) or bool(PG_RISKY_FUNCTIONS.fullmatch(name))


def is_unsafe_node(key: str, value) -> bool:
    if key in PG_WRITE_NODES:
        return True
    if key == "SelectStmt":
        return bool(value.get("intoClause") or value.get("lockingClause"))
    return key == "FuncCall" and is_unsafe_function_call(value)


def statement_kind(stmt: dict):
    (kind, body), = stmt.items()
    return kind, body


def prelude_setting(stmt: dict):
    kind, body = statement_kind(stmt)
    if kind != "VariableSetStmt" or not body.get("is_local") or body.get("kind") != "VAR_SET_VALUE":
        return None
    name = body.get("name", "").casefold()
    return name if name in PG_PRELUDE_SETTINGS else None


def is_read_only_on(stmt: dict) -> bool:
    args = statement_kind(stmt)[1].get("args") or []
    if len(args) != 1:
        return False
    constant = args[0].get("A_Const", {})
    if "sval" in constant:
        return constant["sval"].get("sval", "").casefold() in ("on", "true")
    return constant.get("boolval", {}).get("boolval") is True


def is_parser_read_statement(stmt: dict) -> bool:
    kind, body = statement_kind(stmt)
    if kind in ("SelectStmt", "VariableShowStmt"):
        return True
    if kind != "ExplainStmt":
        return False
    options = body.get("options") or []
    if any(option["DefElem"]["defname"].casefold() in ("analyze", "analyse") for option in options):
        return False
    return statement_kind(body["query"])[0] == "SelectStmt"


def postgres_read_state_parser(sql: str):
    try:
        if has_uncertain_characters(sql):
            return None
        statements = [entry["stmt"] for entry in json.loads(pglast_parser.parse_sql_json(sql)).get("stmts", [])]
        if has_plain_backslash_string(sql):
            return None
        read_only = False
        index = 0
        while index < len(statements) and prelude_setting(statements[index]):
            if prelude_setting(statements[index]) == "transaction_read_only":
                if not is_read_only_on(statements[index]):
                    return None
                read_only = True
            index += 1
        queries = statements[index:]
        if not queries:
            return None
        for stmt in queries:
            if not is_parser_read_statement(stmt):
                return None
            if any(is_unsafe_node(key, value) for key, value in iter_nodes(stmt)):
                return None
        return read_only
    except Exception:
        return None


def postgres_read_state(sql: str):
    if pglast_parser is None:
        return postgres_read_state_regex(sql)
    return postgres_read_state_parser(sql)


def is_mssql_read_statement(statement: str) -> bool:
    local = MSSQL_LOCAL.match(statement)
    if local:
        return not MSSQL_RISKY.search(fold(statement[local.end():]))
    return bool(MSSQL_START.match(statement)) and not MSSQL_RISKY.search(fold(statement))


def is_mssql_read(sql: str) -> bool:
    statements = split_statements(sql, False)
    if not statements:
        return False
    return all(is_mssql_read_statement(s) for s in statements)


def result(decision: str, reason: str, updated_input: dict = None) -> dict:
    output = {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }
    if updated_input is not None:
        output["updatedInput"] = updated_input
    return {"hookSpecificOutput": output}


def find_data_source(tool_input: dict):
    project = tool_input.get("projectPath")
    connection_id = tool_input.get("connectionId")
    if not isinstance(project, str) or not project or not isinstance(connection_id, str) or not connection_id:
        return None
    try:
        root = ET.parse(Path(project) / ".idea" / "dataSources.xml").getroot()
    except (OSError, ET.ParseError, ValueError):
        return None
    for element in root.iter("data-source"):
        if element.get("uuid") == connection_id:
            return element
    return None


def connection_kind(tool_input: dict) -> str:
    """Return always, unknown, unsupported, postgres, or mssql for the data source named by the tool input."""
    source = find_data_source(tool_input)
    if source is None:
        return "unknown"
    if APPROVAL_MARK in (source.get("name") or ""):
        return "always"
    driver = (source.findtext("driver-ref") or "").strip().lower()
    if driver == "postgresql":
        return "postgres"
    if driver.startswith("sqlserver") or driver.startswith("azure"):
        return "mssql"
    return "unsupported"


def decide_postgres(tool_input: dict, sql: str) -> dict:
    try:
        read_only = postgres_read_state(sql)
    except ValueError:
        read_only = None
    if read_only is None:
        return result("ask", ASK_REASON)
    if read_only:
        return result("allow", PG_ALLOW_REASON)
    updated = dict(tool_input)
    updated["queryText"] = READ_ONLY_PRELUDE + sql
    return result("allow", PG_ALLOW_REASON, updated)


def decide_mssql(sql: str) -> dict:
    try:
        is_read = is_mssql_read(sql)
    except ValueError:
        is_read = False
    return result("allow", MSSQL_ALLOW_REASON) if is_read else result("ask", ASK_REASON)


def decide(tool_input) -> dict:
    if not isinstance(tool_input, dict):
        return result("ask", ASK_REASON)
    kind = connection_kind(tool_input)
    if kind == "always":
        return result("ask", ALWAYS_ASK_REASON)
    if kind == "unknown":
        return result("ask", UNKNOWN_REASON)
    if kind == "unsupported":
        return result("ask", UNSUPPORTED_REASON)
    sql = tool_input.get("queryText")
    if not isinstance(sql, str):
        return result("ask", ASK_REASON)
    return decide_postgres(tool_input, sql) if kind == "postgres" else decide_mssql(sql)


def classify_read(tool_input):
    if not isinstance(tool_input, dict):
        return None
    sql = tool_input.get("queryText")
    if not isinstance(sql, str):
        return None
    kind = connection_kind(tool_input)
    try:
        if kind == "postgres":
            read_only = postgres_read_state(sql)
            return None if read_only is None else (sql, True, read_only)
        if kind == "mssql":
            return (sql, False, True) if is_mssql_read(sql) else None
    except ValueError:
        return None
    return None


def codex_pre_tool_use(tool_input):
    classified = classify_read(tool_input)
    if classified is None:
        return None
    sql, postgres, read_only = classified
    if not postgres or read_only:
        return None
    updated = dict(tool_input)
    updated["queryText"] = READ_ONLY_PRELUDE + sql
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "updatedInput": updated,
    }}


def codex_permission_request(tool_input):
    if classify_read(tool_input) is None:
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PermissionRequest",
        "decision": {"behavior": "allow"},
    }}


def detect_host() -> str:
    root = Path(__file__).resolve().parents[1]
    codex_root = os.environ.get("PLUGIN_ROOT")
    return "codex" if codex_root and Path(codex_root).resolve() == root else "claude"


def handle(event):
    if not isinstance(event, dict) or event.get("tool_name") != TOOL_NAME:
        return None
    name = event.get("hook_event_name")
    tool_input = event.get("tool_input")
    if detect_host() == "claude":
        if name != "PreToolUse":
            return None
        try:
            return decide(tool_input)
        except Exception:
            return result("ask", ASK_REASON)
    try:
        if name == "PreToolUse":
            return codex_pre_tool_use(tool_input)
        if name == "PermissionRequest":
            return codex_permission_request(tool_input)
    except Exception:
        return None
    return None


def parser_python() -> Path:
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "hei5enbug-agent-setup" / "sql-parser" / "bin" / "python"


def reexec_with_parser() -> None:
    interpreter = parser_python()
    if pglast_parser is None and interpreter.exists() and not os.environ.get(REEXEC_GUARD):
        os.environ[REEXEC_GUARD] = "1"
        try:
            os.execv(str(interpreter), [str(interpreter), str(Path(__file__).absolute()), *sys.argv[1:]])
        except OSError:
            pass


def main() -> int:
    reexec_with_parser()
    try:
        output = handle(json.load(sys.stdin))
    except Exception:
        output = None
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
