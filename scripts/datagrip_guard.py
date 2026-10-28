#!/usr/bin/env python3
"""Approval guard for the DataGrip `execute_sql_query` tool, shared by Claude Code and Codex.

The data source is resolved from `<projectPath>/.idea/dataSources.xml` by matching `connectionId` to the `uuid` of a
`data-source` element. The `driver-ref` selects the database: `postgresql`, or a value starting with `sqlserver` or
`azure`. Any other driver, an unreadable file, or an unknown uuid asks. With the `approval_guard` toggle on, a read on
a production data source (see db_read_policy) needs a recorded plan for PostgreSQL and gets lock and result safeguards
for SQL Server.

Only queries that are certainly reads run without approval. With the `approval_guard` toggle on, a PostgreSQL or SQL
Server write uses the shared mcp:session approval key, and Codex denies it with a one-time code. A statement whose
code (literals, comments, and quoted identifiers removed) names delete, drop, or truncate, and everything else that is
not a read, asks every time.
  - PostgreSQL with pglast: every statement must be SELECT, VALUES, TABLE, SHOW, or EXPLAIN of a SELECT without
    ANALYZE, and the parse tree must hold no INSERT, UPDATE, DELETE, MERGE, INTO, locking clause, or risky function
    call. Reads run in a read-only transaction through a prepended `SET LOCAL transaction_read_only = on;`.
  - PostgreSQL without pglast: a regex classifier over text with strings, quoted identifiers, and comments removed.
  - SQL Server: every statement starts with SELECT or WITH and holds no write, execute, or side-effect keyword.
    Session variable statements (DECLARE @v, SET @v =, INSERT [INTO] @v) and the listed session SET statements count
    as reads under the same condition.
  - Control characters, invisible format characters, JDBC escapes, unterminated literals, and parse errors ask.
Codex denies only unapproved writes and always-asking queries, through approval_state; the guard always exits 0.
While Codex's native approval window can ask (the approval guard's native_ready), it leaves a write to the
window instead and remembers the session approval it grants; an always-asking query keeps the one-time code.

Claude Code PreToolUse prints a permission decision; PermissionRequest prints nothing. Codex PreToolUse prints an
allow with the read-only prefix for PostgreSQL reads, and PermissionRequest prints an allow for any read. Anything
undecided prints nothing, which leaves the host's own approval flow in charge.

When pglast is not importable and `$XDG_STATE_HOME/hei5enbug-agent-setup/sql-parser/bin/python` exists (default
`~/.local/state`), the script re-executes itself once with that interpreter.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from plugin_toggles import enabled  # noqa: E402
import approval_state  # noqa: E402
import db_read_policy  # noqa: E402
from approval_state import Outcome  # noqa: E402

try:
    from pglast import parser as pglast_parser
except Exception:
    pglast_parser = None

TOOL_NAME = "mcp__datagrip__execute_sql_query"
REEXEC_GUARD = "HEI5ENBUG_SQL_PARSER_REEXEC"

UNKNOWN_REASON = "The DataGrip data source could not be identified from the project settings. Review the SQL and approve it."
UNSUPPORTED_REASON = "Only PostgreSQL and SQL Server data sources are checked automatically. Review the SQL and approve it."
ASK_REASON = "This query writes or cannot be classified as a read. Review the SQL and approve it."
PG_ALLOW_REASON = "Classified as a PostgreSQL read; it runs in a read-only transaction."
MSSQL_ALLOW_REASON = "Classified as a SQL Server read; it runs without approval."

READ_ONLY_PRELUDE = "SET LOCAL transaction_read_only = on;\nSET LOCAL statement_timeout = '60s';\n"
PLACEHOLDER = " __lit__ "

RAW_DESTRUCTIVE = re.compile(r"\b(?:delete|drop|truncate)\b", re.IGNORECASE)
RISKY_LEADERS = frozenset({"do", "exec", "execute", "call"})
DELETE_WORD = re.compile(r"\bdelete\b", re.IGNORECASE)
OTHER_DESTRUCTIVE = re.compile(r"\b(?:drop|truncate)\b", re.IGNORECASE)
DO_STATEMENT = re.compile(r"do(?: language plpgsql)? __lit__(?: language plpgsql)?", re.IGNORECASE)
DO_BODY_FORBIDDEN = re.compile(r"\b(?:drop|truncate|execute|exec|alter|grant|revoke|call)\b", re.IGNORECASE)
DO_STATEMENT_START = re.compile(r"(?:^|;|\b(?:begin|then|else|loop))\s*do\b", re.IGNORECASE)
DO_ALLOWED_CALLS = re.compile(r"set_config|pg_sleep\w*", re.IGNORECASE)
PLPGSQL_WRAPPER = "CREATE FUNCTION pg_temp.f() RETURNS void LANGUAGE plpgsql AS "
CALLED_NAME = re.compile(r"(?<![^\W\d])(\w+)\s*\(")
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
MSSQL_SESSION_SET = re.compile(
    r"set\s+(?:nocount\s+(?:on|off)"
    r"|lock_timeout\s+-?\d+"
    r"|deadlock_priority\s+(?:low|normal|-?\d+)"
    r"|transaction\s+isolation\s+level\s+(?:read\s+uncommitted|read\s+committed|snapshot)"
    r"|(?:arithabort|ansi_nulls|ansi_warnings|ansi_padding|quoted_identifier|concat_null_yields_null|xact_abort)"
    r"\s+(?:on|off)"
    r"|statistics\s+(?:io|time)\s+(?:on|off)"
    r"|showplan_(?:xml|all|text)\s+(?:on|off))",
    re.I,
)
MSSQL_BOUND_SETTING = re.compile(r"^set\s+(lock_timeout|deadlock_priority)\b", re.I)
PLAN_STATEMENT = re.compile(r"^explain\s*(?:\([^()]*\))?\s*(?P<read>\S.*)$", re.I | re.S)
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


def _sanitized_pieces(sql: str, postgres: bool, blank_identifiers: bool = False) -> list:
    """The sanitized text as (kept code, original source) pairs."""
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
            out.append((PLACEHOLDER, sql[index:end]))
            index = end
        elif ch == '"':
            if postgres and is_unicode_escape_prefix(sql, index):
                raise ValueError("unicode escape identifier")
            end = skip_quoted(sql, index, '"')
            if postgres and not blank_identifiers:
                content = sql[index + 1:end - 1].replace('""', '"')
                out.append((" " + re.sub(r"\W", " ", content) + " ", sql[index:end]))
            else:
                out.append((PLACEHOLDER, sql[index:end]))
            index = end
        elif ch == "[" and not postgres:
            end = skip_quoted(sql, index, "]")
            out.append((PLACEHOLDER, sql[index:end]))
            index = end
        elif ch == "$" and postgres:
            if (index > 0 and is_ident_char(sql[index - 1])) or not DOLLAR_TAG.match(sql, index):
                raise ValueError("stray dollar sign")
            tag = DOLLAR_TAG.match(sql, index).group(0)
            end = sql.find(tag, index + len(tag))
            if end < 0:
                raise ValueError("unterminated dollar quote")
            end += len(tag)
            out.append((PLACEHOLDER, sql[index:end]))
            index = end
        elif sql.startswith("--", index):
            end = sql.find("\n", index)
            end = len(sql) if end < 0 else end
            out.append((" ", sql[index:end]))
            index = end
        elif sql.startswith("/*", index):
            end = skip_block_comment(sql, index)
            out.append((" ", sql[index:end]))
            index = end
        elif ch in "{}":
            raise ValueError("jdbc escape syntax")
        else:
            out.append((ch, ch))
            index += 1
    return out


def sanitize(sql: str, postgres: bool, blank_identifiers: bool = False) -> str:
    """Remove literals, comments, and bracketed identifiers; PostgreSQL keeps the contents of a quoted identifier
    unless `blank_identifiers` is set."""
    return "".join(code for code, _ in _sanitized_pieces(sql, postgres, blank_identifiers))


def _statement_parts(sql: str, postgres: bool) -> list:
    """(code, original source, literals) for each statement, with quoted identifiers blanked."""
    parts, code, source, literals = [], [], [], []
    for text, original in _sanitized_pieces(sql, postgres, True) + [(";", "")]:
        if text != ";":
            code.append(text)
            source.append(original)
            if text == PLACEHOLDER:
                literals.append(original)
            continue
        joined = "".join(code).strip()
        if joined:
            parts.append((joined, "".join(source), literals))
        code, source, literals = [], [], []
    return parts


def split_statements(sql: str, postgres: bool, blank_identifiers: bool = False) -> list:
    return [s.strip() for s in sanitize(sql, postgres, blank_identifiers).split(";") if s.strip()]


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
    if MSSQL_SESSION_SET.fullmatch(fold(statement)):
        return True
    local =MSSQL_LOCAL.match(statement)
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
    """Return unknown, unsupported, postgres, or mssql for the data source named by the tool input."""
    source = find_data_source(tool_input)
    if source is None:
        return "unknown"
    driver = (source.findtext("driver-ref") or "").strip().lower()
    if driver == "postgresql":
        return "postgres"
    if driver.startswith("sqlserver") or driver.startswith("azure"):
        return "mssql"
    return "unsupported"


def database_target(tool_input):
    """(connection id, name, postgres, sql) for a call on a PostgreSQL or SQL Server data source, else None."""
    kind = connection_kind(tool_input) if isinstance(tool_input, dict) else "unknown"
    sql = tool_input.get("queryText") if isinstance(tool_input, dict) else None
    if kind not in ("postgres", "mssql") or not isinstance(sql, str):
        return None
    return tool_input["connectionId"], find_data_source(tool_input).get("name"), kind == "postgres", sql


def approval_on() -> bool:
    return enabled("approval_guard")


def is_destructive(sql: str, postgres=None) -> bool:
    """Whether the SQL code names delete, drop, or truncate, or a statement is led by DO, EXEC, EXECUTE, or CALL.

    The check runs on the code left after `sanitize` blanks literals, comments, and quoted or bracketed identifiers in
    both dialects; text that cannot be sanitized keeps the raw check. A `postgres` of None checks both dialects.
    """
    for dialect in (True, False) if postgres is None else (postgres,):
        try:
            code = sanitize(sql, dialect, True)
        except ValueError:
            code = sql
        if RAW_DESTRUCTIVE.search(code) or _leads_with_risky(sql, dialect, True):
            return True
    return False


def _leads_with_risky(sql: str, postgres: bool, blank_identifiers: bool = False) -> bool:
    try:
        statements = split_statements(sql, postgres, blank_identifiers)
    except ValueError:
        return False
    return any(
        (match := re.match(r"([A-Za-z]+)\b", statement)) is not None and match.group(1).lower() in RISKY_LEADERS
        for statement in statements
    )


def _delete_has_where(code: str, end: int) -> bool:
    depth = 0
    for token in re.finditer(r"[()]|\bwhere\b", code[end:], re.IGNORECASE):
        if token.group() == "(":
            depth += 1
        elif token.group() == ")":
            depth -= 1
            if depth < 0:
                return False
        elif depth == 0:
            return True
    return False


def _deletes_targeted(code: str) -> bool:
    """Whether every DELETE in one statement's code stands outside any parentheses and is followed by a WHERE of its own
    outside any parentheses."""
    return all(
        code.count("(", 0, match.start()) == code.count(")", 0, match.start()) and _delete_has_where(code, match.end())
        for match in DELETE_WORD.finditer(code)
    )


def _parser_confirms_deletes(source: str, count: int) -> bool:
    """The statement parses with pglast and holds exactly `count` DELETE statements, each with a WHERE clause."""
    try:
        nodes = [value for key, value in iter_nodes(json.loads(pglast_parser.parse_sql_json(source))) if key == "DeleteStmt"]
    except Exception:
        return False
    return len(nodes) == count and all(node.get("whereClause") for node in nodes)


def _safe_do_body(body: str) -> bool:
    """Whether a PL/pgSQL body is parseable and holds no drop, truncate, dynamic SQL, alter, grant, revoke, call, nested
    DO, DELETE without its own WHERE, or risky function call. Keywords are checked with quoted identifiers blanked,
    function names with their quoted contents kept."""
    try:
        parts = _statement_parts(body, True)
        named = fold(sanitize(body, True))
    except ValueError:
        return False
    code = fold(";".join(part[0] for part in parts))
    if not parts or DO_BODY_FORBIDDEN.search(code) or DO_STATEMENT_START.search(code):
        return False
    if not all(_deletes_targeted(part[0]) for part in parts):
        return False
    if any(PG_RISKY_FUNCTIONS.fullmatch(name) and not DO_ALLOWED_CALLS.fullmatch(name) for name in CALLED_NAME.findall(named)):
        return False
    return all(name.lower() in PG_SAFE_FUNCTIONS or DO_ALLOWED_CALLS.fullmatch(name) for name in PG_FUNCTION_CALL.findall(named))


def _is_plpgsql(literal: str) -> bool:
    """Whether pglast's PL/pgSQL parser accepts the quoted DO body, kept exactly as written, as a function body."""
    try:
        pglast_parser.parse_plpgsql_json(PLPGSQL_WRAPPER + literal)
    except Exception:
        return False
    return True


