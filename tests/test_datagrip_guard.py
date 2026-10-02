import atexit
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "scripts" / "datagrip_guard.py"
HOOKS = json.loads((REPO_ROOT / "hooks/hooks.json").read_text())["hooks"]
_spec = importlib.util.spec_from_file_location("datagrip_guard_under_test", HOOK_PATH)
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)

PG_ID = "11111111-1111-4111-8111-111111111111"
MSSQL_ID = "22222222-2222-4222-8222-222222222222"
AZURE_ID = "33333333-3333-4333-8333-333333333333"
PG_APPROVAL_ID = "44444444-4444-4444-8444-444444444444"
MSSQL_APPROVAL_ID = "55555555-5555-4555-8555-555555555555"
AZURE_APPROVAL_ID = "66666666-6666-4666-8666-666666666666"
MYSQL_ID = "77777777-7777-4777-8777-777777777777"
UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"
ALWAYS_ASK_ID = PG_APPROVAL_ID
APPROVAL_IDS = [PG_APPROVAL_ID, MSSQL_APPROVAL_ID, AZURE_APPROVAL_ID]
READ_IDS = [PG_ID, MSSQL_ID, AZURE_ID]
TOOL_NAME = "mcp__datagrip__execute_sql_query"
CODEX_PERMISSION = "codex-permission"
CODEX_PRE_TOOL = "codex-pre-tool"

DATA_SOURCES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<project version="4">
  <component name="DataSourceManagerImpl" format="xml" multifile-model="true">
    <data-source source="LOCAL" name="demo-postgres" uuid="{pg}">
      <driver-ref>postgresql</driver-ref>
      <synchronize>true</synchronize>
    </data-source>
    <data-source source="LOCAL" name="demo-sqlserver" uuid="{ms}">
      <driver-ref>sqlserver.ms</driver-ref>
    </data-source>
    <data-source source="LOCAL" name="demo-azure" uuid="{az}">
      <driver-ref>azure.ms</driver-ref>
    </data-source>
    <data-source source="LOCAL" name="demo-postgres 승인" uuid="{pga}">
      <driver-ref>postgresql</driver-ref>
    </data-source>
    <data-source source="LOCAL" name="[승인 필요] demo-sqlserver" uuid="{msa}">
      <driver-ref>sqlserver.ms</driver-ref>
    </data-source>
    <data-source source="LOCAL" name="demo-azure (승인)" uuid="{aza}">
      <driver-ref>azure.ms</driver-ref>
    </data-source>
    <data-source source="LOCAL" name="demo-mysql" uuid="{my}">
      <driver-ref>mysql.8</driver-ref>
    </data-source>
  </component>
</project>
""".format(pg=PG_ID, ms=MSSQL_ID, az=AZURE_ID, pga=PG_APPROVAL_ID, msa=MSSQL_APPROVAL_ID, aza=AZURE_APPROVAL_ID, my=MYSQL_ID)

_PROJECT_TEMP = tempfile.TemporaryDirectory()
atexit.register(_PROJECT_TEMP.cleanup)
PROJECT = Path(_PROJECT_TEMP.name) / "demo project"
(PROJECT / ".idea").mkdir(parents=True)
(PROJECT / ".idea" / "dataSources.xml").write_text(DATA_SOURCES_XML, encoding="utf-8")
STATE_HOME = Path(_PROJECT_TEMP.name) / "state"
STATE_HOME.mkdir()

MSSQL_CORPUS_QUERY = r"""DECLARE @yr varchar(4) = '2031', @mo varchar(2) = '07';
DECLARE @pick TABLE (i int PRIMARY KEY); INSERT @pick VALUES (0),(1),(2),(3),(5),(8);
WITH seeds(i, code) AS (
  SELECT * FROM (VALUES (0,'AAA-001'),(1,'BBB-002')) v(i, code)
), base AS (
  SELECT d.origin_cd, d.dest_cd, d.carrier_id FROM demo.shipments d WITH (NOLOCK)
  JOIN seeds s ON s.code = d.owner_code COLLATE DATABASE_DEFAULT
  WHERE ((d.[YEAR] = '2030' AND d.[MONTH] IN ('11','12')) OR (d.[YEAR] = '2031' AND d.[MONTH] IN ('01','02')))
), origins AS (
  SELECT oc, ROW_NUMBER() OVER (ORDER BY oc) - 1 AS k FROM (SELECT origin_cd AS oc FROM base UNION SELECT dest_cd FROM base) u
), carriers AS (
  SELECT carrier_id, ROW_NUMBER() OVER (ORDER BY carrier_id) - 1 AS k FROM (SELECT DISTINCT carrier_id FROM base) d
), picked AS (
  SELECT d.*, s.i, o1.k AS ok1, o2.k AS ok2, c.k AS ck FROM demo.shipments d WITH (NOLOCK)
  JOIN seeds s ON s.code = d.owner_code COLLATE DATABASE_DEFAULT
  JOIN @pick k ON k.i = s.i
  JOIN origins o1 ON o1.oc = d.origin_cd
  JOIN origins o2 ON o2.oc = d.dest_cd
  JOIN carriers c ON c.carrier_id = d.carrier_id
  WHERE d.[YEAR] = @yr AND d.[MONTH] = @mo
)
SELECT COUNT(*) AS cnt, CAST(SUM(units) AS varchar(30)) AS total_units,
  SUM(CAST(BINARY_CHECKSUM(owner_code, origin_cd, dest_cd, carrier_id, carrier_nm, [YEAR], [MONTH], units, created_at) AS bigint)) AS chk,
  STRING_AGG(CAST(CONCAT(i, ',', ok1, ',', ok2, ',', ck, ',', FORMAT(units, '0.##')) AS varchar(max)), ';') WITHIN GROUP (ORDER BY shipment_id) AS digest
