# Response language and DataGrip guards

This page explains how response-language checks and DataGrip query safeguards behave on each host.

## Response language

A language guard, `scripts/language_guard.py`, checks that every reply and every progress update is written in the
response language. Claude Code takes the language from the `language` setting, read from the local project settings,
then the project settings, then the user settings; without one, nothing is enforced. Codex reads
`HEI5ENBUG_RESPONSE_LANGUAGE` and uses Korean when it is unset. Only languages with a distinctive script are checked:
Korean, Japanese, Chinese, Russian, Ukrainian, Greek, Arabic, Hebrew, Thai, and Hindi. For any other language, such as
English or French, the instruction alone applies.

The check ignores code, quotes, and URLs. A text passes when at least 30% of its letters are in the target script, and
very short text always passes. A `Stop` hook asks for a rewrite when a reply fails, at most 3 times per turn. Delegated
child sessions are not checked: a session with `HEI5ENBUG_ASSIGNED_ROLE` or `HEI5ENBUG_PARENT_SESSION` set, such as a
role runner child, returns its answer to the coordinating session, which replies to the user. A `PostToolUse` hook adds
a reminder after a progress update in another language. It runs asynchronously, so the reminder reaches the model on the
next turn. Put text the user asks for in another language in a code block or block quote.

## DataGrip query guard

A `PreToolUse` hook on both hosts and a `PermissionRequest` hook on Codex only, both `scripts/datagrip_guard.py`, run
before the DataGrip MCP tool `execute_sql_query`. The guard reads the connection from `.idea/dataSources.xml` in the
DataGrip project that `projectPath` names. PostgreSQL and SQL Server reads on non-production, recognized connections run
without approval, and PostgreSQL reads run inside a read-only transaction with `SET LOCAL statement_timeout = '60s';`. A
production connection needs a recorded plan before a PostgreSQL read and gets lock safeguards on a SQL Server read; see
the [production read rules](approval-guard.md#production-database-reads). With `approval_guard` on, non-destructive
PostgreSQL and SQL Server writes share the session write approval (`write:session`) with all other writes. Unknown
connections, other database types, and text the guard cannot parse use that approval too; a `승인` in a connection name
has no effect of its own. A statement whose code names `delete`, `drop`, or `truncate`, and statements the SQL
classifier treats as destructive, including those led by `DO`, `EXEC`, `EXECUTE`, or `CALL`, ask every time. The code is
the text left after string literals, comments, and quoted or bracketed identifiers are removed, so a `SELECT` that only
mentions `delete` in one of them stays a read. On a non-production PostgreSQL connection (see [production database
reads](approval-guard.md#production-database-reads)), when the `pglast` parser confirms the text, a `DELETE` whose own
statement has a `WHERE`, and a `DO` block whose body parses as PL/pgSQL and has no `DROP`, `TRUNCATE`, `EXECUTE`,
`ALTER`, `GRANT`, `REVOKE`, `CALL`, nested `DO`, `DELETE` without `WHERE`, or risky function call (`set_config` and
`pg_sleep` are allowed there, quoted names included in the check), are session writes instead. SQL Server, which allows
statements without semicolons, and text the parser cannot confirm keep asking every time. SQL Server reads may also
carry `SET NOCOUNT`, `LOCK_TIMEOUT`, `DEADLOCK_PRIORITY`, `TRANSACTION ISOLATION LEVEL READ UNCOMMITTED|READ
COMMITTED|SNAPSHOT`, `ARITHABORT`, `ANSI_NULLS`, `ANSI_WARNINGS`, `ANSI_PADDING`, `QUOTED_IDENTIFIER`,
`CONCAT_NULL_YIELDS_NULL`, `XACT_ABORT`, `STATISTICS IO|TIME`, and `SHOWPLAN_XML|ALL|TEXT` statements. On Codex, a write
opens Codex's native approval window when it is ready, and is denied with a code otherwise; an every-time query is
always denied with a code; see [Approval guard](approval-guard.md#approval-guard). With the toggle off, every write asks
as before. In Codex, trust the hook in `/hooks`.

Optionally, install the `pglast` parser once:

```bash
uv venv --python 3.12 "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser"
uv pip install --python "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser/bin/python" pglast==8.4
```

Without it, PostgreSQL falls back to a stricter text check that may ask more often but still never lets a write run
without approval.