def _safe_do(code: str, literals: list) -> bool:
    if len(literals) != 1 or not DO_STATEMENT.fullmatch(" ".join(code.split())):
        return False
    literal = literals[0]
    if pglast_parser is None or not _is_plpgsql(literal):
        return False
    if literal.startswith("$"):
        tag = DOLLAR_TAG.match(literal).group(0)
        return _safe_do_body(literal[len(tag):-len(tag)])
    if literal.startswith("'"):
        return _safe_do_body(literal[1:-1].replace("''", "'"))
    return False


def targeted_writes_only(sql: str, postgres: bool) -> bool:
    """Whether the only destructive parts of the SQL are DELETE statements with a top-level WHERE and PostgreSQL DO
    blocks whose body is safe; every other destructive statement, and any text that cannot be parsed, is False. Only
    PostgreSQL text classified with pglast can qualify."""
    if not postgres or pglast_parser is None:
        return False
    try:
        parts = _statement_parts(sql, postgres)
        pglast_parser.parse_sql_json(sql)
    except Exception:
        return False
    if not parts:
        return False
    for code, source, literals in parts:
        leader = re.match(r"([A-Za-z]+)\b", code)
        word = leader.group(1).lower() if leader else ""
        if word == "do":
            if not _safe_do(code, literals):
                return False
        elif word in RISKY_LEADERS or OTHER_DESTRUCTIVE.search(code):
            return False
        else:
            count = len(DELETE_WORD.findall(code))
            if count and not (_deletes_targeted(code) and _parser_confirms_deletes(source, count)):
                return False
    return True