FROM picked
"""

KEYWORD_SEPARATORS = [
    ("space", " "),
    ("lf", "\n"),
    ("crlf", "\r\n"),
    ("tab", "\t"),
    ("block-comment", "/**/"),
    ("digit-glued", ""),
    ("paren-glued", ")"),
    ("semicolon", ";"),
]
MSSQL_COMBO_SEPARATORS = [
    ("space", " "),
    ("lf", "\n"),
    ("crlf", "\r\n"),
    ("tab", "\t"),
    ("block-comment", "/**/"),
    ("digit-glued", "1"),
    ("paren-glued", ")"),
    ("semicolon", ";"),
]
PG_COMBO_SEPARATORS = [("semicolon", ";"), ("semicolon-lf", ";\n")]

MSSQL_KEYWORDS = [
    "insert", "update", "delete", "merge", "truncate", "into", "exec", "execute", "create", "alter", "drop",
    "grant", "revoke", "deny", "backup", "restore", "dbcc", "kill", "shutdown", "waitfor", "output", "begin",
    "commit", "rollback", "save", "transaction", "tran", "set", "declare", "use", "bulk", "openrowset",
    "openquery", "opendatasource", "openxml", "reconfigure", "checkpoint", "go", "writetext", "updatetext",
    "next value for", "sp_who", "sp_executesql", "xp_cmdshell", "add", "disable", "enable", "receive", "send",
    "setuser", "dump", "load", "rename", "end conversation", "move conversation", "get conversation",
    "with log", "with nowait, log",
]
PG_STATEMENT_KEYWORDS = [
    "insert", "update", "delete", "merge", "truncate", "copy", "into", "commit", "rollback", "begin", "abort",
    "savepoint", "prepare", "reset", "discard", "call", "do", "lock", "vacuum", "grant", "revoke", "create",
    "alter", "drop", "comment", "refresh", "reindex", "cluster", "read_only", "session_authorization",
    "for share", "for key share",
]
PG_CALLABLE_STATEMENT_KEYWORDS = [
    "insert", "update", "delete", "merge", "truncate", "copy", "commit", "rollback", "begin", "abort",
    "savepoint", "prepare", "reset", "discard", "call", "lock", "vacuum", "revoke", "alter", "drop", "comment",
    "refresh", "reindex", "cluster", "read_only", "session_authorization",
]
PG_RESERVED_STATEMENT_KEYWORDS = [k for k in PG_STATEMENT_KEYWORDS if k not in PG_CALLABLE_STATEMENT_KEYWORDS]
PG_FUNCTION_KEYWORDS = [
    "set_config", "nextval", "setval", "dblink", "dblink_exec", "lo_import", "lo_export", "lo_unlink",
    "pg_terminate_backend", "pg_cancel_backend", "pg_reload_conf", "pg_advisory_lock",
    "pg_advisory_xact_lock", "pg_notify", "pg_sleep", "pg_sleep_for",
    "query_to_xml", "query_to_xml_and_xmlschema", "cursor_to_xml", "ts_stat", "crosstab", "crosstab4", "http",
    "http_get", "brin_summarize_new_values", "brin_desummarize_range", "gin_clean_pending_list", "set_foo",
    "drop_chunks", "compress_chunk", "decompress_chunk", "add_retention_policy", "add_compression_policy",
    "remove_retention_policy", "remove_compression_policy", "add_job", "alter_job", "delete_job", "run_job",
    "move_chunk", "reorder_chunk", "create_hypertable", "attach_partition", "detach_partition",
]
PG_KEYWORDS = PG_STATEMENT_KEYWORDS + PG_FUNCTION_KEYWORDS
PG_PATHS = ["parser", "regex"]

PG_UNSAFE_PG_FUNCTIONS = [
    "pg_try_advisory_lock", "pg_advisory_lock", "pg_stat_reset", "pg_logical_slot_get_changes",
    "pg_rotate_logfile", "pg_switch_wal", "pg_background_launch", "pg_terminate_backend", "pg_cancel_backend",
    "pg_reload_conf", "pg_sleep", "pg_notify", "pg_file_write", "pg_prewarm", "pg_create_restore_point",
    "pg_replication_slot_advance", "pg_drop_replication_slot", "pg_promote", "pg_ls_dir",
    "pg_stat_get_activity", "pg_read_file", "pg_foo",
]
PG_UNSAFE_OTHER_FUNCTIONS = [
    "query_to_xml", "ts_stat", "crosstab", "brin_summarize_new_values", "gin_clean_pending_list", "set_config",
    "nextval", "setval", "dblink", "lo_import", "drop_chunks", "compress_chunk", "add_retention_policy",
    "add_job", "run_job",
]

CONTROL_CHARS = ["\x00", "\x01", "\x08", "\x0b", "\x0c", "\x0e", "\x1f", "\x7f", "\x85", "\u2028", "\u2029"]
CONTROL_CHAR_CONTEXTS = [
    ("trailing", "SELECT 1{c}"),
    ("leading", "{c}SELECT 1"),
    ("between-tokens", "SELECT{c}1"),
    ("in-string", "SELECT '{c}'"),
    ("in-line-comment", "SELECT 1 -- {c}\n"),
    ("in-block-comment", "SELECT 1 /* {c} */"),
    ("before-write", "SELECT 1{c}DELETE FROM t"),
]
LONE_CR_CASES = [
    ("cr-before-keyword", "SELECT 1\rDELETE FROM t"),
    ("cr-in-line-comment", "SELECT 1 -- comment\rDELETE FROM t"),
    ("cr-trailing", "SELECT 1\r"),
    ("cr-leading", "\rSELECT 1"),
    ("lf-then-cr", "SELECT 1\n\r"),
    ("cr-in-string", "SELECT '\r'"),
    ("cr-cr-lf", "SELECT 1\r\r\n"),
]

MSSQL_ALLOW = [
    ("plain-select", "SELECT 1"),
    ("lowercase", "select 1"),
    ("select-from", "SELECT TOP 10 id, name FROM dbo.T WHERE id > 5 ORDER BY id"),
    ("trailing-semicolon", "SELECT 1;"),
    ("two-selects", "SELECT 1; SELECT 2"),
    ("cte", "WITH c AS (SELECT 1 AS a) SELECT a FROM c"),
    ("cte-chain", "WITH a AS (SELECT 1 x), b AS (SELECT x FROM a) SELECT * FROM b"),
    ("nolock", "SELECT * FROM dbo.T WITH (NOLOCK)"),
    ("offset-fetch", "SELECT * FROM dbo.T ORDER BY id OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY"),
    ("for-json", "SELECT id, name FROM dbo.T FOR JSON PATH"),
    ("union", "SELECT a FROM dbo.A UNION ALL SELECT a FROM dbo.B UNION SELECT 1"),
    ("window", "SELECT id, ROW_NUMBER() OVER (PARTITION BY g ORDER BY id) AS rn, SUM(v) OVER (ORDER BY id) FROM dbo.T"),
    ("keywords-in-strings", "SELECT 'DELETE FROM t; DROP TABLE x' AS s, N'INSERT INTO t EXEC sp_who' AS u"),
    ("string-doubled-quote", "SELECT 'it''s; DELETE FROM t'"),
    ("line-comment", "SELECT 1 -- DROP TABLE t; DELETE FROM t\n"),
    ("line-comment-crlf", "SELECT 1 -- DROP TABLE t\r\n"),
    ("block-comment-nested", "SELECT /* a /* DROP TABLE t */ DELETE */ 1"),
    ("block-comment-with-dashes", "SELECT /* -- */ 1"),
    ("bracket-identifiers", "SELECT [delete], [insert into], [a]]b] FROM dbo.[update]"),
    ("quoted-identifiers", 'SELECT "drop", "exec" FROM dbo."set"'),
    ("bracket-identifiers-new-keywords", "SELECT [add], [send], [load], [enable] FROM dbo.T"),
    ("identifier-containing-keyword", "SELECT updated_at, inserted_by, deleted, created_on, set_by, go_live, output_col FROM dbo.T"),
    ("variable-named-like-keyword", "DECLARE @set int = 1; SELECT @set"),
    ("temp-table-read", "SELECT * FROM #tmp"),
    ("temp-table-named-like-keyword", "SELECT * FROM #insert"),
    ("declare-scalar", "DECLARE @a int = 1; SELECT @a"),
    ("declare-multi", "DECLARE @a int = 1, @b int = 2; SELECT @a + @b"),
    ("declare-table", "DECLARE @t TABLE (id int); INSERT @t VALUES (1); SELECT * FROM @t"),
    ("insert-into-table-variable-select", "DECLARE @t TABLE (id int); INSERT INTO @t (id) SELECT 1; SELECT * FROM @t"),
    ("set-variable", "DECLARE @a int; SET @a = 1; SET @a += 2; SELECT @a"),
    ("select-assign", "DECLARE @a int; SELECT @a = COUNT(*) FROM dbo.T; SELECT @a"),
    ("crlf", "SELECT 1\r\nFROM dbo.T\r\nWHERE a = 1\r\n"),
    ("tabs", "SELECT\t1\tFROM\tdbo.T"),
    ("unicode-identifiers", "SELECT 한글컬럼 FROM dbo.T WHERE 이름 = N'가나다'"),
    ("global-variables", "SELECT @@ROWCOUNT, @@VERSION"),
    ("hex-and-numbers", "SELECT 0x1F, 1.5E3, 12"),
    ("nolock-hint-only", "SELECT * FROM t WITH (NOLOCK)"),
    ("log-function", "SELECT LOG(10)"),
    ("log-alias", "SELECT 1 AS log"),
    ("log-column-with-nolock", "SELECT log FROM dbo.T WITH (NOLOCK)"),
    ("coordinator-corpus", MSSQL_CORPUS_QUERY),
]

MSSQL_ASK = [
    ("select-into", "SELECT * INTO dbo.T2 FROM dbo.T"),
    ("select-into-temp", "SELECT 1 AS a INTO #t"),
    ("exec", "EXEC sp_who"),
    ("execute", "EXECUTE sp_who2"),
    ("exec-string", "EXEC('DELETE FROM dbo.T')"),
    ("exec-string-space", "EXEC (N'select 1')"),
    ("exec-after-select", "SELECT 1; EXEC sp_who"),
    ("sp-executesql", "EXEC sp_executesql N'select 1'"),
    ("sp-executesql-bare", "SELECT 1 AS sp_executesql"),
    ("xp-cmdshell", "EXEC master..xp_cmdshell 'dir'"),
    ("openrowset", "SELECT * FROM OPENROWSET('SQLNCLI', 'x', 'select 1')"),
    ("openquery", "SELECT * FROM OPENQUERY(lnk, 'select 1')"),
    ("opendatasource", "SELECT * FROM OPENDATASOURCE('SQLNCLI', 'x').db.dbo.T"),
    ("next-value-for", "SELECT NEXT VALUE FOR dbo.Seq"),
    ("next-value-for-block-comments", "SELECT NEXT/**/VALUE/**/FOR dbo.Seq"),
    ("next-value-for-line-comment", "SELECT NEXT -- c\n VALUE FOR dbo.Seq"),
    ("next-value-for-whitespace", "SELECT NEXT\r\nVALUE\tFOR dbo.Seq"),
    ("waitfor", "WAITFOR DELAY '00:00:05'"),
    ("go", "GO"),
    ("go-between-selects", "SELECT 1\nGO\nSELECT 2"),
    ("use", "USE master"),
    ("set-nocount", "SET NOCOUNT ON"),
    ("set-isolation", "SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED; SELECT 1"),
    ("begin-tran", "BEGIN TRAN"),
    ("begin-transaction", "BEGIN TRANSACTION; SELECT 1"),
    ("commit", "COMMIT"),
    ("rollback", "ROLLBACK"),
    ("disable-trigger", "DISABLE TRIGGER ALL ON dbo.T"),
    ("enable-trigger", "ENABLE TRIGGER trg ON dbo.T"),
    ("receive", "RECEIVE TOP(1) * FROM q"),
    ("send-on-conversation", "SEND ON CONVERSATION @h MESSAGE TYPE mt"),
    ("end-conversation", "END CONVERSATION @h"),
    ("move-conversation", "MOVE CONVERSATION @h TO @g"),
    ("get-conversation-group", "GET CONVERSATION GROUP @g FROM q"),
    ("setuser", "SETUSER 'x'"),
    ("add-signature", "ADD SIGNATURE TO dbo.p BY CERTIFICATE c"),
    ("bulk-insert", "BULK INSERT dbo.T FROM 'f'"),
    ("cte-update", "WITH c AS (SELECT 1 a) UPDATE dbo.T SET a = 1"),
    ("cte-delete", "WITH c AS (SELECT 1 a) DELETE FROM dbo.T"),
    ("cte-merge", "WITH c AS (SELECT 1 a) MERGE dbo.T AS t USING c ON t.a = c.a WHEN MATCHED THEN DELETE;"),
    ("cte-insert", "WITH c AS (SELECT 1 a) INSERT dbo.T SELECT a FROM c"),
    ("insert-table-variable-exec", "DECLARE @t TABLE (a int); INSERT @t EXEC sp_who"),
    ("insert-table-variable-output", "DECLARE @t TABLE (a int); INSERT @t OUTPUT inserted.a VALUES (1)"),
    ("insert-table-variable-default-values", "DECLARE @t TABLE (a int); INSERT @t DEFAULT VALUES"),
    ("insert-real-table-after-declare", "DECLARE @x int; INSERT dbo.T VALUES (1)"),
    ("declare-cursor", "DECLARE c CURSOR FOR SELECT 1"),
    ("bare-procedure-name", "sp_who"),
    ("create-temp-table", "CREATE TABLE #t (a int)"),
    ("declare-then-real-insert-no-semicolon", "DECLARE @x int INSERT dbo.T VALUES (1)"),
    ("declare-assign-then-real-insert-no-semicolon", "DECLARE @x int = 1 INSERT dbo.T VALUES (1)"),
    ("set-variable-then-real-update-no-semicolon", "DECLARE @x int; SET @x = 1 UPDATE dbo.T SET a = 1"),
    ("insert-table-variable-then-real-delete", "DECLARE @t TABLE (a int); INSERT @t VALUES (1) DELETE FROM dbo.T"),
    ("digit-glued-insert", "SELECT 1INSERT dbo.T VALUES (1)"),
    ("digit-glued-delete-after-variable", "DECLARE @a int = 1DELETE FROM dbo.T"),
    ("digit-glued-after-set-variable", "DECLARE @a int; SET @a = 1UPDATE dbo.T SET a = 1"),
    ("digit-glued-after-insert-variable", "DECLARE @t TABLE (a int); INSERT @t VALUES (1)INSERT dbo.T VALUES (1)"),
    ("select-assign-then-write", "DECLARE @a int; SELECT @a = 1 UPDATE dbo.T SET a = @a"),
    ("full-width-delete", "SELECT 1 ＤＥＬＥＴＥ FROM dbo.T"),
    ("full-width-exec", "SELECT 1; ＥＸＥＣ sp_who"),
    ("full-width-select-start", "ＳＥＬＥＣＴ 1"),
    ("full-width-after-declare", "DECLARE @a int ＩＮＳＥＲＴ dbo.T VALUES (1)"),
    ("unterminated-string", "SELECT 'abc"),
    ("unterminated-string-with-write", "SELECT 'abc; DELETE FROM dbo.T"),
    ("unterminated-bracket", "SELECT [abc"),
    ("unterminated-quoted-identifier", 'SELECT "abc'),
    ("unterminated-block-comment", "SELECT 1 /* abc"),
    ("unterminated-nested-block-comment", "SELECT 1 /* a /* b */"),
    ("empty", ""),
    ("whitespace-only", "  \t\n  "),
    ("line-comment-only", "-- only a comment"),
    ("block-comment-only", "/* only a comment */"),
    ("semicolon-only", ";"),
    ("semicolons-only", ";;"),
    ("non-select-statement", "PRINT 'x'"),
    ("select-after-print", "SELECT 1; PRINT 'x'"),
    ("raiserror-with-log-after-select", "SELECT 1 RAISERROR('x', 10, 1) WITH LOG"),
    ("raiserror-with-log-alone", "RAISERROR('x',10,1) WITH LOG"),
    ("raiserror-with-nowait-log", "SELECT 1 RAISERROR('x', 10, 1) WITH NOWAIT, LOG"),
    ("raiserror-with-log-comment-between", "SELECT 1 RAISERROR('x', 10, 1) WITH/**/LOG"),
    ("raiserror-with-log-lowercase-multiline", "SELECT 1 raiserror('x', 10, 1) with\n  log"),
    ("alter", "ALTER TABLE dbo.T ADD c int"),
    ("grant", "GRANT SELECT ON dbo.T TO u"),
    ("kill", "KILL 55"),
    ("dbcc", "DBCC CHECKDB"),
    ("backup", "BACKUP DATABASE d TO DISK = 'x'"),
    ("openxml", "SELECT * FROM OPENXML(@h, '/r')"),
    ("update-after-line-comment", "SELECT 1 -- c\nUPDATE dbo.T SET a = 1"),
    ("update-after-block-comment", "SELECT 1 /* c */ UPDATE dbo.T SET a = 1"),
]

PG_ALLOW = [
    ("plain-select", "SELECT 1"),
    ("lowercase", "select * from t"),
    ("trailing-semicolon", "SELECT 1;"),
    ("cte", "WITH c AS (SELECT 1 a) SELECT * FROM c"),
    ("show", "SHOW server_version"),
    ("show-all", "SHOW ALL"),
    ("table", "TABLE foo"),
    ("values", "VALUES (1), (2)"),
    ("explain", "EXPLAIN SELECT * FROM t"),
    ("explain-format", "EXPLAIN (FORMAT JSON) SELECT * FROM t"),
    ("explain-costs", "EXPLAIN (COSTS OFF, VERBOSE) SELECT 1"),
    ("e-string-escaped-quote", "SELECT E'it\\'s DELETE'"),
    ("e-string-escaped-backslash", "SELECT E'a\\\\'"),
    ("e-string-lowercase", "select e'x\\n'"),
    ("e-string-concatenated", "SELECT 'a' || E'\\n' || 'b'"),
    ("dollar-quote-empty-tag", "SELECT $$ DELETE FROM t; DROP TABLE x $$"),
    ("dollar-quote-tag", "SELECT $fn$ INSERT ; ' \" $fn$"),
    ("dollar-quote-nested-tags", "SELECT $a$ $b$ UPDATE $b$ $a$"),
    ("quoted-identifiers", 'SELECT "Name", "my col" FROM "Schema"."Table"'),
    ("quoted-identifier-escaped-quote", 'SELECT "a""b" FROM t'),
    ("allowlisted-function", "SELECT pg_size_pretty(pg_database_size(current_database()))"),
    ("allowlisted-function-qualified", "SELECT pg_catalog.pg_get_viewdef('v'::regclass)"),
    ("allowlisted-function-spaced", "SELECT pg_backend_pid ()"),
    ("catalog-table", "SELECT * FROM pg_stat_activity"),
    ("catalog-join", "SELECT * FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"),
    ("public-table", "SELECT * FROM public.t"),
    ("public-function", "SELECT public.myfn(1)"),
    ("information-schema", "SELECT * FROM information_schema.tables"),
    ("line-comment", "SELECT 1 -- DELETE\n"),
    ("block-comment-nested", "SELECT /* a /* DROP */ b */ 1"),
    ("keywords-in-strings", "SELECT 'DELETE; DROP', 'it''s'"),
    ("in-list", "SELECT a FROM t WHERE b IN (1, 2) ORDER BY a LIMIT 10 OFFSET 5"),
    ("filter-aggregate", "SELECT count(*) FILTER (WHERE a > 1) FROM t"),
    ("generate-series", "SELECT * FROM generate_series(1, 3)"),
    ("cast", "SELECT now()::date, date_trunc('day', now()), to_char(now(), 'YYYY')"),
    ("current-setting", "SELECT current_setting('server_version')"),
    ("array-agg", "SELECT array_agg(a ORDER BY b) FROM t"),
    ("join-using", "SELECT * FROM t1 JOIN t2 USING (id)"),
    ("identifier-containing-keyword", "SELECT updated_at, inserted_by, reset_count, created_on FROM t"),
    ("unicode-identifiers", "SELECT 이름 FROM t WHERE 이름 = '가나다'"),
    ("crlf", "SELECT 1\r\nFROM t\r\n"),
    ("decimals", "SELECT 1.5 + 2.5"),
    ("two-reads", "SELECT 1; SELECT 2"),
    ("e-string-simple", "SELECT E'it\\'s'"),
    ("values-and-table-statements", "VALUES (1); TABLE t"),
    ("show-then-select", "SHOW server_version; SELECT 1"),
    ("read-only-prelude", "SET LOCAL transaction_read_only = on;\nSELECT 1"),
    ("read-only-prelude-inline", "SET LOCAL transaction_read_only = on; SELECT 1"),
    ("read-only-prelude-to", "SET LOCAL transaction_read_only TO true; SELECT 1"),
    ("timeout-prelude", "SET LOCAL statement_timeout = 5000; SELECT 1"),
    ("timeout-prelude-quoted", "SET LOCAL statement_timeout TO '5s'; SELECT 1"),
    ("timeout-and-read-only-prelude", "SET LOCAL lock_timeout = 100; SET LOCAL transaction_read_only = on; SELECT 1"),
]

PG_ASK = [
    ("quoted-pg-terminate-backend", 'SELECT "pg_terminate_backend"(1)'),
    ("quoted-set-config", "SELECT \"set_config\"('x', 'y', false)"),
    ("quoted-dblink-exec", "SELECT \"dblink_exec\"('c', 'DELETE FROM t')"),
    ("quoted-lo-import", "SELECT \"lo_import\"('/etc/passwd')"),
    ("quoted-schema-pg-sleep", 'SELECT pg_catalog."pg_sleep"(1)'),
    ("quoted-unknown-pg-function", 'SELECT "pg_foo"(1)'),
    ("quoted-extension-schema", 'SELECT "azure_storage"."blob_put"(1)'),
    ("plain-string-backslash", "SELECT 'a\\b'"),
    ("plain-string-trailing-backslash", "SELECT 'a\\'"),
    ("plain-string-double-backslash", "SELECT '\\\\'"),
    ("stray-dollar", "SELECT $"),
    ("dollar-digit-tag", "SELECT $1$"),
    ("for-share", "SELECT * FROM t FOR SHARE"),
    ("for-key-share", "SELECT * FROM t FOR KEY SHARE"),
    ("for-update", "SELECT * FROM t FOR UPDATE"),
    ("for-no-key-update", "SELECT * FROM t FOR NO KEY UPDATE"),
    ("for-share-comment", "SELECT * FROM t FOR/**/SHARE"),
    ("for-share-spaces", "SELECT * FROM t FOR   SHARE"),
    ("explain-analyze", "EXPLAIN ANALYZE SELECT 1"),
    ("explain-analyse", "EXPLAIN ANALYSE SELECT 1"),
    ("explain-paren-analyze", "EXPLAIN (ANALYZE) SELECT 1"),
    ("explain-paren-analyse", "EXPLAIN (ANALYSE) SELECT 1"),
    ("explain-format-analyze", "EXPLAIN (FORMAT JSON, ANALYZE) SELECT 1"),
    ("explain-tight-paren", "EXPLAIN(ANALYZE)SELECT 1"),
    ("explain-analyze-verbose", "EXPLAIN ANALYZE VERBOSE SELECT 1"),
    ("explain-comment-analyze", "EXPLAIN /* c */ ANALYZE SELECT 1"),
    ("explain-newline-analyze", "EXPLAIN\nANALYZE SELECT 1"),
    ("explain-delete", "EXPLAIN DELETE FROM t"),
    ("set-local-read-only-off", "SET LOCAL transaction_read_only = off"),
    ("set-local-read-only-off-then-select", "SET LOCAL transaction_read_only = off; SELECT 1"),
    ("set-local-read-only-quoted", "SET LOCAL transaction_read_only = 'off'"),
    ("set-read-only-session", "SET transaction_read_only = on; SELECT 1"),
    ("set-work-mem", "SET work_mem = '1MB'; SELECT 1"),
    ("set-local-work-mem", "SET LOCAL work_mem = '1MB'; SELECT 1"),
    ("set-local-role", "SET LOCAL role = 'x'; SELECT 1"),
    ("set-session-authorization", "SET SESSION AUTHORIZATION x; SELECT 1"),
    ("read-only-on-then-off", "SET LOCAL transaction_read_only = on; SET LOCAL transaction_read_only = off; DELETE FROM t"),
    ("timeout-then-set", "SET LOCAL statement_timeout = 5000; SET work_mem = '1MB'; SELECT 1"),
    ("select-then-read-only-off", "SELECT 1; SET LOCAL transaction_read_only = off; DELETE FROM t"),
    ("do", "DO $$ BEGIN DELETE FROM t; END $$"),
    ("call", "CALL p()"),
    ("copy", "COPY t TO '/tmp/x'"),
    ("copy-program", "COPY t FROM PROGRAM 'id'"),
    ("listen", "LISTEN c"),
    ("notify", "NOTIFY c"),
    ("prepare", "PREPARE p AS SELECT 1"),
    ("execute", "EXECUTE p"),
    ("deallocate", "DEALLOCATE p"),
    ("lock", "LOCK TABLE t"),
    ("vacuum", "VACUUM t"),
    ("analyze-statement", "ANALYZE t"),
    ("refresh", "REFRESH MATERIALIZED VIEW mv"),
    ("begin", "BEGIN"),
    ("commit", "COMMIT"),
    ("savepoint", "SAVEPOINT s"),
    ("checkpoint", "CHECKPOINT"),
    ("insert", "INSERT INTO t VALUES (1)"),
    ("truncate", "TRUNCATE t"),
    ("select-into", "SELECT * INTO t2 FROM t"),
    ("select-into-temp", "SELECT 1 INTO TEMP t2"),
    ("cte-delete", "WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d"),
    ("cte-update", "WITH u AS (UPDATE t SET a = 1 RETURNING *) SELECT * FROM u"),
    ("cte-insert", "WITH i AS (INSERT INTO t VALUES (1) RETURNING *) SELECT * FROM i"),
    ("second-statement-insert", "SELECT 1; INSERT INTO t VALUES (1)"),
    ("second-statement-delete", "SELECT 1; DELETE FROM t"),
    ("second-statement-update-tight", "SELECT 1;UPDATE t SET a = 1"),
    ("digit-glued-insert", "SELECT 1INSERT INTO t VALUES (1)"),
    ("full-width-select-start", "ＳＥＬＥＣＴ 1"),
    ("nextval", "SELECT nextval('s')"),
    ("setval", "SELECT setval('s', 1)"),
    ("unterminated-string", "SELECT 'abc"),
    ("unterminated-string-with-write", "SELECT 'abc; DELETE FROM t"),
    ("unterminated-dollar-quote", "SELECT $$abc"),
    ("unterminated-tagged-dollar-quote", "SELECT $a$ abc $b$"),
    ("unterminated-block-comment", "SELECT 1 /* abc"),
    ("unterminated-nested-block-comment", "SELECT 1 /* a /* b */"),
    ("unterminated-quoted-identifier", 'SELECT "abc'),
    ("empty", ""),
    ("whitespace-only", "  \t\n  "),
    ("line-comment-only", "-- only a comment"),
    ("block-comment-only", "/* only a comment */"),
    ("semicolon-only", ";"),
    ("prelude-only", "SET LOCAL transaction_read_only = on;"),
    ("update-after-line-comment", "SELECT 1 -- c\nUPDATE t SET a = 1"),
    ("update-after-block-comment", "SELECT 1 /* c */ UPDATE t SET a = 1"),
    ("update-after-dollar-quote", "SELECT $$x$$; UPDATE t SET a = 1"),
    ("other-schema-table-function", "SELECT other_schema.fn(1)"),
    ("other-schema-spaced", "SELECT OTHER_SCHEMA . fn (1)"),
    ("other-schema-uppercase", "SELECT AZURE_STORAGE.blob_put(1)"),
    ("azure-storage", "SELECT azure_storage.blob_put(1)"),
    ("aws-s3", "SELECT aws_s3.query_export_to_s3('x')"),
    ("cron", "SELECT cron.schedule('* * * * *', 'x')"),
    ("net-http", "SELECT net.http_post('x')"),
    ("timescaledb-functions", "SELECT _timescaledb_functions.x(1)"),
    ("three-part-call", "SELECT mydb.pg_catalog.now()"),
    ("three-part-call-other", "SELECT a.b.c(1)"),
    ("other-schema-in-from", "SELECT * FROM other_schema.fn(1)"),
    ("unicode-escape-identifier-function", 'SELECT U&"pg\\005fsleep"(1)'),
    ("pg-catalog-pg-sleep", "SELECT pg_catalog.pg_sleep(1)"),
    ("for-update-in-subquery", "SELECT * FROM (SELECT * FROM t FOR UPDATE) x"),
    ("for-share-in-subquery", "SELECT * FROM (SELECT * FROM t FOR SHARE) x"),
    ("explain-analyze-true", "EXPLAIN (ANALYZE true) SELECT 1"),
    ("explain-analyze-false", "EXPLAIN (ANALYZE false) SELECT 1"),
    ("jdbc-fn-now", "SELECT {fn now()}"),
    ("plain-string-backslash-after-non-ascii", "SELECT '한글 한글', 'a\\b'"),
    ("plain-string-backslash-after-emoji", "SELECT '😀', 'a\\b'"),
    ("plain-string-backslash-first-of-two", "SELECT 'a\\b', '한글'"),
    ("read-only-one", "SET LOCAL transaction_read_only = 1; SELECT 1"),
    ("reserved-word-column-do", "SELECT do FROM t"),
]

INVISIBLE_CHARS = ["​", "‌", "‍", "⁠", "﻿", "­"]
JDBC_ESCAPE_ASK = [
    ("mssql-call", MSSQL_ID, "SELECT 1 {call dbo.Purge}"),
    ("mssql-fn", MSSQL_ID, "SELECT {fn now()}"),
    ("mssql-return-call", MSSQL_ID, "SELECT 1 {?= call dbo.p}"),
    ("mssql-closing-brace-only", MSSQL_ID, "SELECT 1 }"),
    ("mssql-after-line-comment", MSSQL_ID, "SELECT 1 -- x\n{call dbo.Purge}"),
    ("mssql-after-string", MSSQL_ID, "SELECT '{x}' {call dbo.Purge}"),
    ("pg-fn", PG_ID, "SELECT {fn now()}"),
    ("pg-call", PG_ID, "SELECT 1 {call purge()}"),
    ("pg-closing-brace-only", PG_ID, "SELECT 1 }"),
    ("pg-after-dollar-quote", PG_ID, "SELECT $$ {x} $$ {call purge()}"),
]
INVISIBLE_ASK = (
    [(f"mssql-split-keyword-{ord(c):#06x}", MSSQL_ID, f"SELECT 1 DEL{c}ETE dbo.T") for c in INVISIBLE_CHARS]
    + [(f"mssql-in-string-{ord(c):#06x}", MSSQL_ID, f"SELECT 'a{c}b'") for c in INVISIBLE_CHARS]
    + [(f"mssql-in-comment-{ord(c):#06x}", MSSQL_ID, f"SELECT 1 -- a{c}b\n") for c in INVISIBLE_CHARS]
    + [(f"pg-split-keyword-{ord(c):#06x}", PG_ID, f"SELECT 1 DEL{c}ETE t") for c in INVISIBLE_CHARS]
    + [(f"pg-in-string-{ord(c):#06x}", PG_ID, f"SELECT 'a{c}b'") for c in INVISIBLE_CHARS]
)
BRACE_ALLOW = [
    ("mssql-string", MSSQL_ID, "SELECT '{1,2}'"),
    ("mssql-unicode-string-json", MSSQL_ID, 'SELECT N\'{"a": {"b": 1}}\' AS j'),
    ("mssql-line-comment", MSSQL_ID, "SELECT 1 -- {call dbo.Purge}\n"),
    ("mssql-block-comment", MSSQL_ID, "SELECT /* {fn now()} */ 1"),
    ("mssql-bracket-identifier", MSSQL_ID, "SELECT [a{b}] FROM dbo.T"),
    ("mssql-quoted-identifier", MSSQL_ID, 'SELECT "a{b}" FROM dbo.T'),
    ("pg-array-string", PG_ID, "SELECT '{1,2}'::int[]"),
    ("pg-json-string", PG_ID, 'SELECT \'{"a": {"b": 1}}\'::jsonb'),
    ("pg-e-string", PG_ID, "SELECT E'{x}'"),
    ("pg-dollar-quote", PG_ID, "SELECT $$ {call purge()} $$"),
    ("pg-tagged-dollar-quote", PG_ID, "SELECT $t$ {fn now()} $t$"),
    ("pg-line-comment", PG_ID, "SELECT 1 -- {call purge()}\n"),
    ("pg-block-comment", PG_ID, "SELECT /* {fn now()} */ 1"),
    ("pg-quoted-identifier", PG_ID, 'SELECT "a{b}" FROM t'),
]

PG_ASK_REGEX_ONLY = [
    ("quoted-keyword-column", 'SELECT "comment" FROM t', "a quoted identifier is a column name, not a keyword"),
    ("quoted-keyword-with-dots", 'SELECT "a.insert" FROM t', "a quoted identifier containing a dot is still one column name"),
    ("unicode-escape-identifier", 'SELECT U&"d\\0061t\\0061"', "a decoded U& identifier is only a column name"),
    ("unicode-escape-string", "SELECT U&'d\\0061t\\0061'", "a U& string is only a string value"),
    ("unicode-escape-lowercase", "select u&'x'", "a U& string is only a string value"),
    ("unicode-escape-in-expression", "SELECT 1 FROM t WHERE x = U&'a'", "a U& string is only a string value"),
    ("positional-parameter", "SELECT $1", "a parameter reference cannot run without bound parameters and never writes"),
    ("positional-parameter-in-where", "SELECT * FROM t WHERE a = $1", "a parameter reference cannot run without bound parameters and never writes"),
    ("dollar-after-identifier", "SELECT a$$b$$", "a$$b$$ is one ordinary identifier"),
    ("dollar-in-identifier", "SELECT col$x FROM t", "a dollar sign inside an identifier is an ordinary identifier character"),
    ("full-width-delete", "SELECT 1 ＤＥＬＥＴＥ FROM t", "full-width letters form an ordinary identifier that the server never folds into DELETE"),
    ("full-width-pg-sleep", "SELECT ｐｇ＿ｓｌｅｅｐ(1)", "a full-width name is an unknown user function, not pg_sleep"),
    ("column-names-like-keywords", "SELECT update, comment, set_id, https_url FROM t", "update, comment, set_id and https_url are ordinary column names"),
    ("quoted-reserved-word-and-pg-sleep-columns", 'SELECT "do", "into", "pg_sleep" FROM t', "quoted names are columns and a quoted pg_sleep without parentheses is no call"),
    ("alias-named-like-keyword", "SELECT 1 AS insert, 2 AS delete", "an alias named like a statement keyword is only a label"),
    ("table-named-like-keyword", 'SELECT * FROM comment c JOIN "update" u ON true', "tables named like statement keywords are only relations"),
    ("read-only-prelude-quoted-on", "SET LOCAL transaction_read_only = 'on'; SELECT 1", "the quoted value on really turns read-only on"),
]

PG_PARSER_ASK = [
    ("syntax-error-from-from", "SELECT FROM FROM"),
    ("syntax-error-dangling-operator", "SELECT 1 +"),
    ("syntax-error-missing-relation", "SELECT * FROM"),
    ("syntax-error-misspelled-select", "SELCT 1"),
    ("syntax-error-before-write", "SELECT 1 FROM; DELETE FROM t"),
]

MSSQL_WRITES = [
    ("insert", "INSERT dbo.T VALUES (1)"),
    ("update", "UPDATE dbo.T SET a = 1"),
    ("delete", "DELETE FROM dbo.T"),
    ("merge", "MERGE dbo.T AS t USING dbo.S AS s ON t.id = s.id WHEN MATCHED THEN DELETE"),
    ("truncate", "TRUNCATE TABLE dbo.T"),
    ("exec", "EXEC sp_who"),
    ("drop", "DROP TABLE dbo.T"),
    ("select-into", "SELECT 1 a INTO dbo.T2"),
    ("create", "CREATE TABLE dbo.T2 (a int)"),
    ("waitfor", "WAITFOR DELAY '00:00:01'"),
    ("set", "SET NOCOUNT ON"),
    ("use", "USE master"),
    ("bulk", "BULK INSERT dbo.T FROM 'f'"),
    ("xp", "xp_cmdshell 'dir'"),
    ("send", "SEND ON CONVERSATION @h MESSAGE TYPE mt"),
]
PG_WRITES = [
    ("insert", "INSERT INTO t VALUES (1)"),
    ("update", "UPDATE t SET a = 1"),
    ("delete", "DELETE FROM t"),
    ("truncate", "TRUNCATE t"),
    ("drop", "DROP TABLE t"),
    ("create", "CREATE TABLE t2 (a int)"),
    ("copy", "COPY t FROM '/x'"),
    ("do", "DO $$ BEGIN END $$"),
    ("call", "CALL p()"),
    ("pg-sleep", "SELECT pg_sleep(1)"),
    ("set-config", "SELECT set_config('x', 'y', false)"),
    ("nextval", "SELECT nextval('s')"),
    ("read-only-off", "SET LOCAL transaction_read_only = off"),
    ("vacuum", "VACUUM t"),
    ("select-into", "SELECT * INTO t2 FROM t"),
    ("lock", "LOCK TABLE t"),
    ("explain-analyze", "EXPLAIN ANALYZE SELECT 1"),
    ("for-update", "SELECT * FROM t FOR UPDATE"),
]


def params(table):
    return [pytest.param(sql, id=name) for name, sql in table]


def make_tool_input(connection_id, sql):
    return {"projectPath": str(PROJECT), "connectionId": connection_id, "queryText": sql}


def make_payload(connection_id, sql):
    return {"tool_input": make_tool_input(connection_id, sql)}


def decide(connection_id, sql):
    return hook.decide(make_tool_input(connection_id, sql))


def decision_of(output):
    return output["hookSpecificOutput"]["permissionDecision"]


def reason_of(output):
    return output["hookSpecificOutput"]["permissionDecisionReason"]


def script_env(host="claude", extra=None):
    env = {
        "PATH": os.defpath,
        "HOME": str(STATE_HOME),
        "XDG_STATE_HOME": str(STATE_HOME / "xdg"),
    }
    if host == "codex":
        env["PLUGIN_ROOT"] = str(REPO_ROOT)
    for key, value in (extra or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def run_script(stdin, *args, python=None, extra_env=None):
    """Run the guard once. `args` may hold CODEX_PERMISSION or CODEX_PRE_TOOL to emulate the Codex host events."""
    host = "codex" if any(a in (CODEX_PERMISSION, CODEX_PRE_TOOL) for a in args) else "claude"
    if isinstance(stdin, (str, bytes)):
        try:
            event = json.loads(stdin)
        except ValueError:
            event = None
    else:
        event = stdin
    if isinstance(event, dict) and "tool_input" in event:
        event = {"tool_name": TOOL_NAME, "hook_event_name": "PreToolUse", **event}
        if CODEX_PERMISSION in args:
            event["hook_event_name"] = "PermissionRequest"
        stdin = json.dumps(event, ensure_ascii=False)
    elif not isinstance(stdin, (str, bytes)):
        stdin = json.dumps(stdin, ensure_ascii=False)
    data = stdin if isinstance(stdin, bytes) else stdin.encode("utf-8")
    completed = subprocess.run(
        [python or sys.executable, str(HOOK_PATH)],
        input=data,
        capture_output=True,
        env=script_env(host, extra_env),
        timeout=60,
    )
    return completed.returncode, completed.stdout.decode("utf-8"), completed.stderr.decode("utf-8")


def apply_path(monkeypatch, path):
    if path == "regex":
        monkeypatch.setattr(hook, "pglast_parser", None)
    elif path == "parser":
        assert hook.pglast_parser is not None, "install the dev extra so that pglast is available"


@pytest.fixture(params=PG_PATHS)
def pg_path(request, monkeypatch):
    apply_path(monkeypatch, request.param)
    return request.param


@pytest.fixture
def pg_regex(monkeypatch):
    apply_path(monkeypatch, "regex")


@pytest.fixture
def pg_parser(monkeypatch):
    apply_path(monkeypatch, "parser")


def next_statement_cases(keywords):
    cases = []
    for keyword in keywords:
        for sep_name, sep in KEYWORD_SEPARATORS:
            cases.append(pytest.param(f"SELECT 1;{sep}{keyword}", id=f"{keyword}-{sep_name}"))
    return cases


def keyword_cases(keywords):
    cases = []
    for keyword in keywords:
        for sep_name, sep in KEYWORD_SEPARATORS:
            cases.append(pytest.param(f"SELECT 1{sep}{keyword}", id=f"{keyword}-{sep_name}"))
    return cases


def control_char_cases():
    cases = []
    for context_name, template in CONTROL_CHAR_CONTEXTS:
        for char in CONTROL_CHARS:
            cases.append(pytest.param(template.format(c=char), id=f"{context_name}-{ord(char):#06x}"))
    for name, sql in LONE_CR_CASES:
        cases.append(pytest.param(sql, id=name))
    return cases


def combo_cases(bases, separators, writes):
    cases = []
    for base_name, base in bases:
        for sep_name, sep in separators:
            for write_name, write in writes:
                cases.append(pytest.param(base + sep + write, id=f"{base_name}-{sep_name}-{write_name}"))
    return cases


def pg_function_cases(functions):
    cases = []
    for name in functions:
        for form_name, template in [
            ("plain", "SELECT {f}(1)"),
            ("spaced", "SELECT {f} (1)"),
            ("comment", "SELECT {f}/**/(1)"),
            ("catalog-qualified", "SELECT pg_catalog.{f}(1)"),
            ("quoted", 'SELECT "{f}"(1)'),
            ("digit-glued", "SELECT 1{f}(1)"),
            ("in-from", "SELECT * FROM {f}(1)"),
        ]:
            cases.append(pytest.param(template.format(f=name), id=f"{name}-{form_name}"))
    return cases


def regex_alternatives(compiled):
    body = compiled.pattern[len(hook.KEYWORD_START) + 1:-3]
    return body.split("|")


def path_cases(connection_id, sql, is_read, label, paths=None):
    if connection_id != PG_ID:
        return [pytest.param(connection_id, sql, is_read, None, id=label)]
    return [pytest.param(connection_id, sql, is_read, path, id=f"{label}-{path}") for path in (paths or PG_PATHS)]


def build_core_cases():
    cases = []
    for name, sql in MSSQL_ALLOW:
        cases += path_cases(MSSQL_ID, sql, True, f"mssql-allow-{name}")
    for name, sql in MSSQL_ASK:
        cases += path_cases(MSSQL_ID, sql, False, f"mssql-ask-{name}")
    for name, sql in PG_ALLOW:
        cases += path_cases(PG_ID, sql, True, f"pg-allow-{name}")
    for name, sql in PG_ASK:
        cases += path_cases(PG_ID, sql, False, f"pg-ask-{name}")
    for name, sql, _ in PG_ASK_REGEX_ONLY:
        cases += path_cases(PG_ID, sql, True, f"pg-parser-allow-{name}", ["parser"])
        cases += path_cases(PG_ID, sql, False, f"pg-regex-ask-{name}", ["regex"])
    for name, sql in PG_PARSER_ASK:
        cases += path_cases(PG_ID, sql, False, f"pg-parser-ask-{name}", ["parser"])
    for p in keyword_cases(MSSQL_KEYWORDS):
        cases += path_cases(MSSQL_ID, p.values[0], False, f"mssql-keyword-{p.id}")
    for p in next_statement_cases(PG_KEYWORDS):
        cases += path_cases(PG_ID, p.values[0], False, f"pg-next-statement-{p.id}")
    for p in control_char_cases():
        cases += path_cases(MSSQL_ID, p.values[0], False, f"mssql-control-{p.id}")
        cases += path_cases(PG_ID, p.values[0], False, f"pg-control-{p.id}")
    for name, conn, sql in JDBC_ESCAPE_ASK:
        cases += path_cases(conn, sql, False, f"jdbc-{name}")
    for name, conn, sql in INVISIBLE_ASK:
        cases += path_cases(conn, sql, False, f"invisible-{name}")
    for name, conn, sql in BRACE_ALLOW:
        cases += path_cases(conn, sql, True, f"brace-allow-{name}")
    return cases


CORE_CASES = build_core_cases()


class TestMssqlAllow:
    @pytest.mark.parametrize("sql", params(MSSQL_ALLOW))
    def test_mssql_read_is_allowed(self, sql):
        """MSSQL 조회 쿼리는 승인 없이 allow하고 쿼리를 바꾸지 않는다."""
        # given
        connection_id = MSSQL_ID
        # when
        output = decide(connection_id, sql)
        # then
        assert decision_of(output) == "allow"
        assert reason_of(output) == hook.MSSQL_ALLOW_REASON
        assert "updatedInput" not in output["hookSpecificOutput"]

    def test_corpus_query_keeps_every_feature_and_is_allowed(self):
        """합성 코퍼스 쿼리는 여러 문장, 다섯 개 CTE, 힌트와 집계를 모두 담은 하나의 쿼리로 allow된다."""
        # given
        sql = MSSQL_CORPUS_QUERY
        # when
        output = decide(MSSQL_ID, sql)
        # then
        assert sql.count("DECLARE") == 2
        assert sql.count(" AS (") == 5
        for feature in ("PRIMARY KEY", "INSERT @pick VALUES", "WITH (NOLOCK)", "COLLATE DATABASE_DEFAULT", "[YEAR]",
                        "ROW_NUMBER() OVER", "UNION", "WITHIN GROUP (ORDER BY", "BINARY_CHECKSUM", "FORMAT(", "CAST(", "CONCAT("):
            assert feature in sql
        assert decision_of(output) == "allow"


class TestMssqlAsk:
    @pytest.mark.parametrize("sql", params(MSSQL_ASK))
    def test_mssql_non_read_asks(self, sql):
        """MSSQL 쓰기, 실행, 판별 불가 쿼리는 ask한다."""
        # given
        connection_id = MSSQL_ID
        # when
        output = decide(connection_id, sql)
        # then
        assert decision_of(output) == "ask"
        assert reason_of(output) == hook.ASK_REASON

    @pytest.mark.parametrize("sql", keyword_cases(MSSQL_KEYWORDS))
    def test_mssql_risky_keyword_after_select_asks(self, sql):
        """MSSQL 위험 키워드는 어떤 구분자로 붙어 있어도 ask한다."""
        # given
        connection_id = MSSQL_ID
        # when
        output = decide(connection_id, sql)
        # then
        assert decision_of(output) == "ask"

    @pytest.mark.parametrize("sql", control_char_cases())
    def test_mssql_uncertain_characters_ask(self, sql):
        """MSSQL 제어 문자와 단독 CR은 어느 위치에 있어도 ask한다."""
        # given
        connection_id = MSSQL_ID
        # when
        output = decide(connection_id, sql)
        # then
        assert decision_of(output) == "ask"

    def test_mssql_keyword_samples_cover_every_regex_alternative(self):
        """MSSQL 키워드 표본은 정규식의 모든 대안을 빠짐없이 덮는다."""
        # given
        alternatives = regex_alternatives(hook.MSSQL_RISKY)
        # when
        uncovered = [
            alt for alt in alternatives
            if not any(re.fullmatch(alt, kw, re.I) for kw in MSSQL_KEYWORDS)
        ]
        unused = [
            kw for kw in MSSQL_KEYWORDS
            if not any(re.fullmatch(alt, kw, re.I) for alt in alternatives)
        ]
        # then
        assert uncovered == []
        assert unused == []

    @pytest.mark.parametrize(
        "sql",
        combo_cases(MSSQL_ALLOW, MSSQL_COMBO_SEPARATORS, MSSQL_WRITES),
    )
    def test_mssql_read_followed_by_write_asks(self, sql):
        """MSSQL 조회 뒤에 어떤 구분자로든 쓰기가 이어지면 ask한다."""
        # given
        connection_id = MSSQL_ID
        # when
        output = decide(connection_id, sql)
        # then
        assert decision_of(output) == "ask"


@pytest.mark.usefixtures("pg_path")
class TestPostgresAllow:
    @pytest.mark.parametrize(
        "sql",
        params([c for c in PG_ALLOW if "transaction_read_only" not in c[1]]),
    )
    def test_postgres_read_gets_read_only_prelude(self, sql):
        """PostgreSQL 조회는 allow하고 읽기 전용 접두를 붙인 updatedInput을 돌려준다."""
        # given
        payload = make_payload(PG_ID, sql)
        payload["tool_input"]["extra"] = "kept"
        # when
        output = hook.decide(payload["tool_input"])
        # then
        assert decision_of(output) == "allow"
        assert reason_of(output) == hook.PG_ALLOW_REASON
        updated = output["hookSpecificOutput"]["updatedInput"]
        assert updated["queryText"] == hook.READ_ONLY_PRELUDE + sql
        assert updated["connectionId"] == PG_ID
        assert updated["extra"] == "kept"

    @pytest.mark.parametrize(
        "sql",
        params([c for c in PG_ALLOW if "transaction_read_only" in c[1]]),
    )
    def test_postgres_read_with_user_read_only_prelude_keeps_query(self, sql):
        """사용자가 읽기 전용 접두를 이미 붙인 조회는 쿼리를 바꾸지 않고 allow한다."""
        # given
        payload = make_payload(PG_ID, sql)
        # when
        output = hook.decide(payload["tool_input"])
        # then
        assert decision_of(output) == "allow"
        assert "updatedInput" not in output["hookSpecificOutput"]

    @pytest.mark.parametrize(
        "sql",
        params([c for c in PG_ALLOW if "statement_timeout" in c[1] or "lock_timeout" in c[1]]),
    )
    def test_postgres_timeout_prelude_gets_read_only_prefix(self, sql):
        """타임아웃 접두만 있는 조회는 읽기 전용 접두를 앞에 붙여 allow한다."""
        # given
        payload = make_payload(PG_ID, sql)
        # when
        output = hook.decide(payload["tool_input"])
        # then
        assert decision_of(output) == "allow"
        updated = output["hookSpecificOutput"].get("updatedInput")
        if "transaction_read_only" in sql:
            assert updated is None
        else:
            assert updated["queryText"] == hook.READ_ONLY_PRELUDE + sql

    @pytest.mark.parametrize("name", sorted(hook.PG_SAFE_FUNCTIONS))
    def test_allowlisted_pg_function_is_allowed(self, name):
        """허용 목록의 pg_ 함수 호출은 조회로 allow한다."""
        # given
        sql = f"SELECT {name}(1), pg_catalog.{name}(2)"
        # when
        output = decide(PG_ID, sql)
        # then
        assert decision_of(output) == "allow"


@pytest.mark.usefixtures("pg_path")
class TestPostgresAsk:
    @pytest.mark.parametrize("sql", params(PG_ASK))
    def test_postgres_non_read_asks(self, sql):
        """PostgreSQL 쓰기, 부수 효과, 판별 불가 쿼리는 파서와 정규식 두 경로 모두 ask한다."""
        # given
        connection_id = PG_ID
        # when
        output = decide(connection_id, sql)
        # then
        assert decision_of(output) == "ask"
        assert reason_of(output) == hook.ASK_REASON
        assert "updatedInput" not in output["hookSpecificOutput"]

    @pytest.mark.parametrize("sql", next_statement_cases(PG_KEYWORDS))
    def test_postgres_keyword_as_next_statement_asks(self, sql):
        """PostgreSQL 위험 키워드로 시작하는 뒤따르는 문장은 어떤 구분자로도 ask한다."""
        # given
        connection_id = PG_ID
        # when
        output = decide(connection_id, sql)
        # then
        assert decision_of(output) == "ask"

    @pytest.mark.parametrize("keyword", PG_FUNCTION_KEYWORDS + PG_RESERVED_STATEMENT_KEYWORDS)
    def test_postgres_risky_keyword_as_function_call_asks(self, keyword):
        """위험 함수 이름이나 예약어를 함수처럼 호출하면 두 경로 모두 ask한다."""
        # given
        sql = f"SELECT {keyword}(1)"
        # when
        output = decide(PG_ID, sql)
        # then
        assert decision_of(output) == "ask"

    @pytest.mark.parametrize("keyword", PG_FUNCTION_KEYWORDS)
    def test_postgres_risky_function_as_quoted_identifier_asks(self, keyword):
        """위험 함수 이름을 큰따옴표 식별자로 감싸 호출해도 두 경로 모두 ask한다."""
        # given
        sql = f'SELECT "{keyword}"(1)'
        # when
        output = decide(PG_ID, sql)
        # then
        assert decision_of(output) == "ask"

    @pytest.mark.parametrize("sql", pg_function_cases(PG_UNSAFE_PG_FUNCTIONS))
    def test_postgres_non_allowlisted_pg_function_asks(self, sql):
        """허용 목록에 없는 pg_ 함수 호출은 어떤 표기로도 ask한다."""
        # given
        connection_id = PG_ID
        # when
        output = decide(connection_id, sql)
        # then
        assert decision_of(output) == "ask"

    @pytest.mark.parametrize("sql", pg_function_cases(PG_UNSAFE_OTHER_FUNCTIONS))
    def test_postgres_side_effect_function_asks(self, sql):
        """부수 효과가 있는 확장 및 일반 함수 호출은 어떤 표기로도 ask한다."""
        # given
        connection_id = PG_ID
        # when
        output = decide(connection_id, sql)
        # then
        assert decision_of(output) == "ask"

    @pytest.mark.parametrize("sql", control_char_cases())
    def test_postgres_uncertain_characters_ask(self, sql):
        """PostgreSQL 제어 문자와 단독 CR은 어느 위치에 있어도 ask한다."""
        # given
        connection_id = PG_ID
        # when
        output = decide(connection_id, sql)
        # then
        assert decision_of(output) == "ask"

    @pytest.mark.parametrize(
        "sql",
        combo_cases(PG_ALLOW, PG_COMBO_SEPARATORS, PG_WRITES),
    )
    def test_postgres_read_followed_by_write_asks(self, sql):
        """PostgreSQL 조회 뒤에 두 번째 문장으로 쓰기가 이어지면 두 경로 모두 ask한다."""
        # given
        connection_id = PG_ID
        # when
        output = decide(connection_id, sql)
        # then
        assert decision_of(output) == "ask"

    def test_postgres_keyword_samples_cover_every_regex_alternative(self):
        """PostgreSQL 키워드 표본은 정규식의 모든 대안을 빠짐없이 덮는다."""
        # given
        alternatives = regex_alternatives(hook.RISKY)
        # when
        uncovered = [
            alt for alt in alternatives
            if not any(re.fullmatch(alt, kw, re.I) for kw in PG_KEYWORDS)
        ]
        unused = [
            kw for kw in PG_KEYWORDS
            if not any(re.fullmatch(alt, kw, re.I) for alt in alternatives)
        ]
        # then
        assert uncovered == []
        assert unused == []


@pytest.mark.usefixtures("pg_regex")
class TestPostgresRegexFallback:
    @pytest.mark.parametrize("sql", keyword_cases(PG_KEYWORDS))
    def test_risky_keyword_after_select_asks(self, sql):
        """정규식 경로는 위험 키워드가 SELECT 뒤 어떤 구분자로 붙어도 ask한다."""
        # given
        connection_id = PG_ID
        # when
        output = decide(connection_id, sql)
        # then
        assert decision_of(output) == "ask"

    @pytest.mark.parametrize("keyword", PG_STATEMENT_KEYWORDS)
    def test_statement_keyword_as_function_call_asks(self, keyword):
        """정규식 경로는 문장 키워드를 함수처럼 호출해도 ask한다."""
        # given
        sql = f"SELECT {keyword}(1)"
        # when
        output = decide(PG_ID, sql)
        # then
        assert decision_of(output) == "ask"

    @pytest.mark.parametrize("keyword", [k for k in PG_STATEMENT_KEYWORDS if " " not in k])
    def test_statement_keyword_as_quoted_identifier_asks(self, keyword):
        """정규식 경로는 문장 키워드를 큰따옴표 식별자로 감싸도 ask한다."""
        # given
        sql = f'SELECT "{keyword}"(1)'
        # when
        output = decide(PG_ID, sql)
        # then
        assert decision_of(output) == "ask"

    @pytest.mark.parametrize("sql", [pytest.param(sql, id=name) for name, sql, _ in PG_ASK_REGEX_ONLY])
    def test_keyword_collisions_ask_on_fallback(self, sql):
        """정규식 경로는 파서가 허용하는 식별자 충돌 쿼리도 ask한다."""
        # given
        connection_id = PG_ID
        # when
        output = decide(connection_id, sql)
        # then
        assert decision_of(output) == "ask"
        assert "updatedInput" not in output["hookSpecificOutput"]


@pytest.mark.usefixtures("pg_parser")
class TestPostgresParser:
    @pytest.mark.parametrize("sql,reason", [pytest.param(sql, reason, id=name) for name, sql, reason in PG_ASK_REGEX_ONLY])
    def test_identifier_collisions_are_judged_by_the_parser(self, sql, reason):
        """식별자 이름이 키워드와 겹치는 읽기 쿼리는 파서 경로에서 allow한다."""
        # given
        payload = make_payload(PG_ID, sql)
        # when
        output = hook.decide(payload["tool_input"])
        # then
        assert reason
        assert decision_of(output) == "allow"
        updated = output["hookSpecificOutput"].get("updatedInput")
        if "transaction_read_only" in sql:
            assert updated is None
        else:
            assert updated["queryText"] == hook.READ_ONLY_PRELUDE + sql

    @pytest.mark.parametrize("sql", [pytest.param(sql, id=name) for name, sql in PG_PARSER_ASK])
    def test_syntax_errors_ask(self, sql):
        """문법 오류가 있는 쿼리는 정규식으로 되돌리지 않고 ask한다."""
        # given
        connection_id = PG_ID
        # when
        output = decide(connection_id, sql)
        # then
        assert decision_of(output) == "ask"

    @pytest.mark.parametrize("keyword", PG_CALLABLE_STATEMENT_KEYWORDS)
    def test_statement_keyword_named_function_is_an_ordinary_call(self, keyword):
        """문장 키워드와 같은 이름의 함수 호출은 일반 함수 호출이라 읽기 전용 접두를 붙여 allow한다."""
        # given
        sql = f"SELECT {keyword}(1)"
        # when
        output = decide(PG_ID, sql)
        # then
        assert decision_of(output) == "allow"
        assert output["hookSpecificOutput"]["updatedInput"]["queryText"] == hook.READ_ONLY_PRELUDE + sql

    @pytest.mark.parametrize("keyword", [k for k in PG_STATEMENT_KEYWORDS if " " not in k])
    def test_quoted_statement_keyword_is_an_ordinary_identifier(self, keyword):
        """큰따옴표로 감싼 문장 키워드는 일반 식별자라 allow한다."""
        # given
        sql = f'SELECT "{keyword}" FROM t'
        # when
        output = decide(PG_ID, sql)
        # then
        assert decision_of(output) == "allow"

    def test_pglast_exception_does_not_fall_back_to_regex(self, monkeypatch):
        """파서가 예외를 내면 정규식으로 되돌리지 않고 ask한다."""
        # given
        def boom(sql):
            raise RuntimeError("parser failure")

        monkeypatch.setattr(hook.pglast_parser, "parse_sql_json", boom)
        # when
        output = decide(PG_ID, "SELECT 1")
        # then
        assert decision_of(output) == "ask"

    def test_backslash_check_uses_character_offsets_after_non_ascii_text(self):
        """한글과 이모지가 앞에 있어도 일반 문자열의 역슬래시 위치를 정확히 찾는다."""
        # given
        sqls = ["SELECT '한글', 'a\\b'", "SELECT '😀한', 'a\\b'", "SELECT 1 AS \"é😀\", E'x', 'a\\b'"]
        # when
        flags = [hook.has_plain_backslash_string(sql) for sql in sqls]
        # then
        assert flags == [True, True, True]

    def test_escape_and_dollar_strings_may_contain_backslashes(self):
        """E 문자열과 달러 인용 문자열의 역슬래시는 일반 문자열 규칙에 걸리지 않는다."""
        # given
        sqls = ["SELECT E'a\\nb'", "SELECT $$a\\b$$", "SELECT $t$a\\b$t$"]
        # when
        states = [hook.postgres_read_state(sql) for sql in sqls]
        # then
        assert states == [False, False, False]

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT 1; SELECT 2",
            "SELECT * FROM t WHERE a = ANY (SELECT b FROM u)",
            "WITH c AS (SELECT 1 a) SELECT * FROM c",
            "VALUES (1), (2)",
            "TABLE t",
            "SHOW ALL",
            "EXPLAIN SELECT 1",
            "EXPLAIN (VERBOSE, COSTS OFF) SELECT 1",
        ],
    )
    def test_read_statement_kinds_are_accepted(self, sql):
        """SELECT, VALUES, TABLE, SHOW, 분석하지 않는 EXPLAIN은 읽기로 판단한다."""
        # given
        statement = sql
        # when
        state = hook.postgres_read_state(statement)
        # then
        assert state is False

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM t WHERE a = ANY (SELECT nextval('s'))",
            "SELECT * FROM t, LATERAL pg_sleep(1)",
            "SELECT (SELECT pg_terminate_backend(1))",
            "WITH c AS (SELECT set_config('a', 'b', true)) SELECT * FROM c",
            "SELECT * FROM t UNION ALL SELECT * FROM u FOR UPDATE",
            "SELECT * FROM generate_series(1, 3) g, query_to_xml('delete from t', true, true, '')",
            "EXPLAIN VERBOSE DELETE FROM t",
            "EXPLAIN ANALYZE VERBOSE SELECT 1",
            "EXPLAIN (ANALYSE) SELECT 1",
            "EXPLAIN EXECUTE p",
            "EXPLAIN CREATE TABLE a AS SELECT 1",
            "SELECT 1 INTO TEMP x",
            "CREATE TABLE a AS SELECT 1",
            "SET LOCAL statement_timeout = 5000; DELETE FROM t",
            "SET LOCAL transaction_read_only = on; SET LOCAL work_mem = '1MB'; SELECT 1",
            "SET LOCAL transaction_read_only TO DEFAULT; SELECT 1",
            "SET LOCAL transaction_read_only = on, off; SELECT 1",
            "SELECT 1; SET LOCAL transaction_read_only = on",
            "SET LOCAL transaction_read_only = on",
            "SET statement_timeout = 5000; SELECT 1",
        ],
    )
    def test_nested_writes_and_side_effects_ask(self, sql):
        """서브쿼리, CTE, 집합 연산, EXPLAIN 안에 숨은 쓰기와 부수 효과 호출은 ask한다."""
        # given
        statement = sql
        # when
        state = hook.postgres_read_state(statement)
        # then
        assert state is None


class TestSanitize:
    @pytest.mark.parametrize("postgres", [True, False])
    @pytest.mark.parametrize("char", CONTROL_CHARS)
    def test_uncertain_character_raises(self, char, postgres):
        """판단이 애매한 문자가 있으면 정제 단계가 ValueError를 낸다."""
        # given
        sql = f"SELECT 1{char}"
        # when
        with pytest.raises(ValueError) as caught:
            hook.sanitize(sql, postgres)
        # then
        assert str(caught.value)

    @pytest.mark.parametrize("postgres", [True, False])
    def test_crlf_and_tab_are_accepted(self, postgres):
        """탭, 줄바꿈, CRLF는 그대로 받아들인다."""
        # given
        sql = "SELECT\t1\r\nFROM t\n"
        # when
        sanitized = hook.sanitize(sql, postgres)
        # then
        assert "SELECT" in sanitized and "FROM" in sanitized

    def test_postgres_quoted_identifier_is_unwrapped(self):
        """PostgreSQL 큰따옴표 식별자는 내용을 풀어 공백으로 감싼다."""
        # given
        sql = 'SELECT "pg_terminate_backend"(1)'
        # when
        sanitized = hook.sanitize(sql, True)
        # then
        assert re.search(r"pg_terminate_backend\s+\(1\)", sanitized)

    def test_postgres_quoted_identifier_unescapes_doubled_quotes_and_symbols(self):
        """큰따옴표 식별자의 이중 따옴표는 풀고 단어가 아닌 문자는 공백으로 바꾼다."""
        # given
        sql = 'SELECT "a""b-c"'
        # when
        sanitized = hook.sanitize(sql, True)
        # then
        assert "a b c" in sanitized

    def test_mssql_quoted_identifier_stays_placeholder(self):
        """MSSQL 큰따옴표 식별자는 내용을 숨긴 자리표시자로 바꾼다."""
        # given
        sql = 'SELECT "delete"'
        # when
        sanitized = hook.sanitize(sql, False)
        # then
        assert "delete" not in sanitized

    @pytest.mark.parametrize("sql", ["SELECT $", "SELECT $1", "SELECT a$$b$$", "SELECT x$y"])
    def test_postgres_stray_dollar_raises(self, sql):
        """PostgreSQL에서 달러 인용이 아닌 $는 ValueError를 낸다."""
        # given
        postgres = True
        # when
        with pytest.raises(ValueError) as caught:
            hook.sanitize(sql, postgres)
        # then
        assert str(caught.value)

    def test_mssql_dollar_is_left_alone(self):
        """MSSQL의 $는 정제 단계에서 오류를 내지 않는다."""
        # given
        sql = "SELECT $action"
        # when
        sanitized = hook.sanitize(sql, False)
        # then
        assert "$action" in sanitized

    @pytest.mark.parametrize("sql", ["SELECT 'a\\b'", "SELECT U&'x'", 'SELECT U&"x"', "SELECT 'abc"])
    def test_postgres_uncertain_literals_raise(self, sql):
        """PostgreSQL의 역슬래시 문자열, U& 문자열, 닫히지 않은 문자열은 ValueError를 낸다."""
        # given
        postgres = True
        # when
        with pytest.raises(ValueError) as caught:
            hook.sanitize(sql, postgres)
        # then
        assert str(caught.value)

    def test_mssql_backslash_string_is_accepted(self):
        """MSSQL 문자열의 역슬래시는 경로 표기로 흔하므로 받아들인다."""
        # given
        sql = "SELECT 'C:\\dir\\file'"
        # when
        sanitized = hook.sanitize(sql, False)
        # then
        assert "dir" not in sanitized


class TestKeywordBoundary:
    @pytest.mark.parametrize("char", ["1", "9", "$", ")", " ", "(", ",", "'", "]", "+"])
    def test_non_letter_before_keyword_does_not_block_match(self, char):
        """숫자, $, 기호가 앞에 있어도 위험 키워드를 찾는다."""
        # given
        text = f"x{char}insert y" if char in " (,)+" else f"SELECT 1{char}insert y"
        # when
        mssql_match = hook.MSSQL_RISKY.search(text)
        pg_match = hook.RISKY.search(text)
        # then
        assert mssql_match is not None
        assert pg_match is not None

    @pytest.mark.parametrize("prefix", ["a", "Z", "_", "한", "é"])
    def test_letter_or_underscore_before_keyword_blocks_match(self, prefix):
        """글자나 밑줄 바로 뒤의 키워드는 식별자의 일부로 보고 건너뛴다."""
        # given
        text = f"SELECT {prefix}insert"
        # when
        mssql_match = hook.MSSQL_RISKY.search(text)
        pg_match = hook.RISKY.search(text)
        # then
        assert mssql_match is None
        assert pg_match is None

    @pytest.mark.parametrize("prefix", ["@", "#"])
    def test_variable_or_temp_prefix_blocks_match(self, prefix):
        """@나 # 바로 뒤의 키워드는 변수나 임시 테이블 이름으로 본다."""
        # given
        text = f"SELECT {prefix}insert"
        # when
        mssql_match = hook.MSSQL_RISKY.search(text)
        # then
        assert mssql_match is None

    def test_full_width_keyword_is_folded_before_matching(self):
        """전각 키워드는 MSSQL과 PostgreSQL 정규식 경로에서 NFKC로 정규화해 위험 키워드로 판별한다."""
        # given
        sql = "SELECT 1 ＤＥＬＥＴＥ FROM t"
        # when
        mssql_read = hook.is_mssql_read(sql)
        pg_read = hook.postgres_read_state_regex(sql)
        # then
        assert mssql_read is False
        assert pg_read is None


class TestConnectionRules:
    @pytest.mark.parametrize("connection_id", APPROVAL_IDS)
    def test_approval_named_source_asks_for_pure_select(self, connection_id):
        """이름에 승인이 든 데이터 소스는 DB 종류와 관계없이 단순 SELECT도 ask하고 전용 사유를 쓴다."""
        # given
        sql = "SELECT 1"
        # when
        output = decide(connection_id, sql)
        # then
        assert decision_of(output) == "ask"
        assert reason_of(output) == hook.ALWAYS_ASK_REASON

    @pytest.mark.parametrize("connection_id", APPROVAL_IDS)
    def test_approval_named_source_asks_even_for_non_string_query(self, connection_id):
        """승인 소스는 queryText가 없거나 문자열이 아니어도 승인 사유로 ask한다."""
        # given
        tool_input = {"projectPath": str(PROJECT), "connectionId": connection_id, "queryText": 5}
        # when
        output = hook.decide(tool_input)
        # then
        assert decision_of(output) == "ask"
        assert reason_of(output) == hook.ALWAYS_ASK_REASON

    def test_unknown_uuid_asks(self):
        """dataSources.xml에 없는 uuid는 ask하고 미등록 연결 사유를 쓴다."""
        # given
        sql = "SELECT 1"
        # when
        output = decide(UNKNOWN_ID, sql)
        # then
        assert decision_of(output) == "ask"
        assert reason_of(output) == hook.UNKNOWN_REASON

    def test_unsupported_driver_asks(self):
        """mysql 같은 지원하지 않는 드라이버는 ask하고 전용 사유를 쓴다."""
        # given
        sql = "SELECT 1"
        # when
        output = decide(MYSQL_ID, sql)
        # then
        assert decision_of(output) == "ask"
        assert reason_of(output) == hook.UNSUPPORTED_REASON

    @pytest.mark.parametrize("project_path", [None, 5, ["x"], "", "relative/nowhere"])
    def test_missing_or_invalid_project_path_asks(self, project_path):
        """projectPath가 없거나 문자열이 아니거나 비었거나 가리키는 곳이 없으면 ask한다."""
        # given
        tool_input = {"projectPath": project_path, "connectionId": PG_ID, "queryText": "SELECT 1"}
        if project_path is None:
            del tool_input["projectPath"]
        # when
        output = hook.decide(tool_input)
        # then
        assert decision_of(output) == "ask"
        assert reason_of(output) == hook.UNKNOWN_REASON

    def test_missing_data_sources_file_asks(self, tmp_path):
        """.idea/dataSources.xml이 없으면 ask한다."""
        # given
        tool_input = {"projectPath": str(tmp_path), "connectionId": PG_ID, "queryText": "SELECT 1"}
        # when
        output = hook.decide(tool_input)
        # then
        assert decision_of(output) == "ask"
        assert reason_of(output) == hook.UNKNOWN_REASON

    @pytest.mark.parametrize(
        "content",
        ["", "not xml", "<project><data-source uuid=", "<project></project>", "<?xml version='1.0'?><project>"],
    )
    def test_invalid_or_empty_xml_asks(self, tmp_path, content):
        """XML이 비었거나 깨졌거나 data-source가 없으면 ask한다."""
        # given
        (tmp_path / ".idea").mkdir()
        (tmp_path / ".idea" / "dataSources.xml").write_text(content, encoding="utf-8")
        tool_input = {"projectPath": str(tmp_path), "connectionId": PG_ID, "queryText": "SELECT 1"}
        # when
        output = hook.decide(tool_input)
        # then
        assert decision_of(output) == "ask"
        assert reason_of(output) == hook.UNKNOWN_REASON

    def test_data_sources_path_that_is_a_directory_asks(self, tmp_path):
        """dataSources.xml 자리에 디렉터리가 있어도 ask한다."""
        # given
        (tmp_path / ".idea" / "dataSources.xml").mkdir(parents=True)
        tool_input = {"projectPath": str(tmp_path), "connectionId": PG_ID, "queryText": "SELECT 1"}
        # when
        output = hook.decide(tool_input)
        # then
        assert decision_of(output) == "ask"
        assert reason_of(output) == hook.UNKNOWN_REASON

    @pytest.mark.parametrize("driver", ["postgresql", "sqlserver.ms", "sqlserver", "azure.ms", "azure", "SQLSERVER.ms"])
    def test_supported_driver_refs_allow_a_plain_read(self, tmp_path, driver):
        """postgresql, sqlserver로 시작하는 값, azure로 시작하는 값은 단순 조회를 allow한다."""
        # given
        xml = f'<project><component><data-source name="x" uuid="u1"><driver-ref>{driver}</driver-ref></data-source></component></project>'
        (tmp_path / ".idea").mkdir()
        (tmp_path / ".idea" / "dataSources.xml").write_text(xml, encoding="utf-8")
        tool_input = {"projectPath": str(tmp_path), "connectionId": "u1", "queryText": "SELECT 1"}
        # when
        output = hook.decide(tool_input)
        # then
        assert decision_of(output) == "allow"

    @pytest.mark.parametrize("driver", ["mysql.8", "oracle", "postgresql.rds", "sqlite.xerial", "", "mssql"])
    def test_other_driver_refs_ask_as_unsupported(self, tmp_path, driver):
        """지원 목록에 없는 driver-ref는 값이 비어 있어도 ask한다."""
        # given
        xml = f'<project><component><data-source name="x" uuid="u1"><driver-ref>{driver}</driver-ref></data-source></component></project>'
        (tmp_path / ".idea").mkdir()
        (tmp_path / ".idea" / "dataSources.xml").write_text(xml, encoding="utf-8")
        tool_input = {"projectPath": str(tmp_path), "connectionId": "u1", "queryText": "SELECT 1"}
        # when
        output = hook.decide(tool_input)
        # then
        assert decision_of(output) == "ask"
        assert reason_of(output) == hook.UNSUPPORTED_REASON

    def test_source_without_driver_ref_asks_as_unsupported(self, tmp_path):
        """driver-ref 요소가 없는 데이터 소스는 ask한다."""
        # given
        xml = '<project><component><data-source name="x" uuid="u1"></data-source></component></project>'
        (tmp_path / ".idea").mkdir()
        (tmp_path / ".idea" / "dataSources.xml").write_text(xml, encoding="utf-8")
        tool_input = {"projectPath": str(tmp_path), "connectionId": "u1", "queryText": "SELECT 1"}
        # when
        output = hook.decide(tool_input)
        # then
        assert decision_of(output) == "ask"
        assert reason_of(output) == hook.UNSUPPORTED_REASON

    @pytest.mark.parametrize("connection_id", [None, 123, ["x"], {"a": 1}, True, ""])
    def test_non_string_connection_id_asks(self, connection_id):
        """문자열이 아니거나 빈 connectionId는 ask하고 미등록 연결 사유를 쓴다."""
        # given
        tool_input = {"projectPath": str(PROJECT), "connectionId": connection_id, "queryText": "SELECT 1"}
        # when
        output = hook.decide(tool_input)
        # then
        assert decision_of(output) == "ask"
        assert reason_of(output) == hook.UNKNOWN_REASON

    def test_missing_connection_id_asks(self):
        """connectionId가 없으면 ask하고 미등록 연결 사유를 쓴다."""
        # given
        tool_input = {"projectPath": str(PROJECT), "queryText": "SELECT 1"}
        # when
        output = hook.decide(tool_input)
        # then
        assert decision_of(output) == "ask"
        assert reason_of(output) == hook.UNKNOWN_REASON

    @pytest.mark.parametrize("connection_id", [PG_ID, MSSQL_ID, AZURE_ID])
    @pytest.mark.parametrize("query_text", [None, 1, ["SELECT 1"], {"q": "SELECT 1"}])
    def test_non_string_query_text_asks(self, connection_id, query_text):
        """문자열이 아닌 queryText는 지원하는 연결에서도 ask한다."""
        # given
        tool_input = {"projectPath": str(PROJECT), "connectionId": connection_id, "queryText": query_text}
        # when
        output = hook.decide(tool_input)
        # then
        assert decision_of(output) == "ask"
        assert reason_of(output) == hook.ASK_REASON

    @pytest.mark.parametrize("connection_id", [PG_ID, MSSQL_ID, AZURE_ID])
    def test_missing_query_text_asks(self, connection_id):
        """queryText가 없으면 지원하는 연결에서도 ask한다."""
        # given
        tool_input = {"projectPath": str(PROJECT), "connectionId": connection_id}
        # when
        output = hook.decide(tool_input)
        # then
        assert decision_of(output) == "ask"
        assert reason_of(output) == hook.ASK_REASON

    @pytest.mark.parametrize("tool_input", ["SELECT 1", None, [], 1, ["connectionId"]])
    def test_non_dict_tool_input_asks(self, tool_input):
        """tool_input이 객체가 아니면 ask한다."""
        # given
        value = tool_input
        # when
        output = hook.decide(value)
        # then
        assert decision_of(output) == "ask"
        assert reason_of(output) == hook.ASK_REASON

    @pytest.mark.parametrize("connection_id", READ_IDS)
    def test_every_supported_connection_allows_a_plain_read(self, connection_id):
        """지원하는 모든 데이터 소스에서 단순 조회는 allow한다."""
        # given
        sql = "SELECT 1"
        # when
        output = decide(connection_id, sql)
        # then
        assert decision_of(output) == "allow"

    def test_first_matching_uuid_wins_and_other_sources_are_ignored(self, tmp_path):
        """uuid가 같은 요소가 둘이면 먼저 나온 데이터 소스를 쓴다."""
        # given
        xml = (
            '<project><component>'
            '<data-source name="a" uuid="dup"><driver-ref>postgresql</driver-ref></data-source>'
            '<data-source name="b 승인" uuid="dup"><driver-ref>postgresql</driver-ref></data-source>'
            '</component></project>'
        )
        (tmp_path / ".idea").mkdir()
        (tmp_path / ".idea" / "dataSources.xml").write_text(xml, encoding="utf-8")
        tool_input = {"projectPath": str(tmp_path), "connectionId": "dup", "queryText": "SELECT 1"}
        # when
        output = hook.decide(tool_input)
        # then
        assert decision_of(output) == "allow"