def asks_every_time(sql: str, postgres, name) -> bool:
    """Whether destructive SQL on the connection called `name` asks every time. A connection that is not production
    waives a DELETE with a top-level WHERE and a PostgreSQL DO block with a safe body; `postgres` None never waives."""
    if not is_destructive(sql, postgres):
        return False
    return postgres is None or db_read_policy.is_production(name) or not targeted_writes_only(sql, postgres)


def is_read(sql: str, postgres: bool) -> bool:
    """A read is a read only when its code names no delete, drop, or truncate and no statement is led by DO, EXEC, CALL."""
    if is_destructive(sql, postgres):
        return False
    try:
        return postgres_read_state(sql) is not None if postgres else is_mssql_read(sql)
    except ValueError:
        return False


def strip_prelude(sql: str) -> str:
    return sql[len(READ_ONLY_PRELUDE):] if sql.startswith(READ_ONLY_PRELUDE) else sql


def read_shape(sql: str):
    """Classify a PostgreSQL read for the plan gate: ("plan", read) for a single EXPLAIN without ANALYZE, ("read", sql)
    for any other single read, ("many", None) for several statements, and (None, None) for text that cannot be split."""
    sql = strip_prelude(sql).strip()
    try:
        count = len(split_statements(sql, True))
    except ValueError:
        return None, None
    if count != 1:
        return "many", None
    match = PLAN_STATEMENT.match(sql)
    if match and is_read(sql, True):
        return "plan", match.group("read")
    return "read", sql


def session_settings(sql: str) -> set:
    """The names of the SQL Server LOCK_TIMEOUT and DEADLOCK_PRIORITY settings that the text already sets."""
    try:
        statements = split_statements(sql, False)
    except ValueError:
        return set()
    return {match.group(1).lower() for statement in statements if (match := MSSQL_BOUND_SETTING.match(statement))}


def query_facts(sql: str, postgres: bool, name=None):
    """Return (leading keywords, destructive); keywords is None when the text cannot be parsed.

    The text is destructive when its code, with literals, comments, and quoted identifiers removed, names delete, drop,
    or truncate, or when a statement is led by DO, EXEC, EXECUTE, or CALL. With a connection `name`, a connection that
    is not production waives what `asks_every_time` waives.
    """
    try:
        if postgres and pglast_parser is not None:
            pglast_parser.parse_sql_json(sql)
        statements = split_statements(sql, postgres)
    except Exception:
        return None, False
    if not statements:
        return None, False
    keywords = set()
    for statement in statements:
        match = re.match(r"([A-Za-z]+)\b", statement)
        if match is None:
            return None, False
        keywords.add(match.group(1).lower())
    return keywords, asks_every_time(sql, postgres, name) if name is not None else is_destructive(sql, postgres)


def always_outcome(tool_input, sql) -> Outcome:
    text = sql if isinstance(sql, str) else json.dumps(tool_input, sort_keys=True, default=str)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    source = find_data_source(tool_input) if isinstance(tool_input, dict) else None
    name = (source.get("name") if source is not None else None) or "an unidentified data source"
    connection = tool_input.get("connectionId") if isinstance(tool_input, dict) else None
    connection = connection if isinstance(connection, str) and connection else "unknown"
    return Outcome("always", [f"sql:always:{connection}:{digest}"], [f"DataGrip query on {name}"], every_time=True,
                   critical=db_read_policy.is_production(source.get("name") if source is not None else None))