class TestOutputContract:
    @pytest.mark.parametrize("connection_id,sql,is_read,path", CORE_CASES)
    def test_decision_is_never_deny(self, connection_id, sql, is_read, path, monkeypatch):
        """어떤 쿼리도 deny를 내지 않고 조회 여부에 맞게 allow 또는 ask만 낸다."""
        # given
        apply_path(monkeypatch, path)
        payload = make_payload(connection_id, sql)
        # when
        output = hook.decide(payload["tool_input"])
        # then
        assert decision_of(output) in ("allow", "ask")
        assert (decision_of(output) == "allow") is is_read

    @pytest.mark.parametrize("connection_id,sql,is_read,path", CORE_CASES)
    def test_codex_permission_request_allows_only_reads(self, connection_id, sql, is_read, path, monkeypatch):
        """Codex 권한 요청 모드는 조회에만 allow를 내고 나머지는 아무것도 내지 않는다."""
        # given
        apply_path(monkeypatch, path)
        payload = make_payload(connection_id, sql)
        # when
        output = hook.codex_permission_request(payload["tool_input"])
        # then
        if is_read:
            assert output == {
                "hookSpecificOutput": {
                    "hookEventName": "PermissionRequest",
                    "decision": {"behavior": "allow"},
                }
            }
        else:
            assert output is None

    @pytest.mark.parametrize("connection_id,sql,is_read,path", CORE_CASES)
    def test_codex_pre_tool_use_rewrites_only_postgres_reads_without_prelude(
        self, connection_id, sql, is_read, path, monkeypatch
    ):
        """Codex 사전 실행 모드는 읽기 전용 접두가 없는 PostgreSQL 조회에만 updatedInput과 allow를 낸다."""
        # given
        apply_path(monkeypatch, path)
        payload = make_payload(connection_id, sql)
        has_read_only_prelude = "transaction_read_only" in sql
        # when
        output = hook.codex_pre_tool_use(payload["tool_input"])
        # then
        if is_read and connection_id == PG_ID and not has_read_only_prelude:
            assert output["hookSpecificOutput"]["permissionDecision"] == "allow"
            assert output["hookSpecificOutput"]["updatedInput"]["queryText"] == hook.READ_ONLY_PRELUDE + sql
            assert "deny" not in json.dumps(output)
        else:
            assert output is None

    @pytest.mark.parametrize(
        "connection_id,payload",
        [
            (PG_APPROVAL_ID, make_payload(PG_APPROVAL_ID, "SELECT 1")),
            (MSSQL_APPROVAL_ID, make_payload(MSSQL_APPROVAL_ID, "SELECT 1")),
            (MYSQL_ID, make_payload(MYSQL_ID, "SELECT 1")),
            (UNKNOWN_ID, make_payload(UNKNOWN_ID, "SELECT 1")),
            (None, {"tool_input": {"projectPath": str(PROJECT), "queryText": "SELECT 1"}}),
            (PG_ID, {"tool_input": {"projectPath": str(PROJECT), "connectionId": PG_ID, "queryText": 1}}),
            (PG_ID, {"tool_input": "SELECT 1"}),
        ],
    )
    def test_codex_modes_stay_silent_for_unregistered_or_malformed_input(self, connection_id, payload):
        """등록되지 않았거나 형식이 잘못된 입력에는 Codex 두 모드 모두 아무것도 내지 않는다."""
        # given
        handlers = [hook.codex_permission_request, hook.codex_pre_tool_use]
        # when
        outputs = [handler(payload["tool_input"]) for handler in handlers]
        # then
        assert outputs == [None, None]