def classify_query(tool_input) -> Outcome:
    """Classify a DataGrip query as read, write (asks once per session), or always (asks every time)."""
    sql = tool_input.get("queryText") if isinstance(tool_input, dict) else None
    kind = connection_kind(tool_input) if isinstance(tool_input, dict) else "unknown"
    source = find_data_source(tool_input) if isinstance(tool_input, dict) else None
    name = source.get("name") if source is not None else None
    if isinstance(sql, str) and asks_every_time(sql, {"postgres": True, "mssql": False}.get(kind), name):
        return always_outcome(tool_input, sql)
    if kind in ("unknown", "unsupported") or not isinstance(sql, str):
        if approval_state.session_scope():
            return always_outcome(tool_input, sql)._replace(critical=True)
        return Outcome("write", ["mcp:session"], ["DataGrip query requiring approval"])
    postgres = kind == "postgres"
    if is_read(sql, postgres):
        return Outcome("read", [], [])
    keywords, destructive = query_facts(sql, postgres, name)
    if destructive:
        return always_outcome(tool_input, sql)
    listed = ", ".join(sorted(keywords)) if keywords else "unclassified"
    if not keywords and approval_state.session_scope():
        return always_outcome(tool_input, sql)._replace(critical=True)
    return Outcome(
        "write",
        ["mcp:session"],
        [f"DataGrip write ({listed}) on {name or 'an unnamed data source'}"],
    )


def unapproved_write(tool_input, session_id, tool_use_id=None) -> dict:
    """Claude decision for a query that is not a read: an approved write runs without the prelude, anything else asks."""
    if not approval_on():
        return result("ask", ASK_REASON)
    outcome = classify_query(tool_input)
    if outcome.kind == "write" or approval_state.parent_session():
        return approval_state.pre_decision("claude", session_id, outcome, tool_use_id)
    return result("ask", ASK_REASON)


def read_policy(host: str, tool_input: dict, sql: str, postgres: bool, session_id) -> Outcome:
    """Outcome of an accepted read under the production database policy; a plain read when the approval guard is off."""
    if not approval_on():
        return Outcome("read", [], [])
    source = find_data_source(tool_input)
    return db_read_policy.read_outcome(
        host, session_id, "datagrip", tool_input.get("connectionId"), source.get("name") if source is not None else None,
        postgres, sql, read_shape(sql) if postgres else None,
    )