@pytest.mark.usefixtures("pg_path")
class TestJdbcEscapeAndInvisibleCharacters:
    @pytest.mark.parametrize("connection_id,sql", [pytest.param(c, s, id=n) for n, c, s in JDBC_ESCAPE_ASK])
    def test_jdbc_escape_outside_literals_asks(self, connection_id, sql):
        """문자열과 주석 밖의 중괄호(JDBC 이스케이프)는 ask한다."""
        # given
        payload = make_payload(connection_id, sql)
        # when
        output = hook.decide(payload["tool_input"])
        # then
        assert decision_of(output) == "ask"
        assert reason_of(output) == hook.ASK_REASON

    @pytest.mark.parametrize("connection_id,sql", [pytest.param(c, s, id=n) for n, c, s in INVISIBLE_ASK])
    def test_invisible_format_character_asks(self, connection_id, sql):
        """보이지 않는 서식 문자(Cf)가 어디에 있든 ask한다."""
        # given
        payload = make_payload(connection_id, sql)
        # when
        output = hook.decide(payload["tool_input"])
        # then
        assert decision_of(output) == "ask"
        assert reason_of(output) == hook.ASK_REASON

    @pytest.mark.parametrize("connection_id,sql", [pytest.param(c, s, id=n) for n, c, s in BRACE_ALLOW])
    def test_braces_inside_literals_and_comments_are_allowed(self, connection_id, sql):
        """문자열, 따옴표 식별자, 달러 인용, 주석 안의 중괄호는 조회로 allow한다."""
        # given
        payload = make_payload(connection_id, sql)
        # when
        output = hook.decide(payload["tool_input"])
        # then
        assert decision_of(output) == "allow"

    @pytest.mark.parametrize("postgres", [True, False])
    @pytest.mark.parametrize("char", INVISIBLE_CHARS)
    def test_sanitize_rejects_invisible_format_character(self, char, postgres):
        """정제 단계는 서식 문자가 있으면 ValueError를 낸다."""
        # given
        sql = f"SELECT 1 DEL{char}ETE"
        # when
        with pytest.raises(ValueError) as caught:
            hook.sanitize(sql, postgres)
        # then
        assert str(caught.value)

    @pytest.mark.parametrize("postgres", [True, False])
    @pytest.mark.parametrize("brace", ["{", "}"])
    def test_sanitize_rejects_brace_outside_literals(self, brace, postgres):
        """정제 단계는 리터럴 밖의 중괄호가 있으면 ValueError를 낸다."""
        # given
        sql = f"SELECT 1 {brace}"
        # when
        with pytest.raises(ValueError) as caught:
            hook.sanitize(sql, postgres)
        # then
        assert str(caught.value)


RAISERROR_LOG_ASK = [c for c in MSSQL_ASK if c[0].startswith("raiserror-")]
LOG_HINT_ALLOW = [
    c for c in MSSQL_ALLOW
    if c[0] in ("nolock", "nolock-hint-only", "log-function", "log-alias", "log-column-with-nolock")
]


class TestRaiserrorWithLog:
    @pytest.mark.parametrize("sql", params(RAISERROR_LOG_ASK))
    def test_claude_mode_asks_for_with_log(self, sql):
        """Claude 모드는 서버 오류 로그에 쓰는 WITH LOG를 ask로 출력하고 exit 0으로 끝난다."""
        # given
        stdin = json.dumps(make_payload(MSSQL_ID, sql))
        # when
        code, stdout, _ = run_script(stdin)
        # then
        assert code == 0
        assert decision_of(json.loads(stdout)) == "ask"

    @pytest.mark.parametrize("sql", params(RAISERROR_LOG_ASK))
    def test_codex_permission_request_is_silent_for_with_log(self, sql):
        """Codex 권한 요청 모드는 WITH LOG가 든 쿼리에 아무것도 출력하지 않는다."""
        # given
        stdin = json.dumps(make_payload(MSSQL_ID, sql))
        # when
        code, stdout, _ = run_script(stdin, CODEX_PERMISSION)
        # then
        assert code == 0
        assert stdout == ""

    @pytest.mark.parametrize("sql", params(LOG_HINT_ALLOW))
    def test_claude_mode_allows_table_hint_and_log_names(self, sql):
        """Claude 모드는 WITH (NOLOCK), LOG 함수, log 별칭 조회를 allow로 출력한다."""
        # given
        stdin = json.dumps(make_payload(MSSQL_ID, sql))
        # when
        code, stdout, _ = run_script(stdin)
        # then
        assert code == 0
        assert decision_of(json.loads(stdout)) == "allow"

    @pytest.mark.parametrize("sql", params(LOG_HINT_ALLOW))
    def test_codex_permission_request_allows_table_hint_and_log_names(self, sql):
        """Codex 권한 요청 모드는 WITH (NOLOCK), LOG 함수, log 별칭 조회에 allow를 출력한다."""
        # given
        stdin = json.dumps(make_payload(MSSQL_ID, sql))
        # when
        code, stdout, _ = run_script(stdin, CODEX_PERMISSION)
        # then
        assert code == 0
        assert json.loads(stdout)["hookSpecificOutput"]["decision"] == {"behavior": "allow"}