def policy_response(host: str, outcome: Outcome, session_id, tool_use_id):
    """The hook output for a read that the production policy denies or asks about, otherwise None."""
    if outcome.kind == "forbidden":
        return result("deny", outcome.descriptions[0])
    if outcome.kind == "always":
        return approval_state.pre_decision(host, session_id, outcome, tool_use_id)
    return None


def enforced_input(tool_input: dict, sql: str, outcome: Outcome) -> dict:
    source = find_data_source(tool_input)
    names = (tool_input.get("connectionId"), source.get("name") if source is not None else None)
    return db_read_policy.enforce("datagrip", tool_input, outcome.exe, names, session_settings(sql))


def decide_postgres(tool_input: dict, sql: str, session_id=None, tool_use_id=None) -> dict:
    if not is_read(sql, True):
        return unapproved_write(tool_input, session_id, tool_use_id)
    outcome = read_policy("claude", tool_input, sql, True, session_id)
    blocked = policy_response("claude", outcome, session_id, tool_use_id)
    if blocked is not None:
        return blocked
    read_only = postgres_read_state(sql)
    if read_only:
        return result("allow", PG_ALLOW_REASON)
    updated = dict(tool_input)
    updated["queryText"] = READ_ONLY_PRELUDE + sql
    return result("allow", PG_ALLOW_REASON, updated)


def decide_mssql(sql: str, tool_input=None, session_id=None, tool_use_id=None) -> dict:
    if is_read(sql, False):
        outcome = read_policy("claude", tool_input, sql, False, session_id) if tool_input is not None else None
        blocked = policy_response("claude", outcome, session_id, tool_use_id) if outcome is not None else None
        if blocked is not None:
            return blocked
        if outcome is not None and outcome.exe:
            return result("allow", MSSQL_ALLOW_REASON, enforced_input(tool_input, sql, outcome))
        return result("allow", MSSQL_ALLOW_REASON)
    return unapproved_write(tool_input, session_id, tool_use_id) if tool_input is not None else result("ask", ASK_REASON)


def decide(tool_input, session_id=None, tool_use_id=None) -> dict:
    if not isinstance(tool_input, dict):
        return result("ask", ASK_REASON)
    if approval_on():
        outcome = classify_query(tool_input)
        if outcome.kind != "read":
            return approval_state.pre_decision("claude", session_id, outcome, tool_use_id)
    kind = connection_kind(tool_input)
    if kind == "unknown":
        return result("ask", UNKNOWN_REASON)
    if kind == "unsupported":
        return result("ask", UNSUPPORTED_REASON)
    sql = tool_input.get("queryText")
    if not isinstance(sql, str):
        return result("ask", ASK_REASON)
    if kind == "postgres":
        return decide_postgres(tool_input, sql, session_id, tool_use_id)
    return decide_mssql(sql, tool_input, session_id, tool_use_id)


def classify_read(tool_input):
    if not isinstance(tool_input, dict):
        return None
    sql = tool_input.get("queryText")
    if not isinstance(sql, str):
        return None
    kind = connection_kind(tool_input)
    if kind == "postgres":
        if not is_read(sql, True):
            return None
        return (sql, True, postgres_read_state(sql))
    if kind == "mssql":
        return (sql, False, True) if is_read(sql, False) else None
    return None


def _native_ready(event):
    """Whether Codex's native approval window asks for this call (the approval guard decides, see native_ready)."""
    if event is None:
        return False
    import guard_permissions
    return guard_permissions.native_ready(event)


def codex_unapproved(tool_input, session_id, tool_use_id=None, event=None):
    """Codex decision for a query that is not a read: an approved write proceeds, an always query needs a one-time code.

    When the native window can ask, a write is left to it and no code is issued; an always query keeps the code flow.
    """
    if not approval_on():
        return None
    outcome = classify_query(tool_input)
    if outcome.kind in ("write", "always"):
        if (outcome.kind == "write" and approval_state.session_key(session_id) is not None
                and _native_ready(event)):
            return None
        return approval_state.pre_decision("codex", session_id, outcome, tool_use_id)
    return None