class TestEndToEnd:
    @pytest.mark.parametrize("connection_id,sql", [pytest.param(c, s, id=n) for n, c, s in JDBC_ESCAPE_ASK + INVISIBLE_ASK])
    def test_claude_mode_asks_for_jdbc_escape_and_invisible_characters(self, connection_id, sql):
        """Claude 모드는 JDBC 이스케이프와 서식 문자가 든 쿼리에 ask를 출력하고 exit 0으로 끝난다."""
        # given
        stdin = json.dumps(make_payload(connection_id, sql))
        # when
        code, stdout, _ = run_script(stdin)
        # then
        assert code == 0
        assert decision_of(json.loads(stdout)) == "ask"

    @pytest.mark.parametrize("connection_id,sql", [pytest.param(c, s, id=n) for n, c, s in JDBC_ESCAPE_ASK + INVISIBLE_ASK])
    def test_codex_permission_request_is_silent_for_jdbc_escape_and_invisible_characters(self, connection_id, sql):
        """Codex 권한 요청 모드는 JDBC 이스케이프와 서식 문자가 든 쿼리에 아무것도 출력하지 않는다."""
        # given
        stdin = json.dumps(make_payload(connection_id, sql))
        # when
        code, stdout, _ = run_script(stdin, CODEX_PERMISSION)
        # then
        assert code == 0
        assert stdout == ""

    @pytest.mark.parametrize("connection_id,sql", [pytest.param(c, s, id=n) for n, c, s in BRACE_ALLOW])
    def test_claude_mode_allows_braces_inside_literals(self, connection_id, sql):
        """Claude 모드는 리터럴 안의 중괄호가 든 조회를 allow로 출력한다."""
        # given
        stdin = json.dumps(make_payload(connection_id, sql))
        # when
        code, stdout, _ = run_script(stdin)
        # then
        assert code == 0
        assert decision_of(json.loads(stdout)) == "allow"

    @pytest.mark.parametrize("connection_id,sql", [pytest.param(c, s, id=n) for n, c, s in BRACE_ALLOW])
    def test_codex_permission_request_allows_braces_inside_literals(self, connection_id, sql):
        """Codex 권한 요청 모드는 리터럴 안의 중괄호가 든 조회에 allow를 출력한다."""
        # given
        stdin = json.dumps(make_payload(connection_id, sql))
        # when
        code, stdout, _ = run_script(stdin, CODEX_PERMISSION)
        # then
        assert code == 0
        assert json.loads(stdout)["hookSpecificOutput"]["decision"] == {"behavior": "allow"}

    @pytest.mark.parametrize(
        "connection_id,sql,expected,has_update",
        [
            (PG_ID, "SELECT 1", "allow", True),
            (PG_ID, "SET LOCAL transaction_read_only = on; SELECT 1", "allow", False),
            (PG_ID, "DELETE FROM t", "ask", False),
            (PG_ID, "SELECT pg_sleep(1)", "ask", False),
            (MSSQL_ID, "SELECT 1", "allow", False),
            (MSSQL_ID, MSSQL_CORPUS_QUERY, "allow", False),
            (MSSQL_ID, "SELECT 1INSERT dbo.T VALUES (1)", "ask", False),
            (MSSQL_ID, "SELECT 1\rDELETE FROM dbo.T", "ask", False),
            (AZURE_ID, "SELECT 1", "allow", False),
            (PG_APPROVAL_ID, "SELECT 1", "ask", False),
            (MSSQL_APPROVAL_ID, "SELECT 1", "ask", False),
            (AZURE_APPROVAL_ID, "SELECT 1", "ask", False),
            (MYSQL_ID, "SELECT 1", "ask", False),
            (UNKNOWN_ID, "SELECT 1", "ask", False),
        ],
    )
    def test_claude_mode_prints_decision_and_exits_zero(self, connection_id, sql, expected, has_update):
        """Claude 모드는 판단 JSON을 출력하고 항상 exit 0으로 끝난다."""
        # given
        stdin = json.dumps(make_payload(connection_id, sql))
        # when
        code, stdout, _ = run_script(stdin)
        # then
        output = json.loads(stdout)
        assert code == 0
        assert decision_of(output) == expected
        assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert ("updatedInput" in output["hookSpecificOutput"]) is has_update

    @pytest.mark.parametrize("stdin", ["", "not json", "{", "[]", "null", "7", b"\xff\xfe\x00"])
    def test_claude_mode_stays_silent_for_unparsable_stdin(self, stdin):
        """Claude 모드는 JSON으로 읽을 수 없는 입력에 출력 없이 exit 0으로 끝난다."""
        # given
        data = stdin
        # when
        code, stdout, _ = run_script(data)
        # then
        assert code == 0
        assert stdout == ""

    @pytest.mark.parametrize("tool_input", [None, "x", [], 5])
    def test_claude_mode_asks_for_datagrip_event_with_malformed_tool_input(self, tool_input):
        """DataGrip 도구 이벤트인데 tool_input이 객체가 아니면 ask를 출력하고 exit 0으로 끝난다."""
        # given
        event = {"tool_name": TOOL_NAME, "hook_event_name": "PreToolUse", "tool_input": tool_input}
        # when
        code, stdout, _ = run_script(event)
        # then
        assert code == 0
        assert decision_of(json.loads(stdout)) == "ask"

    @pytest.mark.parametrize("event", [{}, {"tool_name": TOOL_NAME}, {"hook_event_name": "PreToolUse"}])
    def test_events_without_tool_name_or_event_name_stay_silent(self, event):
        """도구 이름이나 이벤트 이름이 없는 이벤트는 두 호스트 모두 출력이 없다."""
        # given
        claude_event = event
        # when
        claude = run_script(claude_event)
        codex = run_script(claude_event, CODEX_PRE_TOOL)
        # then
        assert claude[0] == codex[0] == 0
        assert claude[1] == codex[1] == ""

    @pytest.mark.parametrize(
        "connection_id,sql,expect_allow",
        [
            (PG_ID, "SELECT 1", True),
            (PG_ID, "SELECT 1; DELETE FROM t", False),
            (PG_ID, "SELECT pg_sleep(1)", False),
            (MSSQL_ID, "SELECT 1", True),
            (MSSQL_ID, MSSQL_CORPUS_QUERY, True),
            (MSSQL_ID, "SELECT 1INSERT dbo.T VALUES (1)", False),
            (AZURE_ID, "SELECT 1", True),
            (PG_APPROVAL_ID, "SELECT 1", False),
            (MSSQL_APPROVAL_ID, "SELECT 1", False),
            (MYSQL_ID, "SELECT 1", False),
            (UNKNOWN_ID, "SELECT 1", False),
        ],
    )
    def test_codex_permission_request_prints_allow_only_for_reads(self, connection_id, sql, expect_allow):
        """Codex 권한 요청 모드는 조회에만 allow를 출력하고 나머지는 출력 없이 exit 0으로 끝난다."""
        # given
        stdin = json.dumps(make_payload(connection_id, sql))
        # when
        code, stdout, _ = run_script(stdin, CODEX_PERMISSION)
        # then
        assert code == 0
        if expect_allow:
            assert json.loads(stdout) == {
                "hookSpecificOutput": {
                    "hookEventName": "PermissionRequest",
                    "decision": {"behavior": "allow"},
                }
            }
        else:
            assert stdout == ""
        assert "deny" not in stdout

    @pytest.mark.parametrize(
        "connection_id,sql,expect_update",
        [
            (PG_ID, "SELECT 1", True),
            (PG_ID, "SET LOCAL transaction_read_only = on; SELECT 1", False),
            (PG_ID, "SELECT 1; DELETE FROM t", False),
            (MSSQL_ID, "SELECT 1", False),
            (MSSQL_ID, MSSQL_CORPUS_QUERY, False),
            (MSSQL_ID, "DELETE FROM dbo.T", False),
            (AZURE_ID, "SELECT 1", False),
            (PG_APPROVAL_ID, "SELECT 1", False),
            (MSSQL_APPROVAL_ID, "SELECT 1", False),
            (MYSQL_ID, "SELECT 1", False),
            (UNKNOWN_ID, "SELECT 1", False),
        ],
    )
    def test_codex_pre_tool_use_prints_update_only_for_postgres_reads(self, connection_id, sql, expect_update):
        """Codex 사전 실행 모드는 읽기 전용 접두가 없는 PostgreSQL 조회에만 updatedInput과 allow를 출력한다."""
        # given
        stdin = json.dumps(make_payload(connection_id, sql))
        # when
        code, stdout, _ = run_script(stdin, CODEX_PRE_TOOL)
        # then
        assert code == 0
        if expect_update:
            output = json.loads(stdout)
            assert output["hookSpecificOutput"]["permissionDecision"] == "allow"
            assert output["hookSpecificOutput"]["updatedInput"]["queryText"] == hook.READ_ONLY_PRELUDE + sql
        else:
            assert stdout == ""
        assert "deny" not in stdout

    @pytest.mark.parametrize("mode", [CODEX_PERMISSION, CODEX_PRE_TOOL])
    @pytest.mark.parametrize("stdin", ["", "not json", "{}", "[]", '{"tool_input": null}', b"\xff\xfe\x00"])
    def test_codex_modes_stay_silent_for_malformed_stdin(self, mode, stdin):
        """Codex 두 모드는 입력이 깨졌을 때 출력 없이 exit 0으로 끝난다."""
        # given
        data = stdin
        # when
        code, stdout, _ = run_script(data, mode)
        # then
        assert code == 0
        assert stdout == ""

    def test_dev_null_stdin_stays_silent_and_exits_zero(self):
        """표준 입력이 비어 있으면 출력 없이 exit 0으로 끝난다."""
        # given
        command = [sys.executable, str(HOOK_PATH)]
        # when
        completed = subprocess.run(
            command, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, env=script_env()
        )
        # then
        assert completed.returncode == 0
        assert completed.stdout == ""


class TestEventAndHostDispatch:
    @pytest.mark.parametrize("tool_name", ["mcp__datagrip__other_tool", "Bash", "", None, 5])
    @pytest.mark.parametrize("host_mode", [None, CODEX_PRE_TOOL, CODEX_PERMISSION])
    def test_other_tools_get_no_output(self, tool_name, host_mode):
        """다른 도구 이름의 이벤트는 호스트와 이벤트 종류에 관계없이 출력이 없다."""
        # given
        event = {"tool_name": tool_name, "tool_input": make_tool_input(PG_ID, "SELECT 1")}
        args = (host_mode,) if host_mode else ()
        # when
        code, stdout, _ = run_script(event, *args)
        # then
        assert code == 0
        assert stdout == ""

    @pytest.mark.parametrize("sql", ["SELECT 1", "DELETE FROM t"])
    def test_claude_permission_request_gets_no_output(self, sql):
        """Claude Code의 PermissionRequest 이벤트는 조회든 쓰기든 출력이 없다."""
        # given
        event = {"hook_event_name": "PermissionRequest", "tool_input": make_tool_input(PG_ID, sql)}
        # when
        code, stdout, _ = run_script(event)
        # then
        assert code == 0
        assert stdout == ""

    @pytest.mark.parametrize("event_name", ["PostToolUse", "Stop", "SessionStart", "Notification", None, 3])
    @pytest.mark.parametrize("host_mode", [None, CODEX_PRE_TOOL])
    def test_other_event_names_get_no_output(self, event_name, host_mode):
        """처리하지 않는 이벤트 이름은 두 호스트 모두 출력이 없다."""
        # given
        event = {"hook_event_name": event_name, "tool_input": make_tool_input(PG_ID, "SELECT 1")}
        args = (host_mode,) if host_mode else ()
        # when
        code, stdout, _ = run_script(event, *args)
        # then
        assert code == 0
        assert stdout == ""

    def test_claude_pre_tool_use_prints_permission_decision_with_reason(self):
        """PLUGIN_ROOT가 없으면 Claude Code로 보고 사유가 든 permissionDecision을 출력한다."""
        # given
        event = {"tool_input": make_tool_input(MSSQL_ID, "SELECT 1")}
        # when
        code, stdout, _ = run_script(event)
        # then
        output = json.loads(stdout)["hookSpecificOutput"]
        assert code == 0
        assert output["hookEventName"] == "PreToolUse"
        assert output["permissionDecision"] == "allow"
        assert output["permissionDecisionReason"] == hook.MSSQL_ALLOW_REASON

    def test_plugin_root_at_the_repository_selects_codex(self):
        """PLUGIN_ROOT가 플러그인 루트이면 Codex로 보고 SQL Server 조회에는 출력이 없다."""
        # given
        event = {"tool_input": make_tool_input(MSSQL_ID, "SELECT 1")}
        # when
        code, stdout, _ = run_script(event, extra_env={"PLUGIN_ROOT": str(REPO_ROOT)})
        # then
        assert code == 0
        assert stdout == ""

    def test_codex_pre_tool_use_prints_allow_without_reason_for_postgres_read(self):
        """Codex PreToolUse는 PostgreSQL 조회에 읽기 전용 접두를 붙인 updatedInput과 allow만 출력한다."""
        # given
        event = {"tool_input": make_tool_input(PG_ID, "SELECT 1")}
        # when
        code, stdout, _ = run_script(event, CODEX_PRE_TOOL)
        # then
        output = json.loads(stdout)["hookSpecificOutput"]
        assert code == 0
        assert output == {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": make_tool_input(PG_ID, hook.READ_ONLY_PRELUDE + "SELECT 1"),
        }

    @pytest.mark.parametrize("plugin_root", ["", "/nonexistent/elsewhere"])
    def test_other_plugin_root_selects_claude(self, plugin_root):
        """PLUGIN_ROOT가 비었거나 다른 경로이면 Claude Code 규칙으로 판단한다."""
        # given
        event = {"tool_input": make_tool_input(PG_ID, "DELETE FROM t")}
        # when
        code, stdout, _ = run_script(event, extra_env={"PLUGIN_ROOT": plugin_root})
        # then
        assert code == 0
        assert decision_of(json.loads(stdout)) == "ask"

    @pytest.mark.parametrize("connection_id", APPROVAL_IDS + [MYSQL_ID, UNKNOWN_ID])
    def test_codex_never_allows_approval_or_unsupported_sources(self, connection_id):
        """승인 소스, 지원하지 않는 소스, 모르는 소스는 Codex 두 이벤트 모두 출력이 없다."""
        # given
        event = {"tool_input": make_tool_input(connection_id, "SELECT 1")}
        # when
        pre = run_script(event, CODEX_PRE_TOOL)
        permission = run_script(event, CODEX_PERMISSION)
        # then
        assert pre[0] == permission[0] == 0
        assert pre[1] == permission[1] == ""

    def test_never_denies_in_any_dispatch_branch(self):
        """어느 호스트와 이벤트에서도 출력에 deny가 들어가지 않는다."""
        # given
        sqls = ["SELECT 1", "DELETE FROM t", "SELECT pg_sleep(1)", ""]
        outputs = []
        # when
        for sql in sqls:
            for args in ((), (CODEX_PRE_TOOL,), (CODEX_PERMISSION,)):
                outputs.append(run_script({"tool_input": make_tool_input(PG_ID, sql)}, *args)[1])
        # then
        assert all("deny" not in output for output in outputs)


class TestHooksRegistration:
    @pytest.mark.parametrize("event_name", ["PreToolUse", "PermissionRequest"])
    def test_datagrip_guard_entry_exists_with_matcher_command_and_timeout(self, event_name):
        """PreToolUse와 PermissionRequest에 DataGrip 쿼리 도구만 잡는 matcher로 가드가 등록돼 있다."""
        # given
        expected = {
            "matcher": "^mcp__datagrip__execute_sql_query$",
            "hooks": [
                {"type": "command", "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/datagrip_guard.py"', "timeout": 10}
            ],
        }
        # when
        groups = HOOKS[event_name]
        # then
        assert expected in groups

    def test_matcher_matches_only_the_query_tool(self):
        """등록된 matcher 정규식은 쿼리 실행 도구 이름만 고른다."""
        # given
        matcher = HOOKS["PreToolUse"][-1]["matcher"]
        # when
        matches = {name: bool(re.search(matcher, name)) for name in (TOOL_NAME, "mcp__datagrip__list_tables", "x" + TOOL_NAME, TOOL_NAME + "x")}
        # then
        assert matches == {TOOL_NAME: True, "mcp__datagrip__list_tables": False, "x" + TOOL_NAME: False, TOOL_NAME + "x": False}

    def test_existing_agent_guard_entry_is_kept(self):
        """기존 Agent 가드 등록은 그대로 남아 있다."""
        # given
        expected = {
            "matcher": "Agent|Task",
            "hooks": [
                {"type": "command", "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/agent_guard.py"', "timeout": 5}
            ],
        }
        # when
        groups = HOOKS["PreToolUse"]
        # then
        assert expected in groups

    def test_registered_command_runs_from_the_plugin_root(self):
        """등록된 명령 문자열을 셸로 실행하면 DataGrip 쓰기 쿼리에 ask를 출력한다."""
        # given
        handler = HOOKS["PreToolUse"][-1]["hooks"][0]
        bin_dir = Path(_PROJECT_TEMP.name) / "bin"
        bin_dir.mkdir(exist_ok=True)
        link = bin_dir / "python3"
        if not link.exists():
            link.symlink_to(sys.executable)
        env = script_env(extra={"CLAUDE_PLUGIN_ROOT": str(REPO_ROOT), "PATH": f"{bin_dir}{os.pathsep}{os.defpath}"})
        event = {"tool_name": TOOL_NAME, "hook_event_name": "PreToolUse", "tool_input": make_tool_input(PG_ID, "DELETE FROM t")}
        # when
        completed = subprocess.run(
            handler["command"], shell=True, input=json.dumps(event), text=True, capture_output=True, env=env, timeout=60
        )
        # then
        assert completed.returncode == 0
        assert decision_of(json.loads(completed.stdout)) == "ask"


NO_PGLAST_BOOTSTRAP = "import runpy, sys; sys.modules['pglast'] = None; runpy.run_path(sys.argv.pop(1), run_name='__main__')"
PARSER_ONLY_ALLOW_SQL = "SELECT comment, set_id, https_url FROM t"


def parser_state_dir(root):
    return Path(root) / "hei5enbug-agent-setup" / "sql-parser" / "bin"


def install_fake_parser_python(root):
    interpreter = parser_state_dir(root) / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    interpreter.chmod(interpreter.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return interpreter


def run_without_pglast(event, state_root, *args, extra_env=None):
    env = script_env("codex" if args else "claude", {"XDG_STATE_HOME": str(state_root), **(extra_env or {})})
    stdin = json.dumps({"tool_name": TOOL_NAME, "hook_event_name": "PreToolUse", **event}).encode("utf-8")
    if CODEX_PERMISSION in args:
        stdin = json.dumps({"tool_name": TOOL_NAME, "hook_event_name": "PermissionRequest", **event}).encode("utf-8")
    completed = subprocess.run(
        [sys.executable, "-c", NO_PGLAST_BOOTSTRAP, str(HOOK_PATH)], input=stdin, capture_output=True, env=env, timeout=60
    )
    return completed.returncode, completed.stdout.decode("utf-8")


class TestParserReexec:
    def test_parser_python_follows_xdg_state_home(self, monkeypatch, tmp_path):
        """파서 인터프리터 위치는 XDG_STATE_HOME 아래이고 없으면 홈의 .local/state 아래다."""
        # given
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        with_xdg = hook.parser_python()
        monkeypatch.delenv("XDG_STATE_HOME")
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        without_xdg = hook.parser_python()
        # when
        locations = (with_xdg, without_xdg)
        # then
        assert locations == (
            tmp_path / "hei5enbug-agent-setup" / "sql-parser" / "bin" / "python",
            Path.home() / ".local" / "state" / "hei5enbug-agent-setup" / "sql-parser" / "bin" / "python",
        )

    def test_missing_pglast_reexecs_into_the_parser_environment(self, tmp_path):
        """pglast가 없는 인터프리터는 상태 폴더의 파서 파이썬으로 다시 실행해 파서 경로의 결정을 낸다."""
        # given
        install_fake_parser_python(tmp_path)
        event = {"tool_input": make_tool_input(PG_ID, PARSER_ONLY_ALLOW_SQL)}
        # when
        code, stdout = run_without_pglast(event, tmp_path)
        # then
        output = json.loads(stdout)
        assert code == 0
        assert decision_of(output) == "allow"
        assert output["hookSpecificOutput"]["updatedInput"]["queryText"] == hook.READ_ONLY_PRELUDE + PARSER_ONLY_ALLOW_SQL

    def test_reexec_uses_home_state_directory_without_xdg(self, tmp_path):
        """XDG_STATE_HOME이 없으면 홈 아래 .local/state의 파서 파이썬을 쓴다."""
        # given
        install_fake_parser_python(tmp_path / ".local" / "state")
        event = {"tool_input": make_tool_input(PG_ID, PARSER_ONLY_ALLOW_SQL)}
        env = script_env(extra={"XDG_STATE_HOME": None, "HOME": str(tmp_path)})
        stdin = json.dumps({"tool_name": TOOL_NAME, "hook_event_name": "PreToolUse", **event}).encode("utf-8")
        # when
        completed = subprocess.run(
            [sys.executable, "-c", NO_PGLAST_BOOTSTRAP, str(HOOK_PATH)], input=stdin, capture_output=True, env=env, timeout=60
        )
        # then
        assert completed.returncode == 0
        assert decision_of(json.loads(completed.stdout)) == "allow"

    @pytest.mark.parametrize("mode", [CODEX_PERMISSION, CODEX_PRE_TOOL])
    def test_codex_events_match_after_reexec(self, tmp_path, mode):
        """Codex 두 이벤트도 다시 실행한 뒤 파서 경로와 같은 출력을 낸다."""
        # given
        install_fake_parser_python(tmp_path)
        event = {"tool_input": make_tool_input(PG_ID, PARSER_ONLY_ALLOW_SQL)}
        extra = {"PLUGIN_ROOT": str(REPO_ROOT)}
        # when
        code, stdout = run_without_pglast(event, tmp_path, mode, extra_env=extra)
        # then
        output = json.loads(stdout)["hookSpecificOutput"]
        assert code == 0
        if mode == CODEX_PERMISSION:
            assert output["decision"] == {"behavior": "allow"}
        else:
            assert output["updatedInput"]["queryText"] == hook.READ_ONLY_PRELUDE + PARSER_ONLY_ALLOW_SQL

    def test_write_still_asks_after_reexec(self, tmp_path):
        """다시 실행한 뒤에도 쓰기 쿼리는 ask한다."""
        # given
        install_fake_parser_python(tmp_path)
        event = {"tool_input": make_tool_input(PG_ID, "SELECT 1; DELETE FROM t")}
        # when
        code, stdout = run_without_pglast(event, tmp_path)
        # then
        assert code == 0
        assert decision_of(json.loads(stdout)) == "ask"

    def test_guard_variable_stops_a_second_exec(self, tmp_path):
        """HEI5ENBUG_SQL_PARSER_REEXEC가 있으면 다시 실행하지 않고 정규식 경로로 ask한다."""
        # given
        install_fake_parser_python(tmp_path)
        event = {"tool_input": make_tool_input(PG_ID, PARSER_ONLY_ALLOW_SQL)}
        # when
        code, stdout = run_without_pglast(event, tmp_path, extra_env={"HEI5ENBUG_SQL_PARSER_REEXEC": "1"})
        # then
        assert code == 0
        assert decision_of(json.loads(stdout)) == "ask"

    def test_missing_parser_environment_uses_the_regex_path(self, tmp_path):
        """파서 환경이 없으면 정규식 경로를 쓰므로 키워드와 겹치는 식별자는 ask하고 일반 조회는 allow한다."""
        # given
        collision = {"tool_input": make_tool_input(PG_ID, PARSER_ONLY_ALLOW_SQL)}
        plain = {"tool_input": make_tool_input(PG_ID, "SELECT 1")}
        # when
        asked = run_without_pglast(collision, tmp_path)
        allowed = run_without_pglast(plain, tmp_path)
        # then
        assert asked[0] == allowed[0] == 0
        assert decision_of(json.loads(asked[1])) == "ask"
        assert decision_of(json.loads(allowed[1])) == "allow"

    def test_unexecutable_parser_python_falls_back_to_the_regex_path(self, tmp_path):
        """실행할 수 없는 파서 파이썬은 OSError를 넘기고 정규식 경로로 계속한다."""
        # given
        interpreter = parser_state_dir(tmp_path) / "python"
        interpreter.parent.mkdir(parents=True)
        interpreter.write_text("not executable", encoding="utf-8")
        interpreter.chmod(0o644)
        event = {"tool_input": make_tool_input(PG_ID, PARSER_ONLY_ALLOW_SQL)}
        # when
        code, stdout = run_without_pglast(event, tmp_path)
        # then
        assert code == 0
        assert decision_of(json.loads(stdout)) == "ask"

    def test_interpreter_with_pglast_never_reexecs(self, tmp_path):
        """pglast가 있는 인터프리터는 파서 환경이 있어도 다시 실행하지 않고 파서 경로로 판단한다."""
        # given
        marker = tmp_path / "executed"
        interpreter = parser_state_dir(tmp_path) / "python"
        interpreter.parent.mkdir(parents=True)
        interpreter.write_text(f'#!/bin/sh\ntouch "{marker}"\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
        interpreter.chmod(0o755)
        event = {"tool_name": TOOL_NAME, "hook_event_name": "PreToolUse", "tool_input": make_tool_input(PG_ID, PARSER_ONLY_ALLOW_SQL)}
        env = script_env(extra={"XDG_STATE_HOME": str(tmp_path)})
        # when
        completed = subprocess.run(
            [sys.executable, str(HOOK_PATH)], input=json.dumps(event).encode(), capture_output=True, env=env, timeout=60
        )
        # then
        assert completed.returncode == 0
        assert decision_of(json.loads(completed.stdout)) == "allow"
        assert not marker.exists()