def codex_pre_tool_use(tool_input, session_id=None, tool_use_id=None, event=None):
    classified = classify_read(tool_input)
    if classified is None:
        return codex_unapproved(tool_input, session_id, tool_use_id, event)
    sql, postgres, read_only = classified
    outcome = read_policy("codex", tool_input, sql, postgres, session_id)
    blocked = policy_response("codex", outcome, session_id, tool_use_id)
    if blocked is not None:
        return blocked
    if not postgres:
        if not outcome.exe:
            return None
        updated = enforced_input(tool_input, sql, outcome)
    elif read_only:
        return None
    else:
        updated = dict(tool_input)
        updated["queryText"] = READ_ONLY_PRELUDE + sql
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "updatedInput": updated,
    }}


def codex_permission_request(tool_input, session_id=None, tool_use_id=None, event=None):
    """Allow reads and approved queries; otherwise leave the native window to ask and remember what it grants."""
    if classify_read(tool_input) is None:
        if not approval_on():
            return None
        outcome = classify_query(tool_input)
        if event is not None and outcome.kind == "write" and _native_ready(event):
            import guard_permissions
            return guard_permissions.codex_permission(session_id, outcome, tool_use_id, tool_input, TOOL_NAME, event)
        if not approval_state.permission_allowed("codex", session_id, outcome, tool_use_id):
            return None
    return approval_state.permission_allow()


def detect_host() -> str:
    root = Path(__file__).resolve().parents[1]
    codex_root = os.environ.get("PLUGIN_ROOT")
    return "codex" if codex_root and Path(codex_root).resolve() == root else "claude"


def handle(event):
    if isinstance(event, dict):
        approval_state.heartbeat(detect_host(), event.get("session_id"), event.get("hook_event_name"))
    if not isinstance(event, dict) or event.get("tool_name") != TOOL_NAME:
        return None
    name = event.get("hook_event_name")
    tool_input = event.get("tool_input")
    session_id = event.get("session_id")
    tool_use_id = event.get("tool_use_id")
    if detect_host() == "claude":
        if name != "PreToolUse":
            return None
        try:
            return decide(tool_input, session_id, tool_use_id)
        except Exception:
            return approval_state.pre_decision("claude", session_id, Outcome(
                "always", ["sql:always:guard-failure"], ["The approval guard failed to check this call"], every_time=True,
                critical=True,
            ), tool_use_id)
    try:
        if name == "PreToolUse":
            return codex_pre_tool_use(tool_input, session_id, tool_use_id, event)
        if name == "PermissionRequest":
            return codex_permission_request(tool_input, session_id, tool_use_id, event)
    except Exception:
        if name == "PreToolUse":
            return approval_state.pre_decision("codex", session_id, Outcome(
                "always", ["sql:always:guard-failure"], ["The approval guard failed to check this call"], every_time=True,
                critical=True,
            ), tool_use_id)
    return None


def parser_python() -> Path:
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "hei5enbug-agent-setup" / "sql-parser" / "bin" / "python"


def output_possible(event) -> bool:
    if not isinstance(event, dict) or event.get("tool_name") != TOOL_NAME:
        return False
    return detect_host() != "claude" or event.get("hook_event_name") == "PreToolUse"


def run_with_parser(raw: bytes):
    """Run this script under the parser interpreter with the already-read input; None when it cannot run."""
    interpreter = parser_python()
    if pglast_parser is not None or not interpreter.exists() or os.environ.get(REEXEC_GUARD):
        return None
    try:
        return subprocess.run(
            [str(interpreter), str(Path(__file__).absolute()), *sys.argv[1:]],
            input=raw,
            stdout=subprocess.PIPE,
            env={**os.environ, REEXEC_GUARD: "1"},
        )
    except OSError:
        return None


def main() -> int:
    raw = sys.stdin.buffer.read()
    try:
        event = json.loads(raw)
    except ValueError:
        return 0
    if isinstance(event, dict):
        approval_state.heartbeat(detect_host(), event.get("session_id"), event.get("hook_event_name"))
    if not enabled("datagrip_guard"):
        return 0
    if not output_possible(event):
        return 0
    child = run_with_parser(raw)
    if child is not None:
        sys.stdout.buffer.write(child.stdout)
        sys.stdout.buffer.flush()
        return child.returncode if child.returncode >= 0 else 1
    try:
        output = handle(event)
    except Exception:
        output = None
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
